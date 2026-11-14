"""Збереження «Моїх рослин».

* SupabaseStore — хмарна PostgreSQL (DBaaS) + Supabase Storage для мініатюр.
* LocalStore    — запасний варіант (SQLite на диску), якщо Supabase не налаштовано.
  Зручно для локального запуску без інтернету до бази.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

import config

log = logging.getLogger(__name__)


class StorageError(Exception):
    def __init__(self, message: str, code: int = 503):
        super().__init__(message)
        self.message = message
        self.code = code


def _row_from_analysis(analysis: dict) -> dict:
    r = analysis["result"]
    return {
        "common_name": r.get("common_name_uk") or "Невідома рослина",
        "latin_name": r.get("latin_name") or "",
        "family": r.get("family") or "",
        "confidence": int(r.get("confidence") or 0),
        "health_status": r.get("health_status") or "unknown",
        "has_problems": bool(r.get("problems")),
        "is_toxic_to_pets": any(r.get("toxicity", {}).get(k) in ("toxic", "mild") for k in ("cats", "dogs")),
        "result": r,
        "model": analysis.get("model") or "",
        "latency_ms": int(analysis.get("latency_ms") or 0),
        "cost_usd": analysis.get("cost_usd_paid_tier"),
    }


def compute_stats(items: list[dict]) -> dict:
    n = len(items)
    latencies = [i["latency_ms"] for i in items if i.get("latency_ms")]
    return {
        "total": n,
        "with_problems": sum(1 for i in items if i.get("has_problems")),
        "healthy": sum(1 for i in items if not i.get("has_problems")),
        "toxic_to_pets": sum(1 for i in items if i.get("is_toxic_to_pets")),
        "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else None,
        "total_cost_usd": round(sum(float(i.get("cost_usd") or 0) for i in items), 5),
    }


# ---------------------------------------------------------------------------
class SupabaseStore:
    kind = "supabase"
    label = "Supabase (PostgreSQL)"

    def __init__(self):
        from supabase import create_client

        self.client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
        self.table = config.SUPABASE_TABLE
        self.bucket = config.SUPABASE_BUCKET

    def _wrap(self, exc: Exception, action: str):
        log.exception("Supabase %s failed", action)
        text = str(exc)
        hint = ""
        if "relation" in text and "does not exist" in text or "PGRST205" in text:
            hint = " Таблицю не створено — виконайте supabase/schema.sql у SQL Editor."
        elif "Bucket not found" in text:
            hint = " Не знайдено bucket для фото — виконайте supabase/schema.sql."
        elif "Invalid API key" in text or "401" in text:
            hint = " Перевірте SUPABASE_SECRET_KEY."
        raise StorageError(f"Не вдалося {action} у Supabase.{hint}")

    def add(self, analysis: dict, thumb_jpeg: bytes | None) -> dict:
        row = _row_from_analysis(analysis)
        row["id"] = str(uuid.uuid4())
        try:
            if thumb_jpeg:
                path = f"{datetime.now(timezone.utc):%Y/%m}/{row['id']}.jpg"
                self.client.storage.from_(self.bucket).upload(
                    path, thumb_jpeg, {"content-type": "image/jpeg", "upsert": "true"}
                )
                row["thumb_path"] = path
                row["thumb_url"] = self.client.storage.from_(self.bucket).get_public_url(path)
            res = self.client.table(self.table).insert(row).execute()
            return res.data[0] if res.data else row
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._wrap(exc, "зберегти рослину")

    def list(self) -> list[dict]:
        try:
            res = self.client.table(self.table).select("*").order("created_at", desc=True).limit(200).execute()
            return res.data or []
        except Exception as exc:  # noqa: BLE001
            self._wrap(exc, "завантажити список рослин")

    def delete(self, plant_id: str) -> bool:
        try:
            res = self.client.table(self.table).delete().eq("id", plant_id).execute()
            rows = res.data or []
            paths = [r["thumb_path"] for r in rows if r.get("thumb_path")]
            if paths:
                try:
                    self.client.storage.from_(self.bucket).remove(paths)
                except Exception:  # мініатюра — не критично
                    log.warning("Не вдалося видалити мініатюру %s", paths)
            return bool(rows)
        except Exception as exc:  # noqa: BLE001
            self._wrap(exc, "видалити рослину")

    def ping(self) -> bool:
        try:
            self.client.table(self.table).select("id").limit(1).execute()
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
class LocalStore:
    kind = "local"
    label = "Локальна база SQLite"

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "plants.db")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.lock = threading.Lock()
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS plants (
                    id TEXT PRIMARY KEY, created_at TEXT, common_name TEXT, latin_name TEXT, family TEXT,
                    confidence INTEGER, health_status TEXT, has_problems INTEGER, is_toxic_to_pets INTEGER,
                    result TEXT, model TEXT, latency_ms INTEGER, cost_usd REAL, thumb_url TEXT)"""
            )

    def _conn(self):
        return sqlite3.connect(self.path)

    def add(self, analysis: dict, thumb_jpeg: bytes | None) -> dict:
        row = _row_from_analysis(analysis)
        row["id"] = str(uuid.uuid4())
        row["created_at"] = datetime.now(timezone.utc).isoformat()
        row["thumb_url"] = (
            "data:image/jpeg;base64," + base64.b64encode(thumb_jpeg).decode() if thumb_jpeg else None
        )
        with self.lock, self._conn() as c:
            c.execute(
                "INSERT INTO plants VALUES (:id,:created_at,:common_name,:latin_name,:family,:confidence,"
                ":health_status,:has_problems,:is_toxic_to_pets,:result,:model,:latency_ms,:cost_usd,:thumb_url)",
                {**row, "result": json.dumps(row["result"], ensure_ascii=False)},
            )
        return row

    def list(self) -> list[dict]:
        with self.lock, self._conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("SELECT * FROM plants ORDER BY created_at DESC LIMIT 200").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["result"] = json.loads(d["result"] or "{}")
            d["has_problems"] = bool(d["has_problems"])
            d["is_toxic_to_pets"] = bool(d["is_toxic_to_pets"])
            out.append(d)
        return out

    def delete(self, plant_id: str) -> bool:
        with self.lock, self._conn() as c:
            cur = c.execute("DELETE FROM plants WHERE id = ?", (plant_id,))
            return cur.rowcount > 0

    def ping(self) -> bool:
        return True


def make_store():
    if config.SUPABASE_URL and config.SUPABASE_KEY:
        try:
            return SupabaseStore()
        except Exception:  # noqa: BLE001
            log.exception("Supabase не вдалося ініціалізувати — використовую локальну базу")
    return LocalStore()

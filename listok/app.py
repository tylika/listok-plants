"""Листок — вебсервіс визначення рослин за фото на основі Google Gemini API.

Запуск локально:  python app.py   ->  http://127.0.0.1:5000
На Render:        gunicorn app:app (див. render.yaml)
"""
from __future__ import annotations

import base64
import logging
import os
import re
import time

from flask import Flask, jsonify, render_template, request
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

import config
import gemini_service
from gemini_service import GeminiError
from images import HEIF_SUPPORTED, ImageError, prepare_for_gemini, validate_thumbnail
from schema import PlantResult
from storage import StorageError, compute_stats, make_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
# Запас понад ліміт файлу на службові поля форми.
app.config["MAX_CONTENT_LENGTH"] = int((config.MAX_UPLOAD_MB + 1) * 1024 * 1024)
app.json.ensure_ascii = False

store = make_store()
STARTED_AT = time.time()
UUID_RE = re.compile(r"^[0-9a-f-]{36}$")


def error(message: str, code: int, kind: str, detail: str = ""):
    payload = {"ok": False, "error": message, "kind": kind}
    if detail:
        payload["detail"] = detail
    return jsonify(payload), code


# --- Сторінки -------------------------------------------------------------------
@app.context_processor
def inject_globals():
    return {
        "max_upload_mb": config.MAX_UPLOAD_MB,
        "flash_model": config.GEMINI_MODEL,
        "pro_model": config.GEMINI_PRO_MODEL,
        "mock_mode": config.GEMINI_MOCK,
        "store_label": store.label,
        "store_kind": store.kind,
        "asset_v": int(STARTED_AT),
    }


@app.get("/")
def index():
    return render_template("index.html", page="identify")


@app.get("/plants")
def plants_page():
    return render_template("plants.html", page="plants")


@app.get("/about")
def about_page():
    return render_template("about.html", page="about", pricing=config.PRICING_USD_PER_1M,
                           fallbacks=config.GEMINI_FALLBACK_MODELS)


# --- API ---------------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    """Перевірка стану. Зручно, щоб «розбудити» Render перед парою."""
    return jsonify(
        ok=True,
        gemini_configured=gemini_service.is_configured(),
        mock_mode=config.GEMINI_MOCK,
        model=config.GEMINI_MODEL,
        pro_model=config.GEMINI_PRO_MODEL,
        storage=store.kind,
        storage_ok=store.ping(),
        heic_supported=HEIF_SUPPORTED,
        uptime_s=int(time.time() - STARTED_AT),
    )


@app.post("/api/identify")
def api_identify():
    file = request.files.get("photo")
    if file is None or not file.filename and not file.content_length:
        return error("Не отримано фото. Виберіть або зробіть знімок рослини.", 400, "no_file")
    mode = request.form.get("mode", "flash")
    if mode not in ("flash", "pro"):
        mode = "flash"
    if file.mimetype and not (file.mimetype.startswith("image/") or file.mimetype == "application/octet-stream"):
        return error("Можна завантажувати лише зображення (JPG, PNG, WEBP, HEIC).", 415, "bad_file")

    raw = file.read()
    t0 = time.monotonic()
    try:
        img_bytes, mime, thumb = prepare_for_gemini(raw)
    except ImageError as e:
        return error(e.message, e.code, e.kind)
    prep_ms = int((time.monotonic() - t0) * 1000)

    try:
        data = gemini_service.identify(img_bytes, mime, mode)
    except GeminiError as e:
        return error(e.message, e.code, e.kind, e.detail)
    except Exception as e:  # noqa: BLE001 — сервер не повинен «падати»
        log.exception("Unexpected identify error")
        return error("Сталася непередбачена помилка на сервері. Спробуйте ще раз.", 500, "server", type(e).__name__)

    data["ok"] = True
    data["prep_ms"] = prep_ms
    data["image_kb"] = round(len(img_bytes) / 1024)
    data["original_kb"] = round(len(raw) / 1024)
    data["thumb_data_url"] = "data:image/jpeg;base64," + base64.b64encode(thumb).decode()
    return jsonify(data)


@app.get("/api/plants")
def api_plants():
    try:
        items = store.list()
    except StorageError as e:
        return error(e.message, e.code, "storage")
    return jsonify(ok=True, items=items, stats=compute_stats(items), storage=store.kind)


@app.post("/api/plants")
def api_save_plant():
    body = request.get_json(silent=True) or {}
    analysis = body.get("analysis") or {}
    try:
        result = PlantResult.model_validate(analysis.get("result") or {})
    except ValidationError:
        return error("Некоректні дані результату. Визначте рослину ще раз.", 400, "bad_payload")
    if not result.is_plant:
        return error("На фото не знайдено рослину — зберігати нічого.", 400, "not_plant")

    thumb = None
    data_url = body.get("thumb_data_url") or ""
    if data_url.startswith("data:image/"):
        try:
            thumb = validate_thumbnail(base64.b64decode(data_url.split(",", 1)[1], validate=True))
        except (ImageError, ValueError, IndexError):
            thumb = None  # без мініатюри теж збережемо

    clean = {
        "result": result.model_dump(mode="json"),
        "model": str(analysis.get("model", ""))[:60],
        "latency_ms": int(analysis.get("latency_ms") or 0),
        "cost_usd_paid_tier": analysis.get("cost_usd_paid_tier") if isinstance(analysis.get("cost_usd_paid_tier"), (int, float)) else None,
    }
    try:
        saved = store.add(clean, thumb)
    except StorageError as e:
        return error(e.message, e.code, "storage")
    return jsonify(ok=True, item=saved), 201


@app.delete("/api/plants/<plant_id>")
def api_delete_plant(plant_id: str):
    if not UUID_RE.match(plant_id):
        return error("Некоректний ідентифікатор.", 400, "bad_id")
    try:
        deleted = store.delete(plant_id)
    except StorageError as e:
        return error(e.message, e.code, "storage")
    if not deleted:
        return error("Запис не знайдено — можливо, його вже видалено.", 404, "not_found")
    return jsonify(ok=True)


# --- Обробка помилок: завжди зрозуміла відповідь, без «падіння» ---------------
@app.errorhandler(RequestEntityTooLarge)
def too_large(_e):
    return error(f"Файл завеликий. Максимум — {config.MAX_UPLOAD_MB:g} МБ.", 413, "too_large")


@app.errorhandler(HTTPException)
def http_error(e: HTTPException):
    if request.path.startswith("/api/"):
        return error(e.description or "Помилка запиту.", e.code or 400, "http")
    return render_template("error.html", code=e.code, message=e.description), e.code


@app.errorhandler(Exception)
def unhandled(e: Exception):
    log.exception("Unhandled error")
    if request.path.startswith("/api/"):
        return error("Сталася непередбачена помилка на сервері.", 500, "server", type(e).__name__)
    return render_template("error.html", code=500, message="Сталася непередбачена помилка."), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"\n  Листок запущено: http://127.0.0.1:{port}\n  Сховище: {store.label}"
          f"{'   (ДЕМО-РЕЖИМ без Gemini)' if config.GEMINI_MOCK else ''}\n")
    app.run(host="0.0.0.0", port=port, debug=False)

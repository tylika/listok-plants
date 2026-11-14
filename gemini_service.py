"""Робота з Google Gemini API (модель AIaaS).

Ми не навчаємо модель і не маємо GPU: надсилаємо фото + інструкцію + JSON-схему
в хмарний API і отримуємо структуровану відповідь.

Надійність:
  * таймаут на кожен запит;
  * повторна спроба при тимчасових збоях (5xx, таймаут, обрив з'єднання);
  * при вичерпанні квоти (429) або недоступній моделі (404) — перехід на запасну модель;
  * кеш за хешем фото: те саме фото вдруге не витрачає квоту.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import random
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

import config
from schema import PROMPT, PlantResult

log = logging.getLogger(__name__)

try:  # SDK імпортуємо м'яко, щоб демо-режим працював навіть без нього
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types
except Exception:  # pragma: no cover
    genai = None
    genai_errors = None
    types = None


class GeminiError(Exception):
    """Помилка, яку можна показати користувачу. code -> HTTP-статус."""

    def __init__(self, message: str, code: int = 502, kind: str = "gemini_error", detail: str = ""):
        super().__init__(message)
        self.message = message
        self.code = code
        self.kind = kind
        self.detail = detail  # коротка технічна причина (для налагодження)


@dataclass
class _Attempt:
    model: str
    outcome: str
    ms: int


_client = None
_client_lock = threading.Lock()


def _get_client():
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                if genai is None:
                    raise GeminiError("Не встановлено бібліотеку google-genai.", 500, "config")
                if not config.GEMINI_API_KEY:
                    raise GeminiError(
                        "На сервері не задано ключ GEMINI_API_KEY. Додайте його у змінні середовища.",
                        503,
                        "config",
                    )
                _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def is_configured() -> bool:
    return config.GEMINI_MOCK or bool(config.GEMINI_API_KEY)


# --- Кеш результатів (LRU у пам'яті) --------------------------------------
_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_CACHE_MAX = 64
_cache_lock = threading.Lock()


def _cache_get(key: str):
    with _cache_lock:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return copy.deepcopy(_CACHE[key])
    return None


def _cache_put(key: str, value: dict):
    with _cache_lock:
        _CACHE[key] = copy.deepcopy(value)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


# --- Вартість ---------------------------------------------------------------
def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Вартість запиту на ПЛАТНОМУ рівні (на безкоштовному — $0)."""
    price = None
    for name, p in config.PRICING_USD_PER_1M.items():
        if model == name or model.startswith(name):
            price = p
            break
    if price is None:
        return None
    return round(input_tokens / 1e6 * price["input"] + output_tokens / 1e6 * price["output"], 6)


def _usage(resp) -> dict:
    u = getattr(resp, "usage_metadata", None)
    get = (lambda k: int(getattr(u, k, 0) or 0)) if u else (lambda k: 0)
    inp = get("prompt_token_count")
    out = get("candidates_token_count")
    thoughts = get("thoughts_token_count")
    return {"input": inp, "output": out, "thinking": thoughts, "total": inp + out + thoughts}


def _build_config(model: str, timeout_s: float):
    kwargs = dict(
        response_mime_type="application/json",
        response_schema=PlantResult,
        http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
    )
    # Для Gemini 3 Google радить не змінювати temperature; для 2.5 робимо відповіді стабільнішими.
    if not model.startswith("gemini-3"):
        kwargs["temperature"] = 0.2
    # Моделі Gemini 3 керуються thinking_level; для 2.5 залишаємо налаштування за замовчуванням.
    if model.startswith("gemini-3") and config.GEMINI_THINKING_LEVEL:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=config.GEMINI_THINKING_LEVEL.upper())
    return types.GenerateContentConfig(**kwargs)


def _classify(exc: Exception) -> str:
    """Повертає: quota | overloaded | not_found | bad_request | auth | transient."""
    code = getattr(exc, "code", None)
    text = str(exc).lower()
    if code in (503, 504) or "unavailable" in text or "high demand" in text or "deadline" in text:
        return "overloaded"  # модель перевантажена — одразу переходимо на наступну
    if code == 429 or "resource_exhausted" in text or "quota" in text:
        return "quota"
    if code == 404 or "not_found" in text or "is not found" in text:
        return "not_found"
    if code in (401, 403) or "api key not valid" in text or "permission_denied" in text:
        return "auth"
    if code == 400 and "thinking" in text:
        return "thinking_unsupported"
    if code == 400:
        return "bad_request"
    return "transient"  # 500/503/504, таймаут, обрив з'єднання


def _call_model(model: str, image_bytes: bytes, mime: str, timeout_s: float, thinking: bool = True):
    client = _get_client()
    cfg = _build_config(model, timeout_s)
    if not thinking:
        cfg.thinking_config = None
    resp = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime), PROMPT],
        config=cfg,
    )
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, PlantResult):
        result = parsed
    else:
        text = (getattr(resp, "text", None) or "").strip()
        if not text:
            raise GeminiError("Gemini повернув порожню відповідь (можливо, спрацював фільтр безпеки).", 502, "empty")
        result = PlantResult.model_validate_json(text)
    return result, _usage(resp)


def identify(image_bytes: bytes, mime: str, mode: str = "flash") -> dict:
    """Визначити рослину. mode: 'flash' (швидко) або 'pro' (точніше)."""
    cache_key = f"{mode}:{hashlib.sha256(image_bytes).hexdigest()}"
    cached = _cache_get(cache_key)
    if cached:
        cached["cached"] = True
        cached["latency_ms"] = 0
        return cached

    if config.GEMINI_MOCK:
        data = _mock_response(mode)
        _cache_put(cache_key, data)
        return data

    if mode == "pro":
        chain = [config.GEMINI_PRO_MODEL, config.GEMINI_MODEL, *config.GEMINI_FALLBACK_MODELS]
    else:
        chain = [config.GEMINI_MODEL, *config.GEMINI_FALLBACK_MODELS]
    chain = list(dict.fromkeys(m for m in chain if m))  # без дублікатів, порядок збережено

    started = time.monotonic()
    attempts: list[_Attempt] = []
    last_kind = "transient"
    last_detail = ""

    for model in chain:
        thinking = True
        tries_left = 2  # одна повторна спроба на модель при тимчасовому збої
        while tries_left > 0:
            remaining = config.GEMINI_TOTAL_BUDGET_S - (time.monotonic() - started)
            if remaining < 5:
                break
            t0 = time.monotonic()
            try:
                result, usage = _call_model(model, image_bytes, mime, min(config.GEMINI_TIMEOUT_S, remaining), thinking)
            except GeminiError:
                raise
            except Exception as exc:  # noqa: BLE001
                kind = _classify(exc)
                ms = int((time.monotonic() - t0) * 1000)
                attempts.append(_Attempt(model, kind, ms))
                log.warning("Gemini %s -> %s (%s ms): %s", model, kind, ms, str(exc)[:300])
                last_kind = kind
                last_detail = f"{model}: {type(exc).__name__}: {str(exc)[:220]}"
                if kind == "thinking_unsupported" and thinking:
                    thinking = False
                    continue
                if kind == "auth":
                    raise GeminiError(
                        "Ключ Gemini API недійсний або не має доступу. Перевірте GEMINI_API_KEY.", 503, "auth", last_detail
                    )
                if kind in ("quota", "overloaded", "not_found", "bad_request"):
                    break  # одразу пробуємо наступну модель
                tries_left -= 1
                if tries_left > 0:
                    time.sleep(0.8 + random.random() * 0.7)  # невелика пауза перед повтором
                continue

            ms = int((time.monotonic() - t0) * 1000)
            attempts.append(_Attempt(model, "ok", ms))
            cost = estimate_cost_usd(model, usage["input"], usage["output"] + usage["thinking"])
            data = {
                "result": result.model_dump(mode="json"),
                "model": model,
                "requested_mode": mode,
                "fallback_used": model != chain[0],
                "latency_ms": int((time.monotonic() - started) * 1000),
                "model_latency_ms": ms,
                "tokens": usage,
                "cost_usd_paid_tier": cost,
                "attempts": [a.__dict__ for a in attempts],
                "cached": False,
                "mock": False,
            }
            _cache_put(cache_key, data)
            return data

    if last_kind == "quota":
        raise GeminiError(
            "Вичерпано безкоштовний ліміт запитів до Gemini для всіх доступних моделей. "
            "Зачекайте хвилину (ліміт на хвилину) або спробуйте завтра (денний ліміт).",
            429,
            "quota",
            last_detail,
        )
    if last_kind == "overloaded":
        raise GeminiError(
            "Сервери Gemini зараз перевантажені (high demand). Спробуйте ще раз за хвилину.", 503, "overloaded", last_detail
        )
    if last_kind == "not_found":
        raise GeminiError("Модель Gemini недоступна. Перевірте назву моделі в GEMINI_MODEL.", 502, "model", last_detail)
    if last_kind == "bad_request":
        raise GeminiError(
            "Gemini не зміг обробити цей запит. Спробуйте інше фото (JPG або PNG).", 422, "bad_image", last_detail
        )
    raise GeminiError(
        "Gemini не відповів вчасно або тимчасово недоступний. Спробуйте ще раз за кілька секунд.",
        504,
        "timeout",
        last_detail,
    )


# --- Демо-режим ---------------------------------------------------------------
def _mock_response(mode: str) -> dict:
    time.sleep(1.2)
    result = {
        "is_plant": True,
        "common_name_uk": "Монстера делікатесна",
        "latin_name": "Monstera deliciosa",
        "family": "Araceae",
        "confidence": 94,
        "description": "Тропічна ліана з великим розсіченим листям, одна з найпопулярніших кімнатних рослин.",
        "health_status": "problems",
        "problems": [
            {
                "name": "Сухі коричневі краї листя",
                "severity": "low",
                "signs": "На двох нижніх листках видно підсохлі краї.",
                "what_to_do": "Підвищте вологість повітря і не ставте рослину біля батареї.",
            }
        ],
        "care": {
            "watering": "Раз на 7–10 днів, коли верхні 3–4 см ґрунту просохли; взимку рідше.",
            "light": "Яскраве розсіяне світло, без прямого полуденного сонця.",
            "temperature": "18–27 °C, не нижче 12 °C.",
            "repotting": "Навесні раз на 1–2 роки в горщик на 3–5 см ширший.",
            "humidity": "50–70 %, допомагає обприскування або зволожувач.",
        },
        "toxicity": {
            "cats": "toxic",
            "dogs": "toxic",
            "note": "Містить оксалати кальцію: подразнення рота, слинотеча, блювання.",
        },
        "alternatives": [{"common_name_uk": "Монстера Борзіга", "latin_name": "Monstera borsigiana", "confidence": 4}],
        "photo_tip": None,
    }
    model = "mock-" + (config.GEMINI_PRO_MODEL if mode == "pro" else config.GEMINI_MODEL)
    usage = {"input": 1320, "output": 410, "thinking": 180, "total": 1910}
    return {
        "result": result,
        "model": model,
        "requested_mode": mode,
        "fallback_used": False,
        "latency_ms": 1200,
        "model_latency_ms": 1200,
        "tokens": usage,
        "cost_usd_paid_tier": estimate_cost_usd(model.replace("mock-", ""), usage["input"], usage["output"] + usage["thinking"]),
        "attempts": [{"model": model, "outcome": "ok", "ms": 1200}],
        "cached": False,
        "mock": True,
    }


if __name__ == "__main__":  # швидка перевірка: python gemini_service.py фото.jpg
    import sys

    from images import prepare_for_gemini

    with open(sys.argv[1], "rb") as f:
        raw = f.read()
    img_bytes, img_mime, _ = prepare_for_gemini(raw)
    print(json.dumps(identify(img_bytes, img_mime, sys.argv[2] if len(sys.argv) > 2 else "flash"), ensure_ascii=False, indent=2))

"""Налаштування застосунку. Усі секрети беруться ТІЛЬКИ зі змінних середовища."""
import os

from dotenv import load_dotenv

# Локально читаємо файл .env (на Render змінні задаються в панелі керування).
load_dotenv()


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_list(name: str, default: str) -> list[str]:
    return [x.strip() for x in _env(name, default).split(",") if x.strip()]


# --- Google Gemini API (AIaaS) -------------------------------------------
GEMINI_API_KEY = _env("GEMINI_API_KEY")

# Основна «швидка» модель і запасні моделі (у кожної моделі окрема квота,
# тому при вичерпанні ліміту сервіс автоматично переходить на наступну).
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACK_MODELS = _env_list(
    "GEMINI_FALLBACK_MODELS", "gemini-3.6-flash,gemini-3.5-flash-lite,gemini-2.5-flash"
)
# «Точна» модель для порівняння (Pro). gemini-2.5-pro має безкоштовний рівень.
GEMINI_PRO_MODEL = _env("GEMINI_PRO_MODEL", "gemini-2.5-pro")

# Таймаут одного запиту до Gemini (секунди) і загальний бюджет часу на всі спроби.
GEMINI_TIMEOUT_S = float(_env("GEMINI_TIMEOUT_S", "30"))
GEMINI_TOTAL_BUDGET_S = float(_env("GEMINI_TOTAL_BUDGET_S", "55"))
# Рівень «роздумів» для моделей Gemini 3 (minimal / low / medium / high).
GEMINI_THINKING_LEVEL = _env("GEMINI_THINKING_LEVEL", "low")

# Демо-режим без ключа: повертає заздалегідь підготовану відповідь.
# Лише для перевірки інтерфейсу. На захисті має бути ВИМКНЕНО.
GEMINI_MOCK = _env("GEMINI_MOCK", "0") in ("1", "true", "yes")

# --- Supabase (DBaaS + об'єктне сховище) ------------------------------------
SUPABASE_URL = _env("SUPABASE_URL")
# Серверний ключ (secret / service_role). Ніколи не передається у браузер.
SUPABASE_KEY = _env("SUPABASE_SECRET_KEY") or _env("SUPABASE_SERVICE_ROLE_KEY") or _env("SUPABASE_KEY")
SUPABASE_TABLE = _env("SUPABASE_TABLE", "plants")
SUPABASE_BUCKET = _env("SUPABASE_BUCKET", "plant-thumbs")

# --- Обмеження на файли ------------------------------------------------------
MAX_UPLOAD_MB = float(_env("MAX_UPLOAD_MB", "10"))
MAX_IMAGE_SIDE = int(_env("MAX_IMAGE_SIDE", "1536"))   # що надсилаємо в Gemini
THUMB_SIDE = int(_env("THUMB_SIDE", "480"))             # мініатюра для «Моїх рослин»
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF", "HEIC", "GIF", "BMP", "MPO"}

# --- Ціни платного рівня, USD за 1 млн токенів --------------------------------
# Джерело: сторінка Pricing у документації Google AI Studio (перевірено 14.11.2026).
# Для gemini-3.8-flash / 3.6-flash діє акційна ціна до 31.12.2026,
# з 01.01.2027 — $1.50 (вхід) і $7.50 (вихід).
PRICING_USD_PER_1M = {
    "gemini-3.8-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.6-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
}

# Курс для приблизного перерахунку в гривні на сторінці (можна змінити).
UAH_PER_USD = float(_env("UAH_PER_USD", "41.5"))

SECRET_KEY = _env("FLASK_SECRET_KEY", "dev-only-change-me")

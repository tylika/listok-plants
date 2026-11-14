"""Перевірка і підготовка зображень.

Перевіряємо не розширення файлу, а сам вміст: Pillow має реально відкрити
його як зображення. Потім зменшуємо фото (менше токенів = швидше і дешевше)
і робимо мініатюру для «Моїх рослин».
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

import config

try:  # фото з iPhone (HEIC). Якщо бібліотеки немає — просто не підтримуємо HEIC.
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_SUPPORTED = True
except Exception:  # pragma: no cover
    HEIF_SUPPORTED = False

Image.MAX_IMAGE_PIXELS = 60_000_000  # захист від «бомб» із гігантською роздільністю


class ImageError(Exception):
    def __init__(self, message: str, code: int = 415, kind: str = "bad_file"):
        super().__init__(message)
        self.message = message
        self.code = code
        self.kind = kind


def _open(raw: bytes) -> Image.Image:
    if not raw:
        raise ImageError("Файл порожній. Виберіть фото рослини.", 400, "empty_file")
    if len(raw) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise ImageError(f"Файл завеликий. Максимум — {config.MAX_UPLOAD_MB:g} МБ.", 413, "too_large")
    try:
        img = Image.open(io.BytesIO(raw))
        fmt = (img.format or "").upper()
        img.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ImageError("Це не зображення або файл пошкоджений. Підтримуються JPG, PNG, WEBP, HEIC.")
    if fmt not in config.ALLOWED_FORMATS:
        raise ImageError(f"Формат {fmt or 'невідомий'} не підтримується. Використайте JPG, PNG або WEBP.")
    if min(img.size) < 64:
        raise ImageError("Зображення занадто маленьке. Потрібно щонайменше 64×64 пікселі.", 422, "too_small")
    try:
        img.seek(0)  # для GIF/анімацій беремо перший кадр
    except Exception:
        pass
    img = ImageOps.exif_transpose(img)  # правильна орієнтація фото з телефона
    if img.mode not in ("RGB", "L"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    return img.convert("RGB")


def _to_jpeg(img: Image.Image, max_side: int, quality: int) -> bytes:
    img = img.copy()
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def prepare_for_gemini(raw: bytes) -> tuple[bytes, str, bytes]:
    """Повертає (jpeg для Gemini, mime, jpeg-мініатюра)."""
    img = _open(raw)
    gemini_jpeg = _to_jpeg(img, config.MAX_IMAGE_SIDE, 86)
    thumb = _to_jpeg(img, config.THUMB_SIDE, 80)
    return gemini_jpeg, "image/jpeg", thumb


def validate_thumbnail(raw: bytes) -> bytes:
    """Мініатюра, яку браузер надсилає при збереженні. Перестраховуємось і перекодовуємо."""
    if len(raw) > 2 * 1024 * 1024:
        raise ImageError("Мініатюра завелика.", 413, "too_large")
    img = _open(raw)
    return _to_jpeg(img, config.THUMB_SIDE, 80)

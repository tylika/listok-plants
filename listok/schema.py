"""JSON-схема відповіді Gemini (structured output).

Gemini отримує цю схему разом із запитом і зобов'язаний повернути JSON
саме такої структури — тому серверу не треба «розбирати» вільний текст.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    healthy = "healthy"          # здорова
    problems = "problems"        # є ознаки проблем
    unknown = "unknown"          # не вдалося оцінити


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ToxicityLevel(str, Enum):
    non_toxic = "non_toxic"
    mild = "mild"
    toxic = "toxic"
    unknown = "unknown"


class Problem(BaseModel):
    name: str = Field(description="Коротка назва проблеми українською, напр. «Павутинний кліщ», «Перелив»")
    severity: Severity = Field(description="Наскільки серйозно")
    signs: str = Field(description="Які ознаки видно на фото, 1 речення")
    what_to_do: str = Field(description="Що зробити, 1–2 речення")


class Care(BaseModel):
    watering: str = Field(description="Полив: як часто і скільки, 1–2 речення")
    light: str = Field(description="Освітлення, 1 речення")
    temperature: str = Field(description="Температура у °C, 1 речення")
    repotting: str = Field(description="Пересадка: коли і як часто, 1 речення")
    humidity: str = Field(description="Вологість повітря, 1 речення")


class Toxicity(BaseModel):
    cats: ToxicityLevel = Field(description="Токсичність для котів")
    dogs: ToxicityLevel = Field(description="Токсичність для собак")
    note: str = Field(description="Пояснення: яка частина рослини небезпечна і які симптоми, 1 речення")


class Alternative(BaseModel):
    common_name_uk: str
    latin_name: str
    confidence: int = Field(ge=0, le=100)


class PlantResult(BaseModel):
    is_plant: bool = Field(description="Чи є на фото рослина")
    common_name_uk: str = Field(description="Поширена українська назва; порожній рядок, якщо рослини немає")
    latin_name: str = Field(description="Латинська назва (рід і вид), напр. «Monstera deliciosa»")
    family: str = Field(description="Родина латиною, напр. «Araceae»")
    confidence: int = Field(ge=0, le=100, description="Впевненість у визначенні виду, 0–100")
    description: str = Field(description="1–2 речення про рослину простою мовою")
    health_status: HealthStatus
    problems: list[Problem] = Field(description="Видимі проблеми на листі/стеблі; порожній список, якщо їх немає")
    care: Care
    toxicity: Toxicity
    alternatives: list[Alternative] = Field(description="До 2 інших схожих видів, якщо є сумнів; інакше порожній список")
    photo_tip: Optional[str] = Field(
        default=None,
        description="Якщо фото нечітке або рослину погано видно — порада, як перефотографувати; інакше null",
    )


PROMPT = """Ти — досвідчений ботанік і фітопатолог. Проаналізуй фото.

Завдання:
1. Визнач рослину: українська назва, латинська назва, родина, впевненість 0–100.
2. Оціни стан: шукай плями, пожовтіння, сухі краї, шкідників, гниль, ознаки переливу чи нестачі світла.
   Указуй лише те, що реально видно на фото. Не вигадуй проблем.
3. Дай практичні поради з догляду для кімнатних умов в Україні.
4. Вкажи токсичність для котів і собак (за даними ASPCA, якщо знаєш).
5. Якщо не впевнений у виді — додай до 2 альтернатив.

Правила:
- Усі тексти — українською, коротко і конкретно.
- Якщо на фото немає рослини: is_plant=false, порожні назви, confidence=0, health_status=unknown,
  токсичність unknown, і в photo_tip поясни, що сфотографувати.
- Впевненість має бути чесною: розмите фото або лише частина листка — нижча впевненість.
"""

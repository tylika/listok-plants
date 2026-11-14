# Листок: визначення рослин за фото на основі Google Gemini API

Прототип вебсервісу для лабораторної роботи №2 з дисципліни «Хмарні обчислення»
(КНУ імені Тараса Шевченка, факультет комп'ютерних наук та кібернетики, кафедра теоретичної кібернетики).

Автор: Буряк Юліана, група ТК-42.

Користувач фотографує або завантажує фото рослини. Сервер надсилає його в **Google Gemini API**
і отримує структурований JSON: українську й латинську назву, впевненість, ознаки хвороб,
поради з догляду (полив, світло, температура, пересадка, вологість) і токсичність для котів і собак.
Результат показується карткою і може бути збережений у «Мої рослини» (**Supabase**).

## Хмарні моделі в проєкті

| Модель | Сервіс | Що робить |
|---|---|---|
| **AIaaS** | Google Gemini API | Розпізнає рослину і стан листя на фото, повертає JSON за схемою |
| **PaaS** | Render (Free) | Запускає Flask-сервер із GitHub, дає публічне HTTPS-посилання |
| **DBaaS** | Supabase PostgreSQL | Таблиця `plants` для «Моїх рослин» |
| **Об'єктне сховище** | Supabase Storage | Мініатюри фото (bucket `plant-thumbs`) |
| **SaaS** | GitHub, Google AI Studio | Зберігання коду, керування ключами і квотами |
| IaaS | не використовується напряму | Віртуальні машини приховані всередині Render і Supabase |

## Архітектура

```
Телефон / ноутбук (браузер)
   │  фото, стиснуте до 1600 px
   ▼
Render (PaaS): Flask + gunicorn
   │  перевірка файлу (Pillow), стискання до 1536 px, JSON-схема
   ├──────────────► Google Gemini API (AIaaS): gemini-3.8-flash / gemini-2.5-pro
   │                  ◄── JSON: назва, проблеми, догляд, токсичність, токени
   └──────────────► Supabase (DBaaS): PostgreSQL + Storage
```

Локально (на ноутбуці) — лише браузер. Якщо запустити сервер на ноутбуці (`run_local.bat`),
то Flask працює локально, а Gemini і Supabase так само залишаються в хмарі.

## Структура

```
app.py              маршрути Flask і обробка помилок
gemini_service.py   виклик Gemini: таймаути, повтори, запасні моделі, кеш, вартість
schema.py           JSON-схема відповіді (Pydantic) і промпт
images.py           перевірка та стискання зображень (Pillow, HEIC)
storage.py          Supabase (хмара) або SQLite (запасний локальний варіант)
config.py           налаштування зі змінних середовища, ціни моделей
templates/, static/ інтерфейс (HTML, CSS, JS), шрифти Alegreya та Onest (OFL)
supabase/schema.sql SQL для створення таблиці й bucket
render.yaml         конфігурація деплою на Render
scripts/benchmark.py заміри Flash і Pro: точність, час, ціна
run_local.bat       запуск на Windows одним подвійним кліком
```

## Запуск локально (Windows)

1. Встановіть **Python 3.13** з [python.org](https://www.python.org/downloads/) і поставте галочку **Add python.exe to PATH**.
2. Розпакуйте проєкт і двічі клацніть `run_local.bat`.
   Перший запуск створить `.venv`, встановить бібліотеки і відкриє `.env` у Блокноті.
3. Вставте у `.env` значення `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, збережіть файл.
4. Знову запустіть `run_local.bat`. Браузер відкриє `http://127.0.0.1:5000`.

Вручну (будь-яка ОС):

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows;  macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
python app.py
```

Без Supabase сервіс теж працює: «Мої рослини» зберігаються в `data/plants.db` (SQLite).
Для перевірки інтерфейсу без ключа Gemini можна поставити `GEMINI_MOCK=1`.

## Налаштування Supabase

1. Створіть проєкт на [supabase.com](https://supabase.com).
2. **SQL Editor → New query**, вставте вміст `supabase/schema.sql`, натисніть **Run**.
   Створяться таблиця `plants`, представлення `plants_stats` і публічний bucket `plant-thumbs`.
3. Скопіюйте Project URL і **secret key** у змінні `SUPABASE_URL` і `SUPABASE_SECRET_KEY`.
   Секретний ключ використовується тільки на сервері, у браузер він не потрапляє.

## Деплой на Render

1. Завантажте проєкт на GitHub (без `.env`).
2. Render → **New → Web Service** → підключіть репозиторій.
3. Build Command: `pip install -r requirements.txt`
   Start Command: `gunicorn app:app --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT`
   Instance Type: **Free**.
4. **Environment**: додайте `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`.
5. Після деплою відкрийте `https://<назва>.onrender.com/healthz`: має бути `"ok": true`.

Альтернатива: **New → Blueprint** використовує готовий `render.yaml`.
Версія Python задається файлом `.python-version` (3.13).

## Надійність

* Перевірка файлу за вмістом (Pillow), обмеження 10 МБ, мінімум 64×64 px, захист від «бомб» роздільності.
* Таймаут на запит до Gemini (30 с) і загальний бюджет 55 с.
* Повторна спроба при 5xx і таймауті; при 429 (ліміт) або 404 автоматичний перехід на запасну модель.
* Кеш за SHA-256 фото: повторне фото не витрачає квоту.
* Усі помилки повертаються як JSON з українським повідомленням; фронтенд показує окремі тексти для
  відсутності інтернету, задовгого очікування, неправильного файлу і перевищеного ліміту API.

## Заміри (Flash і Pro)

Покладіть 4–8 фото в `demo_photos/` з назвами за латинською назвою, напр. `monstera-deliciosa.jpg`, і запустіть:

```bash
.venv\Scripts\python.exe scripts\benchmark.py demo_photos
```

Результат: `benchmark_results/summary.md` (таблиця для презентації) і `results.csv`.

## Ціни (платний рівень, USD за 1 млн токенів, станом на 14.11.2026)

| Модель | Вхід | Вихід |
|---|---|---|
| gemini-3.8-flash | 0.75 | 3.75 |
| gemini-3.5-flash-lite | 0.30 | 2.50 |
| gemini-2.5-flash | 0.30 | 2.50 |
| gemini-2.5-pro | 1.25 | 10.00 |
| gemini-3.1-pro-preview | 2.00 | 12.00 |

Для gemini-3.8-flash ця ціна діє до 31.12.2026, з 01.01.2027: $1.50 / $7.50.
Прототип працює на безкоштовному рівні: $0. Ліміти безкоштовного рівня видно в Google AI Studio.

## Обмеження прототипу

* Визначення — підказка, а не експертний висновок.
* Немає облікових записів: «Мої рослини» спільні для всіх відвідувачів.
* Free-рівень Gemini має невеликий денний ліміт; запити можуть використовуватися для покращення продуктів Google.
* Render Free засинає після 15 хв без запитів (перше відкриття до ~1 хв); Supabase Free ставить проєкт на паузу після 7 днів без активності.

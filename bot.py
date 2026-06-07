"""
Мират — зеркало осознанности
Ербол Шудабай, 2026
Стек: Telegram + OpenAI Whisper + GPT-4o
Версия 9 — финальная стабильная
"""

import os
import asyncio
import sqlite3
import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, Voice
from aiogram.filters import CommandStart, Command
from aiogram.fsm.storage.memory import MemoryStorage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ── База данных ───────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("awareness.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            transcript TEXT,
            level TEXT,
            branch TEXT,
            left_plus REAL,
            left_minus REAL,
            right_plus REAL,
            right_minus REAL,
            pp_percent REAL,
            pm_percent REAL,
            mp_percent REAL,
            mm_percent REAL,
            content TEXT,
            consequence TEXT,
            break_circle TEXT,
            summary TEXT,
            raw_analysis TEXT
        )
    """)
    # Автомиграция — добавляем колонки если их нет
    existing = [row[1] for row in conn.execute("PRAGMA table_info(entries)")]
    for col in ["content", "consequence", "break_circle"]:
        if col not in existing:
            conn.execute(f"ALTER TABLE entries ADD COLUMN {col} TEXT")
    conn.commit()
    conn.close()

def save_entry(user_id, transcript, analysis):
    conn = sqlite3.connect("awareness.db")
    b = analysis.get("branches", {})
    lh = analysis.get("left_hemisphere", {})
    rh = analysis.get("right_hemisphere", {})
    conn.execute("""
        INSERT INTO entries
        (user_id, timestamp, transcript, level, branch,
         left_plus, left_minus, right_plus, right_minus,
         pp_percent, pm_percent, mp_percent, mm_percent,
         content, consequence, break_circle, summary, raw_analysis)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id, datetime.now().isoformat(), transcript,
        analysis.get("level"), analysis.get("dominant_branch"),
        lh.get("plus", 0), lh.get("minus", 0),
        rh.get("plus", 0), rh.get("minus", 0),
        b.get("++", 0), b.get("+-", 0), b.get("-+", 0), b.get("--", 0),
        analysis.get("content"), analysis.get("consequence"),
        analysis.get("break_circle"), analysis.get("summary"),
        json.dumps(analysis, ensure_ascii=False)
    ))
    conn.commit()
    conn.close()

def get_stats(user_id, days=7):
    conn = sqlite3.connect("awareness.db")
    rows = conn.execute("""
        SELECT date(timestamp), level, branch, pp_percent, pm_percent, mp_percent, mm_percent
        FROM entries
        WHERE user_id = ? AND timestamp >= date('now', ?)
        ORDER BY timestamp DESC
    """, (user_id, f"-{days} days")).fetchall()
    conn.close()
    return rows

# ── ПРОМПТ ────────────────────────────────────────────────────────────────────
ANALYSIS_PROMPT = """Ты — Мират, нейтральное зеркало осознанности. Без советов. Без оценок. Без осуждения.

ТВОЯ ЗАДАЧА — три шага:
1. Увидеть — какой внутренний образ реальности человек держит прямо сейчас
2. Осознать — что этот образ притягивает в реальность
3. Выбрать — одно действие или вопрос который прерывает замкнутый круг

━━━━━━━━━━━━━━━━━━━━━
ЗАКОН 1 — СОДЕРЖАНИЕ
В реальность отражается СОДЕРЖАНИЕ, не форма.
Содержание = внутренний образ реальности = ответ на вопрос "И ЧТО С ТОГО?"

Форма → Содержание:
"не хочу болеть" → образ болезни
"так нужны деньги" → образ недостатка
"если бы только" → образ отсутствия
"он плохой, они все такие" → образ враждебного мира
"это несправедливо" → образ борьбы с реальностью
"я благодарен" → образ достатка и принятия
"я выбираю / моя ответственность" → образ силы и свободы
"воля Всевышнего / иншаллах" → образ принятия и доверия

Правила:
- Приставка "не" — форма, не меняет содержание
- "Если бы / когда наконец / должно быть иначе" — форма условности
- "Почему / за что" — форма застревания
- Ирония — по контексту, не по словам
- Последние фразы весят больше

ЗАКОН 2 — ПРИТЯЖЕНИЕ
Внутренний образ притягивает события того же знака.
Плюс притягивает плюс. Минус притягивает минус.

━━━━━━━━━━━━━━━━━━━━━
ТРИ УРОВНЯ (определяй ПЕРВЫМ):

mirror — нет позиции "я". Человек = объект событий. Сигналы: "так получилось", "они решили", "жизнь такая"
observer — есть позиция "я". Сигналы: "я замечаю", "я осознаю", "я выбираю"
meta — наблюдатель видит сам процесс своего наблюдения. Очень редко. Не путай с умными словами о себе.
Сигналы: человек описывает КАК он осознаёт, "я замечаю что я замечаю", "я содержу это" а не "я это есть", осознанная ссылка на источник как на отдельный от себя ("я вижу что это благо" — не просто "это благо").
"я осознал", "я принимаю", "воля Всевышнего" — это observer, не meta.

━━━━━━━━━━━━━━━━━━━━━
ЛЕВОЕ ПОЛУШАРИЕ — анализ формы
Вопрос: есть движение к КАК или застрял в ПОЧЕМУ?

Левое+: "как", "попробую", конкретные шаги, намерения, "для того чтобы"
Левое−: "почему", "за что", "если бы только", объяснения прошлого

ПРАВОЕ ПОЛУШАРИЕ — синтез содержания
Вопрос: принимает реальность или борется с ней?
Правое НЕ оценивает хорошо/плохо — только: принимает или борется.

Правое+: называет состояние без борьбы, принимает факт, благодарность, "воля Всевышнего", иншаллах, осознаёт ответственность
Правое−: "несправедливо", "не должно быть", жертвенная позиция, "если бы раньше", осуждение других

Важно: принятие негативной реальности → Правое+
Осуждение других → снижает Правое (образ враждебного мира внутри)

━━━━━━━━━━━━━━━━━━━━━
ВЕТКА (считается из цифр, не интерпретируется):
Левое+ + Правое+ = ++  Интеграция
Левое+ + Правое− = +-  Иллюзия
Левое− + Правое+ = -+  Реакция
Левое− + Правое− = --  Заморозка

━━━━━━━━━━━━━━━━━━━━━
ТРИ ПОЛЯ ВЫВОДА (без дублей между полями):

content — внутренний образ реальности. Только образ, без следствий.
  Примеры: "Я принимаю ответственность за свою судьбу" / "Мир несправедлив ко мне"

consequence — что этот образ притягивает. Только следствие, без советов.
  Примеры: "Это притягивает ситуации где человек берёт контроль" / "Это притягивает повторение обид"

break_circle — строго по ветке, из конкретного образа:

  ++ → подтвердить и пригласить к мета-осознанию:
  "Твой образ интегрирован. [из content] — это притягивает [из consequence]. Замечаешь ли ты кто это осознаёт?"

  +- → картина только в голове, предложить новый образ:
  "Ты держишь образ [из content]. Эта картина — в твоей голове. Как бы ты себя чувствовал если бы эта картина была другой?"

  -+ → освободить от поиска пути, ввести в состояние благодарности:
  "Твоё содержание правильное — [из content]. Это уже притягивает [из consequence]. Можешь ли ты быть благодарным за это — не зная как именно это придёт?"

  -- → пауза, зеркало, пространство (БЕЗ вопроса, БЕЗ давления):
  "Сейчас твоя голова держит образ [из content]. Это картина — не реальность. Отправь это сообщение ещё раз — когда что-то изменится."

  mirror → вернуть субъекта:
  "Что ты сам — не обстоятельства, не другие — выбираешь думать об этом?"

━━━━━━━━━━━━━━━━━━━━━
ФОРМАТ — ТОЛЬКО JSON, никакого текста вокруг:
{
  "level": "mirror" или "observer" или "meta",
  "left_hemisphere": {"plus": 0-100, "minus": 0-100, "key_signal": "фраза из текста"},
  "right_hemisphere": {"plus": 0-100, "minus": 0-100, "key_signal": "фраза из текста"},
  "content": "внутренний образ — кратко",
  "consequence": "Это притягивает...",
  "break_circle": "строго по ветке как описано выше",
  "summary": "1 предложение: какой образ держит человек"
}"""

# ── Транскрипция ──────────────────────────────────────────────────────────────
async def transcribe_voice(file_path: str) -> str:
    with open(file_path, "rb") as audio_file:
        transcript = await openai_client.audio.transcriptions.create(
            model="whisper-1", file=audio_file, language="ru"
        )
    return transcript.text

# ── Анализ через GPT-4o ───────────────────────────────────────────────────────
async def analyze_text(text: str) -> dict:
    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        max_tokens=1000,
        temperature=0.2,
        messages=[
            {"role": "system", "content": ANALYSIS_PROMPT},
            {"role": "user", "content": f"{text}\n\nОТВЕЧАЙ ТОЛЬКО JSON."}
        ]
    )
    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    analysis = json.loads(raw)

    # Ветка считается кодом
    lh = analysis.get("left_hemisphere", {})
    rh = analysis.get("right_hemisphere", {})
    left_sign = "+" if lh.get("plus", 0) >= lh.get("minus", 0) else "-"
    right_sign = "+" if rh.get("plus", 0) >= rh.get("minus", 0) else "-"
    analysis["dominant_branch"] = left_sign + right_sign

    # Формула площадей (Ербол)
    lp = lh.get("plus", 0)
    lm = lh.get("minus", 0)
    rp = rh.get("plus", 0)
    rm = rh.get("minus", 0)
    total = (lp + lm) * (rp + rm) if (lp + lm) * (rp + rm) > 0 else 10000
    analysis["branches"] = {
        "++": round(lp * rp / total * 100),
        "+-": round(lp * rm / total * 100),
        "-+": round(lm * rp / total * 100),
        "--": round(lm * rm / total * 100),
    }
    return analysis

# ── Форматирование ────────────────────────────────────────────────────────────
LEVEL_LABELS = {
    "mirror":   "🪞 Зеркало-автомат",
    "observer": "👁 Наблюдатель",
    "meta":     "✨ Мета-осознание"
}
BRANCH_LABELS = {
    "++": "++ Интеграция",
    "+-": "+- Иллюзия",
    "-+": "-+ Реакция",
    "--": "-- Заморозка"
}
BRANCH_BARS = {"++": "🟢", "+-": "🟡", "-+": "🟠", "--": "🔴"}

def bar(pct):
    p = int(pct)
    return "█" * (p // 10) + "░" * (10 - p // 10) + f" {p}%"

def format_response(analysis: dict) -> str:
    level = analysis.get("level", "mirror")
    branch = analysis.get("dominant_branch")
    content_field = analysis.get("content", "")
    consequence = analysis.get("consequence", "")
    break_circle = analysis.get("break_circle", "")
    summary = analysis.get("summary", "")
    branches = analysis.get("branches", {})
    lh = analysis.get("left_hemisphere", {})
    rh = analysis.get("right_hemisphere", {})

    lines = [f"*Уровень:* {LEVEL_LABELS.get(level, level)}"]

    if level == "mirror":
        lines += ["", f"_{summary}_", ""]
        lines.append(f"🪞 *Содержание:* _{content_field}_")
        if consequence:
            lines.append(f"⚡ *Следствие:* _{consequence}_")
        if break_circle:
            lines += ["", f"❓ {break_circle}"]
    else:
        if branch:
            lines.append(f"*Ветка:* {BRANCH_LABELS.get(branch, branch)}")
        lines.append("")

        lines.append("*Левое* (путь):")
        lines.append(f"+ {bar(lh.get('plus', 0))}")
        lines.append(f"− {bar(lh.get('minus', 0))}")
        if lh.get("key_signal"):
            lines.append(f'   _"{lh["key_signal"]}"_')

        lines.append("")
        lines.append("*Правое* (состояние):")
        lines.append(f"+ {bar(rh.get('plus', 0))}")
        lines.append(f"− {bar(rh.get('minus', 0))}")
        if rh.get("key_signal"):
            lines.append(f'   _"{rh["key_signal"]}"_')

        lines.append("")
        lines.append("*Ветки:*")
        for b, emoji in BRANCH_BARS.items():
            pct = int(branches.get(b, 0))
            lines.append(f"{emoji} {b}  {bar(pct)}")

        lines += ["", "🪞 *Содержание:*", f"_{content_field}_"]
        if consequence:
            lines += ["", f"⚡ *Следствие:* _{consequence}_"]
        if break_circle:
            lines += ["", f"❓ {break_circle}"]

    return "\n".join(lines)

def format_stats(stats: list) -> str:
    if not stats:
        return "Пока нет записей. Отправь сообщение."
    lines = ["*📊 Статистика за 7 дней*", ""]
    totals = {"++": [], "+-": [], "-+": [], "--": []}
    levels = {"mirror": 0, "observer": 0, "meta": 0}
    for row in stats:
        _, level, branch, pp, pm, mp, mm = row
        levels[level] = levels.get(level, 0) + 1
        totals["++"].append(pp or 0)
        totals["+-"].append(pm or 0)
        totals["-+"].append(mp or 0)
        totals["--"].append(mm or 0)
    total = len(stats)
    lines.append(f"Всего записей: {total}")
    lines += ["", "*Уровни:*"]
    for lvl, count in levels.items():
        if count:
            lines.append(f"{LEVEL_LABELS.get(lvl, lvl)}: {int(count/total*100)}%")
    lines += ["", "*Среднее по веткам:*"]
    for b, emoji in BRANCH_BARS.items():
        avg = int(sum(totals[b]) / len(totals[b])) if totals[b] else 0
        lines.append(f"{emoji} {b}  {bar(avg)}")
    return "\n".join(lines)

# ── Хэндлеры ─────────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👁 *Мират — зеркало осознанности*\n\n"
        "Напиши или отправь голосовое — скажи как есть, что сейчас происходит.\n\n"
        "Я покажу:\n"
        "• Какой внутренний образ ты транслируешь прямо сейчас\n"
        "• Что этот образ притягивает в твою жизнь\n"
        "• Одно действие которое разрывает замкнутый круг\n\n"
        "/help — как пользоваться\n"
        "/stats — динамика за 7 дней\n\n"
        "⚠️ _Твои сообщения анонимно сохраняются для улучшения системы._",
        parse_mode="Markdown"
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 *Как пользоваться Миратом*\n\n"
        "*Основной метод:*\n"
        "Говори или пиши как есть — без фильтров, без подготовки.\n"
        "Бот читает не слова, а содержание.\n\n"
        "*Метод повторения:*\n"
        "Отправь одно и то же сообщение несколько раз подряд.\n"
        "Каждый раз ты говоришь из чуть другого места.\n"
        "Следи как меняется содержание — это движение.\n"
        "Цель: прийти к состоянию ++ через осознание.\n\n"
        "*Что ты получаешь:*\n"
        "🪞 Содержание — внутренний образ который ты держишь\n"
        "⚡ Следствие — что этот образ притягивает\n"
        "❓ Действие — разрывает замкнутый круг\n\n"
        "*Четыре состояния:*\n"
        "++ Видишь путь И принимаешь реальность\n"
        "+- Видишь путь НО борешься с реальностью\n"
        "-+ Принимаешь реальность НО не видишь пути\n"
        "-- Ни пути ни принятия\n\n"
        "⚠️ _Сообщения анонимно сохраняются для улучшения системы._",
        parse_mode="Markdown"
    )

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    stats = get_stats(message.from_user.id)
    await message.answer(format_stats(stats), parse_mode="Markdown")

@dp.message(F.voice)
async def handle_voice(message: Message):
    processing_msg = await message.answer("🔄 Слушаю...")
    tmp_path = None
    try:
        file = await bot.get_file(message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await bot.download_file(file.file_path, tmp_path)
        await processing_msg.edit_text("📝 Транскрибирую...")
        transcript = await transcribe_voice(tmp_path)
        if not transcript.strip():
            await processing_msg.edit_text("Не смог распознать речь. Попробуй ещё раз.")
            return
        await processing_msg.edit_text("🧠 Анализирую...")
        analysis = await analyze_text(transcript)
        save_entry(message.from_user.id, transcript, analysis)
        await processing_msg.edit_text(format_response(analysis), parse_mode="Markdown")
    except json.JSONDecodeError:
        await processing_msg.edit_text("Ошибка анализа. Попробуй ещё раз.")
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await processing_msg.edit_text(f"Ошибка: {str(e)[:150]}")
    finally:
        if tmp_path and Path(tmp_path).exists():
            Path(tmp_path).unlink()

@dp.message(F.text)
async def handle_text(message: Message):
    if len(message.text) < 10:
        return
    processing_msg = await message.answer("🧠 Анализирую...")
    try:
        analysis = await analyze_text(message.text)
        save_entry(message.from_user.id, message.text, analysis)
        await processing_msg.edit_text(format_response(analysis), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Text error: {e}")
        await processing_msg.edit_text(f"Ошибка: {str(e)[:150]}")

# ── Запуск ────────────────────────────────────────────────────────────────────
async def main():
    init_db()
    logger.info("Bot started v9 — Мират финальный")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

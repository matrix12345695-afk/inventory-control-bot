"""Group video note and branch schedule monitor."""
import asyncio
import json
import logging
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

TZ = ZoneInfo("Asia/Tashkent")
SCHEDULE = json.loads((Path(__file__).parent / "schedule.json").read_text(encoding="utf-8"))
DB = os.getenv("DATABASE_PATH", "round_video_bot/events.sqlite3")
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
TOLERANCE = int(os.getenv("DATE_TOLERANCE_DAYS", "2"))
dp = Dispatcher()


def normalize(value):
    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    value = re.sub(r"\b(safia|burger|магазин|бар)\b", " ", value)
    return re.sub(r"[^\w]+", "", value)


def parse_label(text, event_date):
    match = re.search(r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?(?!\d)", text)
    if not match:
        return text.strip(), event_date
    day, month = map(int, match.group(1, 2))
    year = int(match.group(3)) if match.group(3) else event_date.year
    if year < 100:
        year += 2000
    date = datetime(year, month, day).date()
    return (text[:match.start()] + " " + text[match.end():]).strip(), date


def candidates(label, date):
    key = normalize(label)
    if not key:
        return []
    found = []
    for row in SCHEDULE:
        name = normalize(row["branch"])
        score = 1 if key in (name, normalize(row["code"])) else (.9 if key in name and len(key) >= 4 else SequenceMatcher(None, key, name).ratio())
        if score >= .84:
            found.append((score, row))
    return sorted(found, key=lambda item: (-item[0], abs((datetime.fromisoformat(item[1]["date"]).date() - date).days)))


def connection():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute("CREATE TABLE IF NOT EXISTS videos (chat_id INTEGER, message_id INTEGER, user_id INTEGER, sent_at TEXT, PRIMARY KEY(chat_id,message_id))")
    db.execute("CREATE TABLE IF NOT EXISTS reports (chat_id INTEGER, message_id INTEGER, video_id INTEGER, user_id INTEGER, branch TEXT, code TEXT, schedule_date TEXT, stated_date TEXT, manager TEXT, accountant TEXT, status TEXT, PRIMARY KEY(chat_id,message_id))")
    db.execute("CREATE TABLE IF NOT EXISTS people (chat_id INTEGER, user_id INTEGER, name TEXT, approved INTEGER DEFAULT 0, PRIMARY KEY(chat_id,user_id))")
    db.execute("CREATE TABLE IF NOT EXISTS checks (chat_id INTEGER, video_id INTEGER, label_id INTEGER, user_id INTEGER, branch TEXT, code TEXT, schedule_date TEXT, stated_date TEXT, accountant TEXT, expected TEXT, status TEXT, PRIMARY KEY(chat_id,video_id))")
    db.execute("CREATE TABLE IF NOT EXISTS deliveries (chat_id INTEGER, kind TEXT, period TEXT, PRIMARY KEY(chat_id,kind,period))")
    return db


@dp.message(Command("iam"))
async def iam(message: Message):
    if message.chat.type == "private" or (GROUP_ID and message.chat.id != GROUP_ID):
        return
    name = (message.text or "").partition(" ")[2].strip()
    known = {normalize(r["accountant"]): r["accountant"] for r in SCHEDULE}
    actual = known.get(normalize(name))
    if not actual:
        await message.reply("ФИО не найдено в графике. Напишите /iam ФАМИЛИЯ ИМЯ ОТЧЕСТВО как в таблице.")
        return
    with connection() as db:
        db.execute("INSERT INTO people VALUES (?,?,?,0) ON CONFLICT(chat_id,user_id) DO UPDATE SET name=excluded.name,approved=0", (message.chat.id, message.from_user.id, actual))
    await message.reply("Заявка записана. Администратор группы должен ответить /approve на ваше исходное сообщение с /iam.")


@dp.message(Command("approve"))
async def approve(message: Message, bot: Bot):
    if message.chat.type == "private" or not message.reply_to_message or (GROUP_ID and message.chat.id != GROUP_ID):
        return
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ("administrator", "creator"):
        return
    target = message.reply_to_message.from_user
    if not target:
        return
    with connection() as db:
        person = db.execute("SELECT name FROM people WHERE chat_id=? AND user_id=?", (message.chat.id, target.id)).fetchone()
        if person:
            db.execute("UPDATE people SET approved=1 WHERE chat_id=? AND user_id=?", (message.chat.id, target.id))
    if person:
        await message.reply(f"✅ Подтверждён бухгалтер {person[0]}.")


@dp.message(F.video_note | F.video)
async def video(message: Message):
    if GROUP_ID and message.chat.id != GROUP_ID:
        return
    if message.chat.type == "private" or not message.from_user:
        return
    with connection() as db:
        db.execute("INSERT OR IGNORE INTO videos VALUES (?,?,?,?)", (message.chat.id, message.message_id, message.from_user.id, message.date.astimezone(TZ).isoformat()))
    if message.caption:
        await process_label(message, message.caption, message.message_id)


async def process_label(message, label, video_id):
    date = message.date.astimezone(TZ).date()
    try:
        branch, stated = parse_label(label, date)
    except ValueError:
        await message.reply("Не понял дату. Напишите: Филиал ДД.ММ (ответом на видео).")
        return
    found = candidates(branch, stated)
    if not found:
        await message.reply(f"⚠️ В графике нет «{branch}» на {stated:%d.%m.%Y} (допуск ±{TOLERANCE} дня). Проверьте название и дату.")
        return
    best, row = found[0]
    if len(found) > 1 and found[1][0] == best and found[1][1]["code"] != row["code"]:
        await message.reply("⚠️ Филиал неоднозначен: " + ", ".join(f'{x[1]["branch"]} ({x[1]["code"]})' for x in found[:4]) + ". Укажите W-код.")
        return
    with connection() as db:
        person = db.execute("SELECT name FROM people WHERE chat_id=? AND user_id=? AND approved=1", (message.chat.id, message.from_user.id)).fetchone()
    accountant = person[0] if person else ""
    days = abs((datetime.fromisoformat(row["date"]).date() - stated).days)
    if not accountant:
        status = "бухгалтер не установлен"
    elif normalize(accountant) != normalize(row["accountant"]):
        status = "чужой филиал"
    elif days > TOLERANCE:
        status = "вне графика"
    elif days:
        status = "сдвиг по дате"
    else:
        status = "совпадает"
    with connection() as db:
        db.execute("INSERT INTO checks VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(chat_id,video_id) DO UPDATE SET label_id=excluded.label_id,branch=excluded.branch,code=excluded.code,schedule_date=excluded.schedule_date,stated_date=excluded.stated_date,accountant=excluded.accountant,expected=excluded.expected,status=excluded.status", (message.chat.id, video_id, message.message_id, message.from_user.id, row["branch"], row["code"], row["date"], stated.isoformat(), accountant, row["accountant"], status))
    await message.reply(f'📍 {row["branch"]} ({row["code"]})\nГрафик: {row["date"]}; сообщено: {stated:%d.%m.%Y}\nПо графику: {row["accountant"]}\nОтправил: {accountant or "не подтверждён"}\nРезультат: {status}.')


@dp.message(F.text & F.reply_to_message)
async def label_reply(message: Message):
    if GROUP_ID and message.chat.id != GROUP_ID:
        return
    if message.chat.type == "private" or not message.from_user:
        return
    target = message.reply_to_message
    with connection() as db:
        video_row = db.execute("SELECT user_id FROM videos WHERE chat_id=? AND message_id=?", (message.chat.id, target.message_id)).fetchone()
    if not video_row:
        return
    if video_row[0] != message.from_user.id:
        await message.reply("Название филиала должен указать автор видео.")
        return
    await process_label(message, message.text, target.message_id)


@dp.message(Command("today"))
async def today(message: Message):
    if GROUP_ID and message.chat.id != GROUP_ID:
        return
    date = datetime.now(TZ).date().isoformat()
    rows = [r for r in SCHEDULE if r["date"] == date]
    if not rows:
        await message.reply("На сегодня филиалов в графике нет.")
        return
    await message.reply("График на сегодня:\n" + "\n".join(f'{r["code"]} {r["branch"]} — {r["manager"]}' for r in rows))


def report(chat_id, start, end):
    planned = [r for r in SCHEDULE if start <= r["date"] <= end]
    with connection() as db:
        rows = db.execute("SELECT code,branch,schedule_date,stated_date,accountant,expected,status FROM checks WHERE chat_id=? AND stated_date BETWEEN ? AND ? ORDER BY stated_date,code", (chat_id, start, end)).fetchall()
    counts = Counter(r[6] for r in rows)
    covered = {(r[0], r[2]) for r in rows if r[6] == "совпадает"}
    missing = [r for r in planned if (r["code"], r["date"]) not in covered]
    lines = [f"📊 Отчёт {start} — {end}", f"По графику: {len(planned)}; видео: {len(rows)}; совпадает: {counts['совпадает']}; без подтверждённого совпадения: {len(missing)}", "Статусы: " + (", ".join(f"{k} — {v}" for k, v in sorted(counts.items())) or "видео нет")]
    for r in rows:
        if r[6] != "совпадает":
            lines.append(f"⚠️ {r[3]} {r[0]} {r[1]}: {r[6]}; снял: {r[4] or 'не установлен'}; по графику: {r[5]}")
    for r in missing:
        lines.append(f'➖ {r["date"]} {r["code"]} {r["branch"]}: нет подтверждённого совпадения ({r["accountant"]})')
    return "\n".join(lines)


async def send_report(bot, chat_id, kind, start, end, automatic=False):
    period = f"{start}:{end}"
    if automatic:
        with connection() as db:
            if db.execute("SELECT 1 FROM deliveries WHERE chat_id=? AND kind=? AND period=?", (chat_id, kind, period)).fetchone():
                return
    body = report(chat_id, start, end)
    for i in range(0, len(body), 3500):
        await bot.send_message(chat_id, body[i:i + 3500])
    if automatic:
        with connection() as db:
            db.execute("INSERT OR IGNORE INTO deliveries VALUES (?,?,?)", (chat_id, kind, period))


@dp.message(Command("week", "month"))
async def manual_report(message: Message, bot: Bot):
    if message.chat.type == "private" or (GROUP_ID and message.chat.id != GROUP_ID):
        return
    today = datetime.now(TZ).date()
    if (message.text or "").split()[0].split("@")[0] == "/week":
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
        kind = "week"
    else:
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
        kind = "month"
    await send_report(bot, message.chat.id, kind, start.isoformat(), end.isoformat())


async def scheduled(bot):
    while True:
        now = datetime.now(TZ)
        if GROUP_ID and now.hour == 9:
            yesterday = now.date() - timedelta(days=1)
            try:
                if now.weekday() == 0:
                    start = yesterday - timedelta(days=6)
                    await send_report(bot, GROUP_ID, "week", start.isoformat(), yesterday.isoformat(), True)
                if now.day == 1:
                    await send_report(bot, GROUP_ID, "month", yesterday.replace(day=1).isoformat(), yesterday.isoformat(), True)
            except Exception:
                logging.exception("Report delivery failed; will retry")
        await asyncio.sleep(60)


async def main():
    logging.basicConfig(level=logging.INFO)
    token = os.environ["BOT_TOKEN"]
    with connection():
        pass
    async with Bot(token) as bot:
        await bot.delete_webhook(drop_pending_updates=False)
        task = asyncio.create_task(scheduled(bot))
        try:
            await dp.start_polling(bot)
        finally:
            task.cancel()


if __name__ == "__main__":
    asyncio.run(main())

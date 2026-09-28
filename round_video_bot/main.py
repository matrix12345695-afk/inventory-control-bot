"""Group video note and branch schedule monitor."""
import asyncio
import json
import logging
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta
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
        if abs((datetime.fromisoformat(row["date"]).date() - date).days) > TOLERANCE:
            continue
        name = normalize(row["branch"])
        score = 1 if key == name else (.9 if key in name and len(key) >= 4 else SequenceMatcher(None, key, name).ratio())
        if score >= .74:
            found.append((score, row))
    return sorted(found, key=lambda item: (-item[0], item[1]["date"]))


def connection():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute("CREATE TABLE IF NOT EXISTS videos (chat_id INTEGER, message_id INTEGER, user_id INTEGER, sent_at TEXT, PRIMARY KEY(chat_id,message_id))")
    db.execute("CREATE TABLE IF NOT EXISTS reports (chat_id INTEGER, message_id INTEGER, video_id INTEGER, user_id INTEGER, branch TEXT, code TEXT, schedule_date TEXT, stated_date TEXT, manager TEXT, accountant TEXT, status TEXT, PRIMARY KEY(chat_id,message_id))")
    return db


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
    status = "по графику" if row["date"] == stated.isoformat() else "отклонение по дате"
    with connection() as db:
        db.execute("INSERT OR IGNORE INTO reports VALUES (?,?,?,?,?,?,?,?,?,?,?)", (message.chat.id, message.message_id, video_id, message.from_user.id, row["branch"], row["code"], row["date"], stated.isoformat(), row["manager"], row["accountant"], status))
        changed = db.execute("SELECT changes()").fetchone()[0]
    if changed:
        await message.reply(f'📍 {row["branch"]} ({row["code"]})\nГрафик: {row["date"][8:10]}.{row["date"][5:7]}\nСообщено: {stated:%d.%m}\nСтатус: {status}.\nУправляющий по графику: {row["manager"]}\n⚠️ Личность отправителя автоматически не подтверждена.')


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


async def main():
    logging.basicConfig(level=logging.INFO)
    token = os.environ["BOT_TOKEN"]
    with connection():
        pass
    async with Bot(token) as bot:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart

import os
import httpx
import asyncio

BOT_TOKEN = os.getenv("BOT_TOKEN")
RENDER_API_KEY = os.getenv("RENDER_API_KEY")
RENDER_SERVICE_ID = os.getenv("RENDER_SERVICE_ID")

ADMIN_IDS = [
    502438855,
    785245733,
    6311609684,
    177536138,
    8103344174
]

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


def menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🟢 Запустить")],
            [KeyboardButton(text="🔴 Остановить")],
            [KeyboardButton(text="📊 Статус")]
        ],
        resize_keyboard=True
    )


@dp.message(CommandStart())
async def start(message: Message):

    if message.from_user.id not in ADMIN_IDS:
        return

    await message.answer(
        "⚙️ Управление Inventory Bot",
        reply_markup=menu()
    )


@dp.message(F.text == "🟢 Запустить")
async def start_service(message: Message):

    if message.from_user.id not in ADMIN_IDS:
        return

    url = f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/resume"

    headers = {
        "Authorization": f"Bearer {RENDER_API_KEY}"
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(url, headers=headers)

    await message.answer(
        f"🚀 Ответ Render:\n{r.status_code}\n{r.text}"
    )


@dp.message(F.text == "🔴 Остановить")
async def stop_service(message: Message):

    if message.from_user.id not in ADMIN_IDS:
        return

    url = f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/suspend"

    headers = {
        "Authorization": f"Bearer {RENDER_API_KEY}"
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(url, headers=headers)

    await message.answer(
        f"🛑 Ответ Render:\n{r.status_code}\n{r.text}"
    )


@dp.message(F.text == "📊 Статус")
async def status_service(message: Message):

    if message.from_user.id not in ADMIN_IDS:
        return

    url = f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}"

    headers = {
        "Authorization": f"Bearer {RENDER_API_KEY}"
    }

    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers)

    await message.answer(
        f"📊 Статус:\n{r.status_code}\n{r.text}"
    )


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

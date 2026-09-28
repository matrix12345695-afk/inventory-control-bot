from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart

import os
import httpx
import asyncio
import logging

BOT_TOKEN = os.getenv("BOT_TOKEN")
RENDER_API_KEY = os.getenv("RENDER_API_KEY")
RENDER_SERVICE_ID = os.getenv("RENDER_SERVICE_ID")
ROUND_VIDEO_SERVICE_ID = os.getenv("ROUND_VIDEO_SERVICE_ID")

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
            [KeyboardButton(text="📊 Статус")],
            [KeyboardButton(text="🟢 Запустить контроль кружков")],
            [KeyboardButton(text="🔴 Остановить контроль кружков")],
            [KeyboardButton(text="📊 Статус контроля кружков")]
        ],
        resize_keyboard=True
    )


confirm_stop = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Да, остановить")],
        [KeyboardButton(text="❌ Отмена")]
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

    await message.answer(
        "🚀 Запускаю Inventory Bot..."
    )

    url = f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/resume"

    headers = {
        "Authorization": f"Bearer {RENDER_API_KEY}"
    }

    async with httpx.AsyncClient(timeout=30) as client:

        r = await client.post(url, headers=headers)

        if r.status_code not in [200, 202]:
            await message.answer(
                f"❌ Ошибка запуска\nHTTP {r.status_code}\n{r.text}"
            )
            return

        await message.answer(
            "⏳ Ожидаю запуск сервиса..."
        )

        for sec in range(5, 65, 5):

            try:

                check = await client.get(
                    "https://inventory-bot-muyu.onrender.com/"
                )

                if check.status_code == 200:

                    await message.answer(
                        f"🟢 Inventory Bot успешно запущен!\n⏱ Время запуска: {sec} сек."
                    )

                    return

            except:
                pass

            await asyncio.sleep(5)

    await message.answer(
        "⚠️ Команда отправлена, но сервис ещё запускается."
    )


@dp.message(F.text == "🔴 Остановить")
async def ask_stop(message: Message):

    if message.from_user.id not in ADMIN_IDS:
        return

    await message.answer(
        "⚠️ Вы уверены, что хотите остановить Inventory Bot?",
        reply_markup=confirm_stop
    )


@dp.message(F.text == "❌ Отмена")
async def cancel_stop(message: Message):

    if message.from_user.id not in ADMIN_IDS:
        return

    await message.answer(
        "👌 Остановка отменена.",
        reply_markup=menu()
    )


@dp.message(F.text == "✅ Да, остановить")
async def stop_service(message: Message):

    if message.from_user.id not in ADMIN_IDS:
        return

    await message.answer(
        "🛑 Останавливаю Inventory Bot..."
    )

    url = f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/suspend"

    headers = {
        "Authorization": f"Bearer {RENDER_API_KEY}"
    }

    async with httpx.AsyncClient(timeout=30) as client:

        r = await client.post(url, headers=headers)

        if r.status_code not in [200, 202]:
            await message.answer(
                f"❌ Ошибка остановки\nHTTP {r.status_code}\n{r.text}",
                reply_markup=menu()
            )
            return

        await message.answer(
            "⏳ Ожидаю остановку сервиса..."
        )

        for _ in range(12):

            try:

                status = await client.get(
                    f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}",
                    headers=headers
                )

                if status.status_code == 200:

                    data = status.json()

                    suspended = (
                        str(data).lower().find("suspended") != -1
                    )

                    if suspended:

                        await message.answer(
                            "🔴 Inventory Bot полностью остановлен.",
                            reply_markup=menu()
                        )

                        return

            except:
                pass

            await asyncio.sleep(5)

    await message.answer(
        "⚠️ Команда отправлена. Render завершает остановку.",
        reply_markup=menu()
    )


@dp.message(F.text == "📊 Статус")
async def status_service(message: Message):

    if message.from_user.id not in ADMIN_IDS:
        return

    url = f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}"

    headers = {
        "Authorization": f"Bearer {RENDER_API_KEY}"
    }

    async with httpx.AsyncClient(timeout=30) as client:

        r = await client.get(url, headers=headers)

        if r.status_code != 200:

            await message.answer(
                f"❌ Ошибка получения статуса\nHTTP {r.status_code}"
            )
            return

        data = r.json()

        pretty = str(data).lower()

        if "suspend" in pretty:
            icon = "🔴"
            status = "Остановлен"
        elif "live" in pretty:
            icon = "🟢"
            status = "Работает"
        else:
            icon = "🟡"
            status = "Переходное состояние"

        await message.answer(
            f"""
⚙️ Inventory Bot

{icon} Статус: {status}

🆔 Service ID:
{RENDER_SERVICE_ID}
"""
        )


@dp.message(F.text.in_({"🟢 Запустить контроль кружков", "🔴 Остановить контроль кружков", "📊 Статус контроля кружков"}))
async def round_video_service(message: Message):
    """Manage the independent inventory video worker without changing the original service."""
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        return
    if not ROUND_VIDEO_SERVICE_ID or not RENDER_API_KEY:
        await message.answer("⚠️ Контроль кружков ещё не подключён. Настройте ROUND_VIDEO_SERVICE_ID и RENDER_API_KEY в Render сервиса управления.")
        return
    label = message.text
    action = "resume" if label.startswith("🟢") else ("suspend" if label.startswith("🔴") else "status")
    url = f"https://api.render.com/v1/services/{ROUND_VIDEO_SERVICE_ID}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if action == "status":
                response = await client.get(url, headers={"Authorization": f"Bearer {RENDER_API_KEY}"})
                response.raise_for_status()
                service = response.json().get("service", response.json())
                state = service.get("suspended", service.get("serviceDetails", {}).get("suspended", "unknown"))
                await message.answer(f"📊 Контроль кружков: suspended={state}. Статус Render: {service.get('status', 'см. панель Render')}")
            else:
                response = await client.post(f"{url}/{action}", headers={"Authorization": f"Bearer {RENDER_API_KEY}"})
                response.raise_for_status()
                await message.answer("✅ Команда запуска отправлена в Render." if action == "resume" else "✅ Команда остановки отправлена в Render.")
    except httpx.HTTPError as exc:
        logging.exception("Render request failed")
        await message.answer(f"⚠️ Render не выполнил команду ({type(exc).__name__}). Проверьте сервис в Render.")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession

from core.config import API_HASH, API_ID, PHONE


async def main() -> None:
    if not API_ID or not API_HASH:
        print("Не заданы API_ID и API_HASH. Заполните .env или переменные окружения.")
        sys.exit(1)

    phone = PHONE or input("Введите телефон Telegram (+79001234567): ").strip()
    if not phone:
        print("Телефон не задан.")
        sys.exit(1)

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start(phone=phone)
    session_string = client.session.save()
    await client.disconnect()

    print()
    print("Скопируйте эту переменную в Railway Variables:")
    print(f"SESSION_STRING={session_string}")


if __name__ == "__main__":
    asyncio.run(main())

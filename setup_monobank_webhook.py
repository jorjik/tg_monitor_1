import asyncio
import sys
import os

# Добавляем текущую директорию в путь поиска модулей, чтобы импорты из bot работали
sys.path.append(os.getcwd())

from bot.monobank import MonobankClient
from core.config import MONOBANK_TOKEN, MONOBANK_WEBHOOK_PATH

async def main():
    if not MONOBANK_TOKEN:
        print("❌ Ошибка: В файле .env не указан MONOBANK_TOKEN")
        return

    if len(sys.argv) < 2:
        print("❌ Ошибка: Не указан URL вебхука")
        print("\nИспользование:")
        print("  python setup_monobank_webhook.py https://ваш-домен.com")
        print("\nСкрипт автоматически добавит путь к вебхуку из конфига:")
        print(f"  Результат: https://ваш-домен.com{MONOBANK_WEBHOOK_PATH}")
        return

    domain = sys.argv[1].rstrip('/')
    webhook_url = f"{domain}{MONOBANK_WEBHOOK_PATH}"

    client = MonobankClient(MONOBANK_TOKEN)
    
    print(f"🔄 Попытка установить вебхук: {webhook_url}...")
    
    # Monobank API ограничение: 1 запрос в 60 секунд. 
    # В MonobankClient._wait_for_rate_limit() уже есть ожидание, 
    # но для первого запуска это не критично, если только вы не запускали другие скрипты Monobank.
    
    success = await client.set_webhook(webhook_url)
    
    if success:
        print(f"✅ Вебхук Monobank успешно установлен!")
        print(f"URL: {webhook_url}")
    else:
        print(f"❌ Ошибка при установке вебхука: {client.last_error}")

if __name__ == "__main__":
    asyncio.run(main())

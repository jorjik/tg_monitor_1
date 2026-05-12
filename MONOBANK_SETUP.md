# Интеграция Monobank - Инструкция по настройке

## 1. Получение токена Monobank API

1. Перейдите на https://api.monobank.ua/
2. Авторизуйтесь через приложение Monobank
3. Скопируйте персональный токен

## 2. Настройка переменных окружения

Откройте файл `.env` и добавьте/обновите следующие переменные:

```env
# Monobank
MONOBANK_TOKEN=ваш_токен_от_api.monobank.ua
MONOBANK_ACCOUNT_ID=0
MONOBANK_CURRENCY=UAH
MONOBANK_AMOUNT_PER_STAR=10
MONOBANK_WEBHOOK_PATH=/webhooks/monobank
```

### Пояснения:
- `MONOBANK_TOKEN` - токен из шага 1
- `MONOBANK_ACCOUNT_ID` - ID счета (0 = первый счет, можно узнать через API)
- `MONOBANK_CURRENCY` - валюта (UAH, USD, EUR)
- `MONOBANK_AMOUNT_PER_STAR` - цена 1 звезды в гривнах (10 грн = 1 звезда)
- `MONOBANK_WEBHOOK_PATH` - путь для webhook (используется общий порт с Ko-fi)

## 3. Настройка webhook в Monobank

### Вариант A: Через код (рекомендуется)

Создайте файл `setup_monobank_webhook.py`:

```python
import asyncio
from bot.monobank import MonobankClient
from core.config import MONOBANK_TOKEN

async def main():
    client = MonobankClient(MONOBANK_TOKEN)
    
    # Замените на ваш публичный URL
    webhook_url = "https://ваш-домен.com/webhooks/monobank"
    
    success = await client.set_webhook(webhook_url)
    if success:
        print(f"✅ Webhook установлен: {webhook_url}")
    else:
        print(f"❌ Ошибка: {client.last_error}")

if __name__ == "__main__":
    asyncio.run(main())
```

Запустите:
```bash
python setup_monobank_webhook.py
```

### Вариант B: Через curl

```bash
curl -X POST https://api.monobank.ua/personal/webhook \
  -H "X-Token: ваш_токен" \
  -H "Content-Type: application/json" \
  -d '{"webHookUrl": "https://ваш-домен.com/webhooks/monobank"}'
```

## 4. Получение ID счета (опционально)

Если у вас несколько счетов, узнайте ID нужного:

```python
import asyncio
from bot.monobank import MonobankClient
from core.config import MONOBANK_TOKEN

async def main():
    client = MonobankClient(MONOBANK_TOKEN)
    info = await client.get_client_info()
    
    if info:
        print("Ваши счета:")
        for i, account in enumerate(info.get("accounts", [])):
            print(f"{i}. {account['id']} - {account['currencyCode']} - {account['type']}")
    else:
        print(f"Ошибка: {client.last_error}")

if __name__ == "__main__":
    asyncio.run(main())
```

Обновите `MONOBANK_ACCOUNT_ID` в `.env` на нужный ID.

## 5. Настройка публичного доступа

Webhook должен быть доступен из интернета по HTTPS.

**Важно:** Ko-fi и Monobank webhook работают на **одном порту** (8080):
- Ko-fi: `https://ваш-домен.com/webhooks/kofi`
- Monobank: `https://ваш-домен.com/webhooks/monobank`

### Локальная разработка (ngrok):

```bash
ngrok http 8080
```

Используйте URL от ngrok для webhook.

### Railway:

Railway автоматически предоставляет публичный URL:
```
https://ваш-проект.up.railway.app
```

Webhook будет доступен по адресу:
```
https://ваш-проект.up.railway.app/webhooks/monobank
```

### Продакшн (nginx):

```nginx
server {
    listen 443 ssl;
    server_name ваш-домен.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # Единый порт для всех webhook
    location /webhooks/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 6. Включение метода оплаты

1. Запустите бота
2. Войдите как администратор
3. Перейдите в "💎 Тарифы"
4. Нажмите "💳 Способы оплаты"
5. Включите "Monobank"

## 7. Тестирование

1. Выберите тариф с оплатой через Monobank
2. Получите код платежа (например, `MB-A1B2C3D4`)
3. Переведите тестовую сумму на карту `5375414122814957`
4. В комментарии укажите код `MB-A1B2C3D4`
5. Бот должен автоматически активировать подписку

## 8. Ручная проверка платежей

Если платеж попал на ручную проверку:

1. Администратор получит уведомление
2. Перейдите в "💎 Тарифы" → "⚠️ Проверка оплат"
3. Откройте платеж и одобрите/отклоните

## Возможные проблемы

### Webhook не работает

1. Проверьте, что порт 8080 открыт (единый для Ko-fi и Monobank)
2. Проверьте логи: `tail -f data/monitor.log`
3. Убедитесь, что URL доступен извне: `curl https://ваш-домен.com/webhooks/monobank`
4. Проверьте, что оба webhook запустились: в логах должно быть "Payment webhooks started"

### Платежи не находятся

1. Проверьте, что код указан в комментарии к переводу
2. Проверьте сумму (должна совпадать с тарифом)
3. Проверьте валюту счета

### Rate limit (429 ошибка)

Monobank API ограничивает запросы до 1 в 60 секунд. Клиент автоматически ждет, но если нужно срочно:
- Используйте webhook вместо polling
- Не делайте частые запросы к API

## Ограничения Monobank Personal API

- ❌ Нельзя использовать как корпоративный сервис
- ❌ Максимум 1 запрос в 60 секунд
- ❌ Выписка доступна за последние 31 день
- ✅ Webhook работает в реальном времени
- ✅ Бесплатно для личного использования

## Переход на Monobank Acquiring (для бизнеса)

Если нужны:
- Генерация платежных ссылок
- QR-коды для оплаты
- Больше запросов к API
- Официальный статус

Обратитесь в Monobank для подключения эквайринга: https://www.monobank.ua/acquiring

# Быстрая настройка Monobank для Railway

## 1. Получите токен Monobank

1. Откройте https://api.monobank.ua/
2. Авторизуйтесь через приложение Monobank
3. Скопируйте токен

## 2. Добавьте переменные в Railway

В Railway Dashboard → Variables:

```
MONOBANK_TOKEN=ваш_токен
MONOBANK_CURRENCY=UAH
MONOBANK_AMOUNT_PER_STAR=10
```

## 3. Задеплойте на Railway

Railway автоматически пересоберет и запустит бота.

Ваш webhook будет доступен по адресу:
```
https://ваш-проект.up.railway.app/webhooks/monobank
```

## 4. Установите webhook в Monobank

**Локально** на вашем компьютере запустите:

```bash
cd c:\dev\tg\мой-монитор-1
python setup_monobank_webhook.py
```

Введите Railway URL: `https://ваш-проект.up.railway.app`

## 5. Включите Monobank в боте

1. Откройте бота в Telegram
2. Войдите как администратор
3. **💎 Тарифы** → **💳 Способы оплаты**
4. Включите **Monobank**

## 6. Готово! 🎉

Теперь пользователи могут оплачивать через Monobank:
- Выбирают тариф
- Получают код платежа (MB-XXXXXXXX)
- Переводят деньги с кодом в комментарии
- Бот автоматически активирует подписку

## Проверка работы

В логах Railway должно быть:
```
Payment webhooks started on http://0.0.0.0:8080
  Ko-fi:     /webhooks/kofi
  Monobank:  /webhooks/monobank
```

## Важно

- Webhook устанавливается **один раз**
- Работает автоматически при каждом платеже
- Не нужно переустанавливать при перезапуске бота
- Оба webhook (Ko-fi и Monobank) работают на **одном порту** (8080)

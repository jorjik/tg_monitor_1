Важно по деплою: после этих правок нужно задать MONOBANK_WEBHOOK_SECRET, MONOBANK_CARD
и один раз переустановить вебхук (python setup_monobank_webhook.py https://ваш-домен) —
URL теперь со секретом, иначе Monobank-webhook просто не будет принимать платежи.

# Telegram AI-бот (бесплатные модели: Groq + Pollinations)

Бот-ассистент на полностью бесплатных сервисах: текст через Groq (Llama 3.3/3.1), картинки через Pollinations.ai.

## Возможности

- Обычный чат с AI — /start, потом просто пиши сообщения
- `/model` — переключение между "умной" (llama-3.3-70b) и "быстрой" (llama-3.1-8b) моделью
- `/image <описание>` — генерация картинки через Pollinations.ai (без ключа)
- `/reset` — очистить историю диалога (у каждого пользователя своя история, хранится в памяти процесса)

## Локальный запуск

1. Установи зависимости:
   ```bash
   pip install -r requirements.txt
   ```
2. Скопируй `.env.example` в `.env` и впиши свои ключи:
   ```bash
   cp .env.example .env
   ```
3. Запусти:
   ```bash
   python bot.py
   ```

## Где взять ключи

- **TELEGRAM_BOT_TOKEN** — у [@BotFather](https://t.me/BotFather) в Telegram, команда `/newbot`
- **GROQ_API_KEY** — https://console.groq.com/keys — регистрация без карты, бесплатный лимит запросов в день/минуту
- Картинки (Pollinations.ai) — ключ не требуется вообще

## Деплой на Railway

1. Залей код в GitHub-репозиторий (bot.py, requirements.txt, Dockerfile, README.md)
2. В Railway: New Project → Deploy from GitHub repo → выбери репозиторий
3. Во вкладке Variables добавь:
   - `TELEGRAM_BOT_TOKEN`
   - `GROQ_API_KEY`
4. Проверь Deploy Logs — должна появиться строка `Bot started, polling...`

## Деплой на любой хостинг с Docker (VPS, Render, Fly.io, etc.)

```bash
docker build -t ai-bot .
docker run -d --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN=xxx \
  -e GROQ_API_KEY=xxx \
  ai-bot
```

## Про лимиты Groq

Бесплатный тариф Groq ограничен по количеству запросов в минуту/день (лимиты периодически меняются,
актуальные — на console.groq.com/settings/limits). Для личного использования и небольшой группы
пользователей этого более чем достаточно.

## Структура проекта

```
ai_bot/
├── bot.py              # основная логика бота
├── requirements.txt    # зависимости
├── .env.example         # шаблон переменных окружения
├── Dockerfile           # для деплоя в контейнере
└── README.md
```


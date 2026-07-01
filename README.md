# Telegram AI-бот (ChatGPT + Gemini)

Бот-ассистент с переключением между ChatGPT и Gemini, плюс генерация картинок по описанию.

## Возможности

- Обычный чат с AI — /start, потом просто пиши сообщения
- `/model` — переключение между ChatGPT (gpt-4o-mini) и Gemini (gemini-2.0-flash)
- `/image <описание>` — генерация картинки через DALL-E 3
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
- **OPENAI_API_KEY** — https://platform.openai.com/api-keys (нужен привязанный платёжный метод, оплата по факту использования)
- **GEMINI_API_KEY** — https://aistudio.google.com/apikey (есть бесплатный лимит запросов в день)

## Деплой на любой хостинг с Docker (VPS, Render, Fly.io, etc.)

```bash
docker build -t ai-bot .
docker run -d --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN=xxx \
  -e OPENAI_API_KEY=xxx \
  -e GEMINI_API_KEY=xxx \
  ai-bot
```

На большинстве хостингов (Render, Fly.io, обычный VPS) переменные окружения задаются
через их панель управления или флаги `-e` — просто не забудь прописать все три ключа.

Если хостинг не поддерживает Docker (например, обычный VPS без него) — можно запустить
как systemd-сервис: `python bot.py` в screen/tmux или через systemd unit с автоперезапуском.

## Про генерацию видео

Видео-генерация (Sora, Veo и т.п.) пока не включена в бота — доступ к этим API
либо платный и дорогой за единицу видео, либо ограничен списком (waitlist),
либо требует отдельной подписки. Если у тебя уже есть доступ к одному из таких API —
скажи, добавлю обработчик `/video` по аналогии с `/image`.

## Стоимость (ориентировочно)

- ChatGPT (gpt-4o-mini): дёшево, доли цента за сообщение
- Gemini flash: есть бесплатный тариф с лимитом запросов/день
- DALL-E 3: ~$0.04 за картинку 1024x1024

## Структура проекта

```
ai_bot/
├── bot.py              # основная логика бота
├── requirements.txt    # зависимости
├── .env.example         # шаблон переменных окружения
├── Dockerfile           # для деплоя в контейнере
└── README.md
```

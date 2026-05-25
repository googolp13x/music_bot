import yt_dlp
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

import os
TOKEN = os.getenv("TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я музыкальный бот 🎵\n"
        "Напиши название трека или исполнителя."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    await update.message.reply_text(f"Ищу «{query}»...")

    # Настройки поиска и скачивания
options = {
    "format": "bestaudio/best",
    "outtmpl": "/tmp/%(title)s.%(ext)s",
    "default_search": "scsearch1",
    "quiet": True,
    "ffmpeg_location": "/usr/bin/ffmpeg",
    "postprocessors": [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
    }],
}

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(query, download=True)
            # Берём первый результат из поиска
            if "entries" in info:
                info = info["entries"][0]
            filename = ydl.prepare_filename(info).replace(".webm", ".mp3").replace(".m4a", ".mp3")

        # Отправляем файл в Telegram
        with open(filename, "rb") as audio:
            await update.message.reply_audio(audio, title=info.get("title", query))

    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT, handle_message))

print("Бот запущен!")
app.run_polling()
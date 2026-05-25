import os
import yt_dlp
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TOKEN")
FFMPEG_PATH = "/nix/store/zcbf5d79fdqbg26y8q186x60pqlc4ij6-ffmpeg-7.1-bin/bin/ffmpeg"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎵 Музыкальный бот\n\n"
        "Напиши название трека или исполнителя — я найду и пришлю музыку.\n\n"
        "Например: Radiohead Creep"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    searching = await update.message.reply_text(f"🔍 Ищу «{query}»...")

    options = {
        "format": "bestaudio/best",
        "outtmpl": "/tmp/%(title)s.%(ext)s",
        "default_search": "scsearch1",
        "quiet": True,
        "ffmpeg_location": FFMPEG_PATH,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
        }],
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(query, download=True)
            if "entries" in info:
                info = info["entries"][0]
            filename = ydl.prepare_filename(info).replace(".webm", ".mp3").replace(".m4a", ".mp3")

    title = info.get("title", query)
    duration = int(info.get("duration", 0))
    minutes = duration // 60
    seconds = duration % 60

        await searching.delete()
        await update.message.reply_text(f"✅ Нашёл: {title} ({minutes}:{seconds:02d})")

        with open(filename, "rb") as audio:
            await update.message.reply_audio(
                audio,
                title=title,
                performer=info.get("uploader", ""),
                duration=duration,
            )

        os.remove(filename)

    except Exception as e:
        await searching.delete()
        await update.message.reply_text(
            "😕 Не удалось найти трек.\n"
            "Попробуйте уточнить запрос, например: «Arctic Monkeys Do I Wanna Know»"
        )

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Бот запущен!")
app.run_polling()
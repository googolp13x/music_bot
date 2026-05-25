import os
import logging
import yt_dlp
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TOKEN")
FFMPEG_PATH = "/nix/store/zcbf5d79fdqbg26y8q186x60pqlc4ij6-ffmpeg-7.1-bin/bin/ffmpeg"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎵 SKMusic Bot\n\n"
        "Send me a track or artist name — I'll find and send the music.\n\n"
        "Example: Yung Lean Highway Patrol.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    searching = await update.message.reply_text(f"🔍 Searching «{query}»...")

    options = {
        "format": "bestaudio/best",
        "outtmpl": "/tmp/%(title)s.%(ext)s",
        "default_search": "scsearch1",
        "quiet": False,
        "ffmpeg_location": FFMPEG_PATH,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
        }],
    }

    try:
        logger.info(f"Начинаю поиск: {query}")
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(query, download=True)
            logger.info(f"Скачал, info keys: {list(info.keys())}")
            if "entries" in info:
                info = info["entries"][0]
            filename = ydl.prepare_filename(info).replace(".webm", ".mp3").replace(".m4a", ".mp3")
            logger.info(f"Файл: {filename}")

        await searching.delete()

        with open(filename, "rb") as audio:
            await update.message.reply_text(
    f"✅ {title} ({minutes}:{seconds:02d})\n"
    f"──────────────\n"
    f"🎧 @ggp1xmusic\\_bot\n"
    f"📻 your personal music bot"
)

        os.remove(filename)

    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        await searching.delete()
        await update.message.reply_text(f"Ошибка: {e}")

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Бот запущен!")
app.run_polling()

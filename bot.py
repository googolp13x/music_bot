import os
import yt_dlp
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

TOKEN = os.getenv("TOKEN")
FFMPEG_PATH = "/nix/store/zcbf5d79fdqbg26y8q186x60pqlc4ij6-ffmpeg-7.1-bin/bin/ffmpeg"

KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("▶️ Start"), KeyboardButton("❓ Help")]],
    resize_keyboard=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎵 SKMusic Bot\n\n"
        "Send me a track or artist name — I'll find and send the music.\n\n"
        "Example: Yung Lean Highway Patrol.",
        reply_markup=KEYBOARD
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ How to use SKMusic Bot:\n\n"
        "Just type the name of a track or artist and I'll find it for you.\n\n"
        "Examples:\n"
        "• Radiohead Creep\n"
        "• Yung Lean Highway Patrol\n"
        "• Arctic Monkeys\n\n"
        "The bot searches SoundCloud and sends the audio directly to this chat.",
        reply_markup=KEYBOARD
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text

    if query == "▶️ Start":
        await start(update, context)
        return

    if query == "❓ Help":
        await help_command(update, context)
        return

    searching = await update.message.reply_text(f"🔍 Searching «{query}»...")

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
        await update.message.reply_text(
            f"✅ {title} ({minutes}:{seconds:02d})\n"
            f"──────────────\n"
            f"🎧 @ggp1xmusic\\_bot\n"
            f"📻 your personal music bot",
            reply_markup=KEYBOARD
        )

        with open(filename, "rb") as audio:
            await update.message.reply_audio(
                audio,
                title=title,
                performer=info.get("uploader", ""),
                duration=duration,
                read_timeout=120,
                write_timeout=120,
                connect_timeout=120,
            )

        os.remove(filename)

    except Exception as e:
        await searching.delete()
        await update.message.reply_text(
            "😕 Could not find the track.\n"
            "Try a more specific search, e.g. «Arctic Monkeys Do I Wanna Know»",
            reply_markup=KEYBOARD
        )

request = HTTPXRequest(read_timeout=120, write_timeout=120, connect_timeout=120)
app = ApplicationBuilder().token(TOKEN).request(request).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Bot started!")
app.run_polling()
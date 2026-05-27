import os
import yt_dlp
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

TOKEN = os.getenv("TOKEN")
FFMPEG_PATH = "/nix/store/zcbf5d79fdqbg26y8q186x60pqlc4ij6-ffmpeg-7.1-bin/bin/ffmpeg"

KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🔍 Find"), KeyboardButton("❓ Help")]],
    resize_keyboard=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to SKMusic Bot!\n\n"
        "🎵 Just type any track or artist name and I'll find the music for you.\n\n"
        "Example: Yung Lean Highway Patrol\n\n"
        "Use the buttons below to get started 👇",
        reply_markup=KEYBOARD
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ How to use SKMusic Bot:\n\n"
        "Just type the name of a track or artist and I'll find it for you.\n\n"
        "Examples:\n"
        "• Aphex Twin Flim\n"
        "• Yung Lean Highway Patrol\n"
        "• Arctic Monkeys\n\n"
        "The bot searches SoundCloud and sends the audio directly to this chat.",
        reply_markup=KEYBOARD
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text

    if query == "🔍 Find":
        await update.message.reply_text(
            "🎵 Type the track or artist name:",
            reply_markup=KEYBOARD
        )
        return

    if query == "❓ Help":
        await help_command(update, context)
        return

    searching = await update.message.reply_text(f"🔍 Searching «{query}»...")

    options = {
        "format": "bestaudio/best",
        "default_search": "scsearch5",
        "quiet": True,
        "extract_flat": "in_playlist",
        "noplaylist": False,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(query, download=False)
            entries = info.get("entries", [])

        if not entries:
            await searching.delete()
            await update.message.reply_text("😕 Nothing found. Try a different search.")
            return

        context.user_data["results"] = entries

        buttons = []
        for i, entry in enumerate(entries[:5]):
            title = entry.get("title", "Unknown")[:50]
            duration = int(entry.get("duration") or 0)
            minutes = duration // 60
            seconds = duration % 60
            buttons.append([InlineKeyboardButton(
                f"{i+1}. {title} ({minutes}:{seconds:02d})",
                callback_data=str(i)
            )])

        await searching.delete()
        await update.message.reply_text(
            "🎵 Choose a track:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    except Exception as e:
        await searching.delete()
        await update.message.reply_text("😕 Could not find the track. Try again.")

async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    index = int(query.data)
    results = context.user_data.get("results", [])

    if not results or index >= len(results):
        await query.edit_message_text("❌ Something went wrong. Search again.")
        return

    entry = results[index]
    url = entry.get("url") or entry.get("webpage_url")

    await query.edit_message_text("⬇️ Downloading...")

    options = {
        "format": "bestaudio/best",
        "outtmpl": "/tmp/%(title)s.%(ext)s",
        "quiet": True,
        "ffmpeg_location": FFMPEG_PATH,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
        }],
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info).replace(".webm", ".mp3").replace(".m4a", ".mp3")

        title = info.get("title", "Unknown")
        duration = int(info.get("duration", 0))
        minutes = duration // 60
        seconds = duration % 60

        await query.edit_message_text(
            f"✅ {title} ({minutes}:{seconds:02d})\n"
            f"──────────────\n"
            f"🎧 @ggp1xmusic\\_bot\n"
            f"📻 your personal music bot"
        )

        with open(filename, "rb") as audio:
            await context.bot.send_audio(
                chat_id=query.message.chat_id,
                audio=audio,
                title=title,
                performer=info.get("uploader", ""),
                duration=duration,
                read_timeout=120,
                write_timeout=120,
                connect_timeout=120,
            )

        os.remove(filename)

    except Exception as e:
        await query.edit_message_text("😕 Could not download. Try another track.")

request = HTTPXRequest(read_timeout=120, write_timeout=120, connect_timeout=120)
app = ApplicationBuilder().token(TOKEN).request(request).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(CallbackQueryHandler(handle_choice))

print("Bot started!")
app.run_polling()
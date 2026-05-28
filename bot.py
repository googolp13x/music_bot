import logging
import os
import glob
import shutil
import tempfile
import yt_dlp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

TOKEN = os.getenv("TOKEN")
FFMPEG_PATH = "/nix/store/zcbf5d79fdqbg26y8q186x60pqlc4ij6-ffmpeg-7.1-bin/bin/ffmpeg"

# Optional: set YOUTUBE_COOKIES env var with the contents of a cookies.txt file
# to bypass YouTube bot detection (export from browser via "Get cookies.txt" extension)
COOKIES_FILE = "/tmp/yt_cookies.txt"
_raw_cookies = os.getenv("YOUTUBE_COOKIES", "")
if _raw_cookies:
    with open(COOKIES_FILE, "w") as _f:
        _f.write(_raw_cookies)
    logging.info("Cookies loaded: %d bytes, %d lines", len(_raw_cookies), _raw_cookies.count("\n"))
else:
    COOKIES_FILE = None
    logging.warning("YOUTUBE_COOKIES not set — running without cookies")

YT_EXTRACTOR_ARGS = {"youtube": {"player_client": ["tv_embedded", "web_embedded", "android"]}}

KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🔍 Find"), KeyboardButton("❓ Help")]],
    resize_keyboard=True
)

PLATFORM_EMOJI = {"sc": "🟢", "yt": "🔴"}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to SKMusic Bot!\n\n"
        "🎵 Just type any track or artist name and I'll find the music for you.\n\n"
        "Example: Yung Lean Highway Patrol\n\n"
        "🟢 SoundCloud  🔴 YouTube\n\n"
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
        "🟢 SoundCloud and 🔴 YouTube results are shown together.\n"
        "Pick a track and I'll send the audio directly to this chat.",
        reply_markup=KEYBOARD
    )


def _yt_base_options(extra: dict = None) -> dict:
    opts = {
        "extractor_args": YT_EXTRACTOR_ARGS,
        "quiet": True,
    }
    if COOKIES_FILE:
        opts["cookiefile"] = COOKIES_FILE
    if extra:
        opts.update(extra)
    return opts


def _search_platform(query: str, search_prefix: str, limit: int) -> list:
    options = _yt_base_options({
        "format": "bestaudio/best",
        "default_search": f"{search_prefix}{limit}",
        "extract_flat": "in_playlist",
        "noplaylist": False,
    })
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(query, download=False)
            return info.get("entries", [])
    except Exception:
        return []


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

    sc_entries = _search_platform(query, "scsearch", 3)
    for e in sc_entries:
        e["_platform"] = "sc"

    yt_entries = _search_platform(query, "ytsearch", 2)
    for e in yt_entries:
        e["_platform"] = "yt"

    entries = sc_entries + yt_entries

    if not entries:
        await searching.delete()
        await update.message.reply_text("😕 Nothing found. Try a different search.")
        return

    context.user_data["results"] = entries

    buttons = []
    for i, entry in enumerate(entries[:5]):
        platform = PLATFORM_EMOJI.get(entry.get("_platform", "sc"), "🎵")
        title = entry.get("title", "Unknown")[:40]
        duration = int(entry.get("duration") or 0)
        minutes = duration // 60
        seconds = duration % 60
        buttons.append([InlineKeyboardButton(
            f"{platform} {i + 1}. {title} ({minutes}:{seconds:02d})",
            callback_data=str(i)
        )])

    await searching.delete()
    await update.message.reply_text(
        "🎵 Choose a track:\n🟢 SoundCloud  🔴 YouTube",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


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

    tmpdir = tempfile.mkdtemp()

    options = _yt_base_options({
        "format": "bestaudio/best",
        "outtmpl": f"{tmpdir}/%(title)s.%(ext)s",
        "ffmpeg_location": FFMPEG_PATH,
        "writethumbnail": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3"},
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
        ],
    })

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)

        audio_files = glob.glob(f"{tmpdir}/*.mp3")
        image_files = glob.glob(f"{tmpdir}/*.jpg") + glob.glob(f"{tmpdir}/*.jpeg")

        if not audio_files:
            await query.edit_message_text("😕 Could not download. Try another track.")
            return

        filename = audio_files[0]
        thumb_file = image_files[0] if image_files else None

        title = info.get("title", "Unknown")
        duration = int(info.get("duration", 0))
        minutes = duration // 60
        seconds = duration % 60

        file_size = os.path.getsize(filename)
        if file_size > 50 * 1024 * 1024:
            await query.edit_message_text(
                "📦 Track is too large for Telegram (>50 MB).\n"
                "Try a different version or a shorter track."
            )
            return

        await query.edit_message_text(
            f"✅ {title} ({minutes}:{seconds:02d})\n"
            f"──────────────\n"
            f"🎧 @ggp1xmusic\n"
            f"📻 your personal music bot"
        )

        thumb = open(thumb_file, "rb") if thumb_file else None
        try:
            with open(filename, "rb") as audio:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id,
                    audio=audio,
                    title=title,
                    performer=info.get("uploader", ""),
                    duration=duration,
                    thumbnail=thumb,
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=120,
                )
        finally:
            if thumb:
                thumb.close()

    except yt_dlp.utils.DownloadError as e:
        logging.error("Download error for url=%s: %s", url, e)
        err = str(e).lower()
        if "sign in" in err or "bot" in err:
            msg = "🔒 YouTube blocked this download. Try a 🟢 SoundCloud track instead."
        elif "private" in err or "unavailable" in err or "deleted" in err:
            msg = "🚫 This track is private or no longer available."
        elif "age" in err:
            msg = "🔞 Age-restricted track, cannot download."
        elif "copyright" in err or "blocked" in err:
            msg = "⛔️ This track is blocked due to copyright. Try another."
        else:
            msg = "😕 Could not download. Try another track."
        await query.edit_message_text(msg)

    except Exception as e:
        logging.error("Unexpected error for url=%s: %s", url, e, exc_info=True)
        await query.edit_message_text("⚠️ Something went wrong. Please try again.")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


request = HTTPXRequest(read_timeout=120, write_timeout=120, connect_timeout=120)
app = ApplicationBuilder().token(TOKEN).request(request).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(CallbackQueryHandler(handle_choice))

print("Bot started!")
app.run_polling()

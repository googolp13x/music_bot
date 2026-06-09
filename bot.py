import asyncio
import logging
import os
import glob
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import yt_dlp
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ── Config ────────────────────────────────────────────────────────────────────

TOKEN = os.getenv("TOKEN")
FFMPEG_PATH = "/nix/store/zcbf5d79fdqbg26y8q186x60pqlc4ij6-ffmpeg-7.1-bin/bin/ffmpeg"

# Set YOUTUBE_COOKIES env var with the contents of a cookies.txt file
# to bypass YouTube bot detection (export via "Get cookies.txt" browser extension)
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

# ── Search cache ──────────────────────────────────────────────────────────────

CACHE_TTL = 600  # 10 minutes
_search_cache: dict = {}


def _cache_get(query: str) -> list | None:
    key = query.strip().lower()
    if key in _search_cache:
        ts, entries = _search_cache[key]
        if time.time() - ts < CACHE_TTL:
            return entries
        del _search_cache[key]
    return None


def _cache_set(query: str, entries: list) -> None:
    now = time.time()
    expired = [k for k, (ts, _) in _search_cache.items() if now - ts >= CACHE_TTL]
    for k in expired:
        del _search_cache[k]
    _search_cache[query.strip().lower()] = (now, entries)


# ── Spam protection ───────────────────────────────────────────────────────────

SEARCH_COOLDOWN = 3   # seconds between searches per user
_last_search: dict = {}       # user_id → timestamp
_active_downloads: set = set()  # user_ids with a download in progress


def _check_search_cooldown(user_id: int) -> float:
    """Returns remaining cooldown in seconds, or 0 if ready."""
    elapsed = time.time() - _last_search.get(user_id, 0)
    return max(0.0, SEARCH_COOLDOWN - elapsed)


# ── Parallel search ───────────────────────────────────────────────────────────

_executor = ThreadPoolExecutor(max_workers=4)


def _yt_base_options(extra: dict = None) -> dict:
    opts = {"extractor_args": YT_EXTRACTOR_ARGS, "quiet": True}
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


async def _search_async(query: str, search_prefix: str, limit: int, platform: str) -> list:
    loop = asyncio.get_event_loop()
    entries = await loop.run_in_executor(_executor, _search_platform, query, search_prefix, limit)
    for e in entries:
        e["_platform"] = platform
    return entries


# ── UI ────────────────────────────────────────────────────────────────────────

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


# ── Handlers ──────────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🔍 Find":
        await update.message.reply_text("🎵 Type the track or artist name:", reply_markup=KEYBOARD)
        return

    if text == "❓ Help":
        await help_command(update, context)
        return

    user_id = update.message.from_user.id

    # spam protection: cooldown between searches
    wait = _check_search_cooldown(user_id)
    if wait > 0:
        await update.message.reply_text(f"⏳ Please wait {wait:.0f}s before searching again.")
        return
    _last_search[user_id] = time.time()

    cached = _cache_get(text)
    if cached:
        logging.info("Cache hit: %s", text)
        entries = cached
        searching = None
    else:
        searching = await update.message.reply_text(f"🔍 Searching «{text}»...")

        # parallel search: SoundCloud + YouTube at the same time
        sc_task = _search_async(text, "scsearch", 3, "sc")
        yt_task = _search_async(text, "ytsearch", 2, "yt")
        sc_entries, yt_entries = await asyncio.gather(sc_task, yt_task)

        entries = sc_entries + yt_entries
        if entries:
            _cache_set(text, entries)

    if not entries:
        if searching:
            await searching.delete()
        await update.message.reply_text("😕 Nothing found. Try a different search.")
        return

    context.user_data["results"] = entries

    buttons = []
    for i, entry in enumerate(entries[:5]):
        platform = PLATFORM_EMOJI.get(entry.get("_platform", "sc"), "🎵")
        title = entry.get("title", "Unknown")[:40]
        duration = int(entry.get("duration") or 0)
        minutes, seconds = divmod(duration, 60)
        buttons.append([InlineKeyboardButton(
            f"{platform} {i + 1}. {title} ({minutes}:{seconds:02d})",
            callback_data=str(i)
        )])

    if searching:
        await searching.delete()
    await update.message.reply_text(
        "🎵 Choose a track:\n🟢 SoundCloud  🔴 YouTube",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    # spam protection: one download at a time per user
    if user_id in _active_downloads:
        await query.answer("⏳ Your previous download is still in progress.", show_alert=True)
        return

    await query.answer()

    index = int(query.data)
    results = context.user_data.get("results", [])

    if not results or index >= len(results):
        await query.edit_message_text("❌ Something went wrong. Search again.")
        return

    entry = results[index]
    url = entry.get("url") or entry.get("webpage_url")

    _active_downloads.add(user_id)
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
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(options) as ydl:
            info = await loop.run_in_executor(_executor, lambda: ydl.extract_info(url, download=True))

        audio_files = glob.glob(f"{tmpdir}/*.mp3")
        image_files = glob.glob(f"{tmpdir}/*.jpg") + glob.glob(f"{tmpdir}/*.jpeg")

        if not audio_files:
            await query.edit_message_text("😕 Could not download. Try another track.")
            return

        filename = audio_files[0]
        thumb_file = image_files[0] if image_files else None

        title = info.get("title", "Unknown")
        duration = int(info.get("duration", 0))
        minutes, seconds = divmod(duration, 60)

        if os.path.getsize(filename) > 50 * 1024 * 1024:
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
        logging.error("Download error url=%s: %s", url, e)
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
        logging.error("Unexpected error url=%s: %s", url, e, exc_info=True)
        await query.edit_message_text("⚠️ Something went wrong. Please try again.")

    finally:
        _active_downloads.discard(user_id)
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── App ───────────────────────────────────────────────────────────────────────

request = HTTPXRequest(read_timeout=120, write_timeout=120, connect_timeout=120)
app = ApplicationBuilder().token(TOKEN).request(request).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(CallbackQueryHandler(handle_choice))

print("Bot started!")
app.run_polling()

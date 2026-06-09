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

# ── Localization ──────────────────────────────────────────────────────────────

STRINGS = {
    "en": {
        "start": (
            "🎵 <b>Muze</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Type a track or artist name — I'll find the music and send it right here.\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "<b>Sources:</b>\n"
            "🟢 SoundCloud  ·  🔴 YouTube\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "<b>Try:</b>\n"
            "<i>Yung Lean Highway Patrol</i>"
        ),
        "help": (
            "❓ <b>How to use Muze</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "1️⃣  <b>Type</b> a track or artist name\n"
            "2️⃣  <b>Choose</b> a track from results\n"
            "3️⃣  <b>Get</b> MP3 right in chat\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "<b>Examples:</b>\n"
            "· <code>Aphex Twin Flim</code>\n"
            "· <code>Yung Lean Highway Patrol</code>\n"
            "· <code>Arctic Monkeys</code>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🟢 SoundCloud  ·  🔴 YouTube"
        ),
        "btn_find":     "🔍 Find",
        "btn_help":     "❓ Help",
        "type_query":   "🎵 Type the track or artist name:",
        "searching":    "🔍 Searching «{}»...",
        "choose_track": "🎵 Choose a track:\n🟢 SoundCloud  ·  🔴 YouTube",
        "not_found":    "😕 Nothing found. Try a different search.",
        "downloading":  "⬇️ Downloading...",
        "too_large":    "📦 Track is too large for Telegram (>50 MB).\nTry a shorter version.",
        "wrong":        "❌ Something went wrong. Search again.",
        "cooldown":     "⏳ Please wait {}s before searching again.",
        "busy":         "⏳ Your previous download is still in progress.",
        "err_blocked":  "🔒 YouTube blocked this download. Try a 🟢 SoundCloud track.",
        "err_private":  "🚫 This track is private or no longer available.",
        "err_age":      "🔞 Age-restricted track, cannot download.",
        "err_copyright":"⛔️ Blocked due to copyright. Try another track.",
        "err_download": "😕 Could not download. Try another track.",
        "err_unknown":  "⚠️ Something went wrong. Please try again.",
    },
    "ru": {
        "start": (
            "🎵 <b>Muze</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Напиши название трека или исполнителя — я найду музыку и пришлю аудио прямо сюда.\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "<b>Источники:</b>\n"
            "🟢 SoundCloud  ·  🔴 YouTube\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "<b>Попробуй:</b>\n"
            "<i>Yung Lean Highway Patrol</i>"
        ),
        "help": (
            "❓ <b>Как пользоваться Muze</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "1️⃣  <b>Напиши</b> название трека или артиста\n"
            "2️⃣  <b>Выбери</b> трек из результатов\n"
            "3️⃣  <b>Получи</b> MP3 прямо в чат\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "<b>Примеры:</b>\n"
            "· <code>Aphex Twin Flim</code>\n"
            "· <code>Yung Lean Highway Patrol</code>\n"
            "· <code>Arctic Monkeys</code>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🟢 SoundCloud  ·  🔴 YouTube"
        ),
        "btn_find":     "🔍 Найти",
        "btn_help":     "❓ Помощь",
        "type_query":   "🎵 Напиши название трека или артиста:",
        "searching":    "🔍 Ищу «{}»...",
        "choose_track": "🎵 Выбери трек:\n🟢 SoundCloud  ·  🔴 YouTube",
        "not_found":    "😕 Ничего не найдено. Попробуй другой запрос.",
        "downloading":  "⬇️ Скачиваю...",
        "too_large":    "📦 Трек слишком большой для Telegram (>50 МБ).\nПопробуй более короткую версию.",
        "wrong":        "❌ Что-то пошло не так. Поищи снова.",
        "cooldown":     "⏳ Подожди {}с перед следующим поиском.",
        "busy":         "⏳ Предыдущая загрузка ещё не завершена.",
        "err_blocked":  "🔒 YouTube заблокировал загрузку. Попробуй 🟢 SoundCloud.",
        "err_private":  "🚫 Этот трек приватный или недоступен.",
        "err_age":      "🔞 Трек с возрастным ограничением, загрузка невозможна.",
        "err_copyright":"⛔️ Трек заблокирован из-за авторских прав. Попробуй другой.",
        "err_download": "😕 Не удалось скачать. Попробуй другой трек.",
        "err_unknown":  "⚠️ Что-то пошло не так. Попробуй ещё раз.",
    },
}


def get_lang(user) -> str:
    code = (user.language_code or "en")[:2].lower()
    return code if code in STRINGS else "en"


def t(key: str, lang: str, *args) -> str:
    s = STRINGS.get(lang, STRINGS["en"]).get(key) or STRINGS["en"].get(key, key)
    return s.format(*args) if args else s


def make_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(t("btn_find", lang)), KeyboardButton(t("btn_help", lang))]],
        resize_keyboard=True,
    )


# ── Search cache ──────────────────────────────────────────────────────────────

CACHE_TTL = 600
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
    for k in [k for k, (ts, _) in _search_cache.items() if now - ts >= CACHE_TTL]:
        del _search_cache[k]
    _search_cache[query.strip().lower()] = (now, entries)


# ── Spam protection ───────────────────────────────────────────────────────────

SEARCH_COOLDOWN = 3
_last_search: dict = {}
_active_downloads: set = set()


def _check_search_cooldown(user_id: int) -> float:
    return max(0.0, SEARCH_COOLDOWN - (time.time() - _last_search.get(user_id, 0)))


# ── yt-dlp helpers ────────────────────────────────────────────────────────────

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


# ── Handlers ──────────────────────────────────────────────────────────────────

PLATFORM_EMOJI = {"sc": "🟢", "yt": "🔴"}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.message.from_user)
    await update.message.reply_text(
        t("start", lang),
        parse_mode="HTML",
        reply_markup=make_keyboard(lang),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.message.from_user)
    await update.message.reply_text(
        t("help", lang),
        parse_mode="HTML",
        reply_markup=make_keyboard(lang),
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.message.from_user
    lang = get_lang(user)

    if text == t("btn_find", lang):
        await update.message.reply_text(t("type_query", lang), reply_markup=make_keyboard(lang))
        return

    if text == t("btn_help", lang):
        await help_command(update, context)
        return

    wait = _check_search_cooldown(user.id)
    if wait > 0:
        await update.message.reply_text(t("cooldown", lang, f"{wait:.0f}"))
        return
    _last_search[user.id] = time.time()

    cached = _cache_get(text)
    if cached:
        logging.info("Cache hit: %s", text)
        entries = cached
        searching = None
    else:
        searching = await update.message.reply_text(t("searching", lang, text))

        sc_entries, yt_entries = await asyncio.gather(
            _search_async(text, "scsearch", 3, "sc"),
            _search_async(text, "ytsearch", 2, "yt"),
        )
        entries = sc_entries + yt_entries
        if entries:
            _cache_set(text, entries)

    if not entries:
        if searching:
            await searching.delete()
        await update.message.reply_text(t("not_found", lang))
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
            callback_data=str(i),
        )])

    if searching:
        await searching.delete()
    await update.message.reply_text(
        t("choose_track", lang),
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    lang = get_lang(query.from_user)

    if user_id in _active_downloads:
        await query.answer(t("busy", lang), show_alert=True)
        return

    await query.answer()

    index = int(query.data)
    results = context.user_data.get("results", [])

    if not results or index >= len(results):
        await query.edit_message_text(t("wrong", lang))
        return

    entry = results[index]
    url = entry.get("url") or entry.get("webpage_url")

    _active_downloads.add(user_id)
    await query.edit_message_text(t("downloading", lang))

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
            await query.edit_message_text(t("err_download", lang))
            return

        filename = audio_files[0]
        thumb_file = image_files[0] if image_files else None

        if os.path.getsize(filename) > 50 * 1024 * 1024:
            await query.edit_message_text(t("too_large", lang))
            return

        title = info.get("title", "Unknown")
        duration = int(info.get("duration", 0))
        minutes, seconds = divmod(duration, 60)
        platform_label = "🟢 SoundCloud" if entry.get("_platform") == "sc" else "🔴 YouTube"

        await query.edit_message_text(
            f"✅ <b>{title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ {minutes}:{seconds:02d}  ·  {platform_label}\n"
            f"🎤 {info.get('uploader', '—')}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🎧 @muzebot",
            parse_mode="HTML",
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
            msg = t("err_blocked", lang)
        elif "private" in err or "unavailable" in err or "deleted" in err:
            msg = t("err_private", lang)
        elif "age" in err:
            msg = t("err_age", lang)
        elif "copyright" in err or "blocked" in err:
            msg = t("err_copyright", lang)
        else:
            msg = t("err_download", lang)
        await query.edit_message_text(msg)

    except Exception as e:
        logging.error("Unexpected error url=%s: %s", url, e, exc_info=True)
        await query.edit_message_text(t("err_unknown", lang))

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

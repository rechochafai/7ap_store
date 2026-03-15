"""
YouTube Automation Telegram Bot
================================
Workflow:
  1. User sends video + game name
  2. Gemini generates a Thumbnail
  3. AI generates SEO (title + description + tags)
  4. Bot sends everything back for review
  5. User: Edit / Approve / Cancel
  6. If approved → choose from up to 20 channels
  7. Video is uploaded to the chosen channel

Requirements:
    pip install python-telegram-bot google-generativeai google-api-python-client google-auth-oauthlib pillow requests

Setup:
    - Set your TELEGRAM_BOT_TOKEN in the .env or config section below
    - Set your GEMINI_API_KEY
    - Add your YouTube channel OAuth credentials (one per channel)
"""

import os
import logging
import asyncio
import json
import tempfile
from pathlib import Path
from io import BytesIO

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ─── CONFIG ────────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"   # ← replace
GEMINI_API_KEY     = "YOUR_GEMINI_API_KEY"        # ← replace

# List of up to 20 YouTube channels.
# Each entry: {"name": "Channel Display Name", "credentials_file": "path/to/token.json"}
YOUTUBE_CHANNELS = [
    {"name": "Gaming Channel 1",  "credentials_file": "tokens/channel1.json"},
    {"name": "Gaming Channel 2",  "credentials_file": "tokens/channel2.json"},
    # ... add up to 20 channels
]

# ─── CONVERSATION STATES ───────────────────────────────────────────────────────

(
    WAIT_GAME_NAME,
    WAIT_VIDEO,
    REVIEW,
    EDIT_CHOICE,
    EDIT_TITLE,
    EDIT_DESCRIPTION,
    EDIT_TAGS,
    SELECT_CHANNEL,
) = range(8)

# ─── LOGGING ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── GEMINI THUMBNAIL GENERATION ───────────────────────────────────────────────

def generate_thumbnail_with_gemini(game_name: str, video_path: str) -> bytes:
    """
    Uses Gemini to generate a thumbnail image for the video.
    Returns raw PNG bytes.
    """
    try:
        import google.generativeai as genai
        from PIL import Image

        genai.configure(api_key=GEMINI_API_KEY)

        # Upload the video frame or use a prompt-only image generation
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = (
            f"Create a vivid, eye-catching YouTube gaming thumbnail for the game '{game_name}'. "
            "It should have bold text, bright colors, exciting action, and look professional. "
            "Return a description of the ideal thumbnail design."
        )
        response = model.generate_content(prompt)
        description = response.text

        # Since Gemini text models can't directly output images,
        # we create a styled placeholder thumbnail using Pillow.
        # In production, swap this with an image generation API (e.g. Imagen, DALL-E).
        img = _create_placeholder_thumbnail(game_name, description)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    except Exception as e:
        logger.error(f"Thumbnail generation failed: {e}")
        return _create_placeholder_thumbnail(game_name, "").tobytes()


def _create_placeholder_thumbnail(game_name: str, description: str):
    """Creates a simple styled thumbnail using Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (1280, 720), color=(20, 20, 40))
        draw = ImageDraw.Draw(img)

        # Background gradient effect
        for i in range(720):
            r = int(20 + (i / 720) * 60)
            g = int(20 + (i / 720) * 30)
            b = int(40 + (i / 720) * 80)
            draw.line([(0, i), (1280, i)], fill=(r, g, b))

        # Title text
        try:
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 90)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
        except Exception:
            font_large = ImageFont.load_default()
            font_small = font_large

        draw.text((640, 300), game_name.upper(), font=font_large, fill=(255, 220, 50), anchor="mm")
        draw.text((640, 420), "🎮 Gaming Video", font=font_small, fill=(200, 200, 255), anchor="mm")
        draw.text((640, 480), "AUTO-GENERATED THUMBNAIL", font=font_small, fill=(150, 150, 150), anchor="mm")

        return img
    except ImportError:
        from PIL import Image
        return Image.new("RGB", (1280, 720), color=(20, 20, 40))


# ─── SEO GENERATION ────────────────────────────────────────────────────────────

def generate_seo(game_name: str) -> dict:
    """
    Uses Gemini to generate YouTube SEO: title, description, tags.
    Returns {"title": ..., "description": ..., "tags": [...]}
    """
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = f"""
You are a YouTube SEO expert specializing in gaming content.
Generate SEO metadata for a YouTube gaming video about: {game_name}

Respond ONLY in valid JSON with this exact format:
{{
  "title": "Catchy video title (max 100 chars, include game name)",
  "description": "Full YouTube description (300-500 words, include keywords, timestamps placeholder, links placeholder)",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"]
}}
"""
        response = model.generate_content(prompt)
        text = response.text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())

    except Exception as e:
        logger.error(f"SEO generation failed: {e}")
        return {
            "title": f"{game_name} - Epic Gaming Moments! 🎮",
            "description": f"Watch the best moments from {game_name}!\n\n#gaming #{game_name.replace(' ', '')} #gameplay",
            "tags": [game_name, "gaming", "gameplay", "YouTube", "video"],
        }


# ─── YOUTUBE UPLOAD ────────────────────────────────────────────────────────────

def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    thumbnail_bytes: bytes,
    credentials_file: str,
) -> str:
    """
    Uploads video to YouTube using the OAuth credentials for the chosen channel.
    Returns the YouTube video URL.
    """
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(
            credentials_file,
            scopes=["https://www.googleapis.com/auth/youtube.upload"],
        )
        youtube = build("youtube", "v3", credentials=creds)

        # Upload video
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "20",  # Gaming category
            },
            "status": {"privacyStatus": "public"},
        }

        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            _, response = request.next_chunk()

        video_id = response["id"]

        # Set thumbnail
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(thumbnail_bytes)
            tmp_path = tmp.name

        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(tmp_path),
        ).execute()
        os.unlink(tmp_path)

        return f"https://youtu.be/{video_id}"

    except Exception as e:
        logger.error(f"YouTube upload failed: {e}")
        raise


# ─── BOT HANDLERS ──────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *YouTube Automation Bot*\n\n"
        "Send me a gaming video and I'll:\n"
        "🖼 Generate a Thumbnail (Gemini)\n"
        "📝 Generate SEO (title, description, tags)\n"
        "📤 Upload to your chosen YouTube channel\n\n"
        "To begin, type the *name of the game* 🎮",
        parse_mode="Markdown",
    )
    return WAIT_GAME_NAME


async def receive_game_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game_name = update.message.text.strip()
    context.user_data["game_name"] = game_name
    await update.message.reply_text(
        f"🎮 Game: *{game_name}*\n\nNow send me the video file 📹",
        parse_mode="Markdown",
    )
    return WAIT_VIDEO


async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.video and not update.message.document:
        await update.message.reply_text("❌ Please send a video file.")
        return WAIT_VIDEO

    await update.message.reply_text("⏳ Processing your video... please wait.")

    # Download video
    file_obj = update.message.video or update.message.document
    file = await context.bot.get_file(file_obj.file_id)

    tmp_dir = tempfile.mkdtemp()
    video_path = os.path.join(tmp_dir, "video.mp4")
    await file.download_to_drive(video_path)
    context.user_data["video_path"] = video_path

    game_name = context.user_data["game_name"]

    # Generate thumbnail
    await update.message.reply_text("🎨 Generating thumbnail with Gemini...")
    thumbnail_bytes = generate_thumbnail_with_gemini(game_name, video_path)
    context.user_data["thumbnail_bytes"] = thumbnail_bytes

    # Generate SEO
    await update.message.reply_text("🔍 Generating SEO metadata...")
    seo = generate_seo(game_name)
    context.user_data["seo"] = seo

    # Send thumbnail preview
    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=BytesIO(thumbnail_bytes),
        caption="🖼 Generated Thumbnail",
    )

    # Send SEO preview
    tags_preview = ", ".join(seo["tags"][:5]) + ("..." if len(seo["tags"]) > 5 else "")
    seo_text = (
        f"📝 *SEO Preview*\n\n"
        f"*Title:*\n{seo['title']}\n\n"
        f"*Description (preview):*\n{seo['description'][:200]}...\n\n"
        f"*Tags:* {tags_preview}"
    )
    await update.message.reply_text(seo_text, parse_mode="Markdown")

    # Review buttons
    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data="approve"),
            InlineKeyboardButton("✏️ Edit",    callback_data="edit"),
            InlineKeyboardButton("❌ Cancel",  callback_data="cancel"),
        ]
    ]
    await update.message.reply_text(
        "What would you like to do?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return REVIEW


async def review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "cancel":
        await query.edit_message_text("❌ Operation cancelled. Send /start to begin again.")
        return ConversationHandler.END

    if choice == "approve":
        return await ask_channel(update, context)

    if choice == "edit":
        keyboard = [
            [InlineKeyboardButton("📌 Title",       callback_data="edit_title")],
            [InlineKeyboardButton("📄 Description", callback_data="edit_desc")],
            [InlineKeyboardButton("🏷 Tags",         callback_data="edit_tags")],
            [InlineKeyboardButton("✅ Done editing", callback_data="approve")],
        ]
        await query.edit_message_text(
            "What do you want to edit?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return EDIT_CHOICE


async def edit_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "approve":
        return await ask_channel(update, context)
    if choice == "edit_title":
        await query.edit_message_text("✏️ Send the new *title*:", parse_mode="Markdown")
        return EDIT_TITLE
    if choice == "edit_desc":
        await query.edit_message_text("✏️ Send the new *description*:", parse_mode="Markdown")
        return EDIT_DESCRIPTION
    if choice == "edit_tags":
        await query.edit_message_text(
            "✏️ Send the new *tags* separated by commas:", parse_mode="Markdown"
        )
        return EDIT_TAGS


async def receive_edit_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["seo"]["title"] = update.message.text.strip()
    await update.message.reply_text("✅ Title updated!")
    return await send_edit_menu(update, context)


async def receive_edit_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["seo"]["description"] = update.message.text.strip()
    await update.message.reply_text("✅ Description updated!")
    return await send_edit_menu(update, context)


async def receive_edit_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tags = [t.strip() for t in update.message.text.split(",")]
    context.user_data["seo"]["tags"] = tags
    await update.message.reply_text(f"✅ Tags updated: {', '.join(tags)}")
    return await send_edit_menu(update, context)


async def send_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📌 Title",       callback_data="edit_title")],
        [InlineKeyboardButton("📄 Description", callback_data="edit_desc")],
        [InlineKeyboardButton("🏷 Tags",         callback_data="edit_tags")],
        [InlineKeyboardButton("✅ Done editing", callback_data="approve")],
    ]
    await update.message.reply_text(
        "Anything else to edit?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return EDIT_CHOICE


async def ask_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show channel selection keyboard."""
    keyboard = []
    for i, ch in enumerate(YOUTUBE_CHANNELS):
        keyboard.append([InlineKeyboardButton(ch["name"], callback_data=f"channel_{i}")])

    msg_text = "📺 Choose a YouTube channel to upload to:"
    if update.callback_query:
        await update.callback_query.edit_message_text(
            msg_text, reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            msg_text, reply_markup=InlineKeyboardMarkup(keyboard)
        )
    return SELECT_CHANNEL


async def channel_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    channel_index = int(query.data.split("_")[1])
    channel = YOUTUBE_CHANNELS[channel_index]
    context.user_data["channel"] = channel

    await query.edit_message_text(
        f"📤 Uploading to *{channel['name']}*...\nThis may take a few minutes ⏳",
        parse_mode="Markdown",
    )

    seo         = context.user_data["seo"]
    video_path  = context.user_data["video_path"]
    thumbnail   = context.user_data["thumbnail_bytes"]

    try:
        url = upload_to_youtube(
            video_path=video_path,
            title=seo["title"],
            description=seo["description"],
            tags=seo["tags"],
            thumbnail_bytes=thumbnail,
            credentials_file=channel["credentials_file"],
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🎉 *Upload successful!*\n\n📺 Channel: {channel['name']}\n🔗 {url}",
            parse_mode="Markdown",
        )
    except Exception as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Upload failed: {e}\n\nCheck your YouTube credentials.",
        )

    # Cleanup
    try:
        import shutil
        shutil.rmtree(os.path.dirname(video_path), ignore_errors=True)
    except Exception:
        pass

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled. Use /start to begin again.")
    return ConversationHandler.END


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAIT_GAME_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_game_name)],
            WAIT_VIDEO:      [MessageHandler(filters.VIDEO | filters.Document.ALL, receive_video)],
            REVIEW:          [CallbackQueryHandler(review_callback)],
            EDIT_CHOICE:     [CallbackQueryHandler(edit_choice_callback)],
            EDIT_TITLE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_title)],
            EDIT_DESCRIPTION:[MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_description)],
            EDIT_TAGS:       [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_tags)],
            SELECT_CHANNEL:  [CallbackQueryHandler(channel_selected_callback)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)

    logger.info("🤖 Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()

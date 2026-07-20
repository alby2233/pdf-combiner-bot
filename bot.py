import os
import shutil
import tempfile
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv
import google.generativeai as genai

# Import our utility functions
from pdf_utils import (
    word_to_pdf, pdf_to_word,
    ppt_to_pdf, pdf_to_ppt,
    excel_to_pdf, pdf_to_excel,
    add_header_footer_page_numbers,
    merge_pdfs, split_pdf, rotate_pdf,
    ppt_to_images, pdf_to_images, images_to_pdf
)
from image_utils import rotate_image, resize_image, compress_image, convert_image_format, grayscale_image

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PROXY_URL = os.getenv("PROXY_URL")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

CURRENT_IMAGE_MODEL = "black-forest-labs/flux-1.1-pro"
CURRENT_EDIT_MODEL = "timothybrooks/instruct-pix2pix"

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)



# In-memory user sessions tracking: key=(chat_id, user_id), value=dict
USER_SESSIONS = {}
GROUP_ACTIVE_USERS = {}

def register_active_group_user(update: Update):
    if not update or not update.effective_chat or not update.effective_user:
        return
    is_group = update.effective_chat.type in ["group", "supergroup"]
    if not is_group:
        return
        
    chat_id = update.effective_chat.id
    user = update.effective_user
    if user.is_bot:
        return
        
    name = user.first_name
    username = f"@{user.username}" if user.username else name
    user_entry = {"id": user.id, "name": name, "username": username}
    
    if chat_id not in GROUP_ACTIVE_USERS:
        GROUP_ACTIVE_USERS[chat_id] = []
        
    GROUP_ACTIVE_USERS[chat_id] = [u for u in GROUP_ACTIVE_USERS[chat_id] if u["id"] != user.id]
    GROUP_ACTIVE_USERS[chat_id].append(user_entry)
    
    if len(GROUP_ACTIVE_USERS[chat_id]) > 30:
        GROUP_ACTIVE_USERS[chat_id].pop(0)

def get_session(chat_id, user_id):
    key = (chat_id, user_id)
    if key not in USER_SESSIONS:
        USER_SESSIONS[key] = {
            "chat_id": chat_id,
            "user_id": user_id,
            "action": None,          # Current running action (e.g., 'merge', 'word2pdf')
            "files": [],             # List of absolute downloaded file paths
            "temp_dir": None,        # Path to session's temp folder
            "config_step": None,     # Layout config step: 'ask_layout', 'ask_exclude_first', 'ask_header', 'ask_footer', 'ask_start_num'
            "config": {
                "header_text": None,
                "footer_text": None,
                "add_page_numbers": False,
                "exclude_first_page": False,
                "start_page_num": 1,
            },
            "split_range": None,     # String storage for split page ranges
            "rotation_angle": None,  # Int storage for rotation angle (90, 180, 270)
        }
    return USER_SESSIONS[key]

def clear_session(chat_id, user_id):
    key = (chat_id, user_id)
    if key in USER_SESSIONS:
        session = USER_SESSIONS[key]
        if session["temp_dir"] and os.path.exists(session["temp_dir"]):
            try:
                shutil.rmtree(session["temp_dir"])
            except Exception as e:
                logger.error(f"Error cleaning temp dir: {e}")
        del USER_SESSIONS[key]

# --- Menus ---

def get_main_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📂 PDF Utilities", callback_data="menu:pdf"),
            InlineKeyboardButton("🔄 Office Conversions", callback_data="menu:office"),
        ],
        [
            InlineKeyboardButton("🖼️ Image Utilities", callback_data="menu:image_utils"),
            InlineKeyboardButton("❌ Cancel Operation", callback_data="btn:cancel")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_image_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🔄 Rotate Image", callback_data="action:img_rotate"),
            InlineKeyboardButton("📐 Resize Image", callback_data="action:img_resize"),
        ],
        [
            InlineKeyboardButton("📉 Compress Image", callback_data="action:img_compress"),
            InlineKeyboardButton("🔄 Convert Format", callback_data="action:img_convert"),
        ],
        [
            InlineKeyboardButton("🎨 Grayscale Filter", callback_data="action:img_grayscale"),
        ],
        [
            InlineKeyboardButton("🎞️ Video to GIF", callback_data="action:video2gif"),
            InlineKeyboardButton("🖼️ Images to GIF", callback_data="action:images2gif"),
        ],
        [
            InlineKeyboardButton("« Back to Main Menu", callback_data="menu:main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)



def get_pdf_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🔗 Merge PDFs", callback_data="action:merge"),
            InlineKeyboardButton("✂️ Split PDF", callback_data="action:split"),
        ],
        [
            InlineKeyboardButton("🔄 Rotate PDF", callback_data="action:rotate"),
            InlineKeyboardButton("⚙️ Add Layout Settings", callback_data="action:layout_settings"),
        ],
        [
            InlineKeyboardButton("📉 Compress PDF", callback_data="action:pdf_compress"),
        ],
        [
            InlineKeyboardButton("✍️ Watermark PDF", callback_data="action:pdf_watermark"),
            InlineKeyboardButton("🧼 Remove Watermark", callback_data="action:pdf_rem_watermark"),
        ],
        [
            InlineKeyboardButton("🔒 Lock PDF", callback_data="action:pdf_encrypt"),
            InlineKeyboardButton("🔓 Unlock PDF", callback_data="action:pdf_decrypt"),
        ],
        [
            InlineKeyboardButton("« Back to Main Menu", callback_data="menu:main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_office_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📝 Word ➔ PDF", callback_data="action:word2pdf"),
            InlineKeyboardButton("📥 PDF ➔ Word", callback_data="action:pdf2word"),
        ],
        [
            InlineKeyboardButton("📊 PPT ➔ PDF", callback_data="action:ppt2pdf"),
            InlineKeyboardButton("📥 PDF ➔ PPT", callback_data="action:pdf2ppt"),
        ],
        [
            InlineKeyboardButton("📈 Excel ➔ PDF", callback_data="action:excel2pdf"),
            InlineKeyboardButton("📥 PDF ➔ Excel", callback_data="action:pdf2excel"),
        ],
        [
            InlineKeyboardButton("🖼️ PPT ➔ Images", callback_data="action:ppt2images"),
            InlineKeyboardButton("🖼️ PDF ➔ Images", callback_data="action:pdf2images"),
        ],
        [
            InlineKeyboardButton("➕ Images ➔ PDF", callback_data="action:images2pdf"),
            InlineKeyboardButton("📊 Excel Chart", callback_data="action:excel_chart"),
        ],
        [
            InlineKeyboardButton("« Back to Main Menu", callback_data="menu:main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Bot Commands ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    clear_session(chat_id, user_id) # Reset any active session
    
    welcome_text = (
        "👋 **Welcome to the PDF & Office Converter Bot!**\n\n"
        "Here you can perform watermark-free document conversions and layout edits.\n\n"
        "Please select a category below:"
    )
    await update.message.reply_text(welcome_text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    clear_session(chat_id, user_id)
    
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.message.reply_text(
            "🎨 **Generate Image**\n\n"
            "Please provide a prompt after the command, for example:\n"
            "`/generate a futuristic city at sunset, highly detailed`",
            parse_mode="Markdown"
        )
        return
        
    msg = await update.message.reply_text("⏳ Initializing AI Image Engine...")
    await generate_image_with_replicate(chat_id, prompt, msg, context)

async def set_model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    clear_session(chat_id, user_id)
    
    prompt = (
        "⚙️ **Select AI Models**\n\n"
        f"• **Current Image Gen Model**: `{CURRENT_IMAGE_MODEL}`\n"
        f"• **Current Image Edit Model**: `{CURRENT_EDIT_MODEL}`\n\n"
        "Choose a model category to customize:"
    )
    keyboard = [
        [
            InlineKeyboardButton("🎨 Text-to-Image Models", callback_data="set_model_cat:gen"),
        ],
        [
            InlineKeyboardButton("🖼️ Image-to-Image / Edit Models", callback_data="set_model_cat:edit"),
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="btn:cancel"),
        ]
    ]
    await update.message.reply_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = context.bot.username or "slow_gokubot"
    help_text = (
        "💡 **PDF & Office Bot Help**\n\n"
        "Here are all the direct commands you can run:\n\n"
        "📂 **PDF Utilities**:\n"
        "• `/merge` - Combine multiple PDF files into one\n"
        "• `/split` - Extract specific page ranges from a PDF\n"
        "• `/rotate` - Rotate pages of a PDF document\n"
        "• `/layout` - Add custom Header, Footer, and Page Numbers\n"
        "• `/compress` - Compress PDF file size (Low/Medium/High)\n"
        "• `/lock` - Password protect a PDF file\n"
        "• `/unlock` - Remove password from a PDF\n"
        "• `/watermark` - Add a transparent watermark to a PDF\n"
        "• `/rem_watermark` - Remove a text watermark from a PDF\n\n"
        "🔄 **Office Conversions (Watermark-Free)**:\n"
        "• `/word_to_pdf` - Convert Word to PDF\n"
        "• `/pdf_to_word` - Convert PDF to Word\n"
        "• `/ppt_to_pdf` - Convert PowerPoint to PDF\n"
        "• `/pdf_to_ppt` - Convert PDF to PowerPoint\n"
        "• `/excel_to_pdf` - Convert Excel to PDF\n"
        "• `/pdf_to_excel` - Convert PDF to Excel\n"
        "• `/chart` - Generate Bar/Line/Pie charts from Excel/CSV\n"
        "• `/seminar <topic>` - Generate full Seminar PPT presentation & Word Report\n"
        "• `/website <prompt>` - Antigravity AI: Build interactive HTML5 web app / page\n\n"
        "🖼️ **Image & GIF Utilities**:\n"
        "• `/images_to_pdf` - Combine photos into a single PDF\n"
        "• `/pdf_to_images` - Export PDF pages as a ZIP of images\n"
        "• `/ppt_to_images` - Export PPT slides as a ZIP of images\n"
        "• `/img_rotate` - Rotate a photo clockwise (90, 180, 270)\n"
        "• `/img_resize` - Scale a photo or set custom width\n"
        "• `/img_compress` - Reduce file size of a photo\n"
        "• `/img_convert` - Convert format (JPG ➔ PNG / PNG ➔ JPG)\n"
        "• `/img_grayscale` - Apply a black & white filter to a photo\n"
        "• `/video_to_gif` - Convert a video file into an animated GIF\n"
        "• `/images_to_gif` - Combine multiple photos into a GIF\n"
        "• `/ocr` - Extract text from a textbook page or image scan\n\n"
        "🎨 **AI Image Generation & Editing (Replicate)**:\n"
        "• `/generate <prompt>` - Generate a new image from scratch\n"
        "• `/set_model` - Select active generation/editing model dynamically\n"
        "• **Prompt Editing**: Reply to any photo (or upload with caption) and mention the bot with an edit instruction (e.g. @" + bot_username + " blur background)\n"
        "• `/avatar` - Stylize portrait face into Claymation, Pixel Art, 3D, etc.\n"
        "• `/upscale` - Upscale and enhance low-res photo to high-res 4K\n"
        "• `/meme Top Text | Bottom Text` - Overlay text on image to make a meme\n\n"
        "🎲 **Group Games & Social Tools**:\n"
        "• `/download <link>` - Download videos from YouTube, TikTok, Reels, etc.\n"
        "• `/music <prompt>` - Generate 10s custom AI lofi/music beats from text\n"
        "• `/tts <text>` - Convert text to voice note/speech using Suno Bark\n"
        "• `/choose <options>` - Randomly pick an option from a list (or pick active group member)\n"
        "• `/members` - View current pool of active group members\n"
        "• `/trivia` - Start a Gemini AI-powered quiz poll in the group\n\n"
        "🤖 **Google Gemini & Antigravity AI**:\n"
        "• `/code <snippet>` - Audit code, debug error stack traces & optimize logic\n"
        "• `/summarize <URL>` - Read webpage / article & extract key executive takeaways\n"
        "• Direct DM: Send any text message to chat directly.\n"
        "• Group Chats: Mention the bot (e.g. @" + bot_username + " question) or reply to any bot message.\n\n"
        "❌ **Control**:\n"
        "• Use `/cancel` at any time to abort the current operation."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    clear_session(chat_id, user_id)
    await update.message.reply_text("❌ Current operation has been cancelled. Use /start to open the dashboard again.")

async def meme_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message = update.message
    
    # 1. Parse texts
    args_str = " ".join(context.args) if context.args else ""
    if not args_str and message.caption and message.caption.startswith("/meme"):
        # Strip command
        caption_parts = message.caption.split()
        if len(caption_parts) > 1:
            args_str = message.caption.replace(caption_parts[0], "", 1).strip()
        
    if not args_str:
        await message.reply_text(
            "⚠️ **Meme Generator Usage**:\n\n"
            "• Reply to any photo with: `/meme Top Text | Bottom Text`\n"
            "• Or upload a photo with caption: `/meme Top Text | Bottom Text`\n\n"
            "Use the `|` symbol to separate top and bottom captions.",
            parse_mode="Markdown"
        )
        return
        
    # Split top and bottom
    parts = args_str.split("|")
    top_text = parts[0].strip()
    bottom_text = parts[1].strip() if len(parts) > 1 else ""
    
    # 2. Get photo source
    photo_file = None
    if message.reply_to_message:
        reply = message.reply_to_message
        if reply.photo:
            photo_file = reply.photo[-1]
        elif reply.document and is_doc_image(reply.document):
            photo_file = reply.document
    elif message.photo:
        photo_file = message.photo[-1]
    elif message.document and is_doc_image(message.document):
        photo_file = message.document
        
    if not photo_file:
        await message.reply_text("⚠️ Please reply to a photo message, or upload a photo with this command to generate a meme.")
        return
        
    status_msg = await message.reply_text("⏳ Generating meme...")
    try:
        temp_dir = tempfile.mkdtemp()
        file_name = "src_photo.jpg"
        src_path = os.path.join(temp_dir, file_name)
        out_path = os.path.join(temp_dir, "meme_output.jpg")
        
        # Download photo
        new_file = await context.bot.get_file(photo_file.file_id)
        await new_file.download_to_drive(src_path)
        
        # Generate meme
        from meme_utils import generate_meme
        generate_meme(src_path, top_text, bottom_text, out_path)
        
        # Send meme back
        await message.reply_chat_action("upload_photo")
        with open(out_path, "rb") as f:
            await message.reply_photo(f, caption="🎭 Here is your meme!")
            
        await status_msg.delete()
        
        # Clean up temp
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Meme generation error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error generating meme: {str(e)}")

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not context.args:
        await message.reply_text(
            "⚠️ **Social Downloader Usage**:\n\n"
            "• `/download <URL>` or `/dl <URL>`\n\n"
            "Supports: YouTube, TikTok, Instagram Reels, Twitter, and more!",
            parse_mode="Markdown"
        )
        return
        
    url = context.args[0].strip()
    status_msg = await message.reply_text("⏳ Analyzing video link and starting download...")
    
    try:
        import yt_dlp
        import tempfile
        import shutil
        import asyncio
        
        temp_dir = tempfile.mkdtemp()
        
        # yt-dlp options
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, 'video.%(ext)s'),
            'format': 'best[filesize<48M]/bestvideo[filesize<40M]+bestaudio[filesize<8M]/best',
            'merge_output_format': 'mp4',
            'nooverwrites': True,
            'max_filesize': 49 * 1024 * 1024,
            'quiet': True,
            'noprogress': True,
        }
        
        # Run yt-dlp in executor to not block async loop
        def run_ydl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                base_without_ext = os.path.splitext(filename)[0]
                possible_files = [filename, base_without_ext + ".mp4", base_without_ext + ".mkv"]
                for pf in possible_files:
                    if os.path.exists(pf):
                        return pf, info.get("title", "Video")
                return None, None

        loop = asyncio.get_event_loop()
        file_path, video_title = await loop.run_in_executor(None, run_ydl)
        
        if not file_path or not os.path.exists(file_path):
            raise Exception("Could not retrieve downloaded file. File might be too large (>50MB) or format is unsupported.")
            
        await status_msg.edit_text("📤 Uploading video to Telegram...")
        
        # Send as video if it has standard video formats, else as document
        ext = os.path.splitext(file_path)[1].lower()
        await message.reply_chat_action("upload_video")
        
        with open(file_path, "rb") as f:
            if ext in [".mp4", ".mov", ".m4v"]:
                await message.reply_video(f, caption=f"📹 **{video_title}**", parse_mode="Markdown")
            else:
                await message.reply_document(f, filename=os.path.basename(file_path), caption=f"📄 **{video_title}**", parse_mode="Markdown")
                
        await status_msg.delete()
        
        # Clean up temp
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass
            
    except Exception as e:
        logger.error(f"Download error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error downloading video:\n`{str(e)}`", parse_mode="Markdown")

async def choose_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    chat_id = update.effective_chat.id
    is_group = update.effective_chat.type in ["group", "supergroup"]
    
    input_text = " ".join(context.args) if context.args else ""
    
    if not input_text and is_group:
        active_list = GROUP_ACTIVE_USERS.get(chat_id, [])
        if active_list:
            import random
            import asyncio
            selected_user = random.choice(active_list)
            pool_str = ", ".join([u["name"] for u in active_list])
            suspense_msg = await message.reply_text("🎲 **Picking randomly from active chat members...** 🎲")
            await asyncio.sleep(1.0)
            
            mention_name = selected_user["username"] if selected_user["username"].startswith("@") else selected_user["name"]
            await suspense_msg.edit_text(
                f"🔮 **I choose:** {mention_name}\n\n"
                f"👥 *Pool (active members)*: {pool_str}",
                parse_mode="Markdown"
            )
            return
        else:
            await message.reply_text(
                "🎲 **Group Decision Maker**\n\n"
                "I haven't recorded any active members in this chat yet! "
                "Once people send a few text/media messages, I will be able to pick from them automatically.\n\n"
                "💡 Alternatively, specify options manually:\n"
                "`/choose Alice, Bob, Charlie`",
                parse_mode="Markdown"
            )
            return
            
    if "," in input_text:
        options = [opt.strip() for opt in input_text.split(",") if opt.strip()]
    else:
        options = [opt.strip() for opt in input_text.split() if opt.strip()]
        
    if not options:
        await message.reply_text(
            "⚠️ **Group Decision Maker Usage**:\n\n"
            "• `/choose option1, option2, option3`\n"
            "• `/choose option1 option2 option3`\n\n"
            "The bot will randomly select one of your choices!",
            parse_mode="Markdown"
        )
        return
        
    import random
    import asyncio
    selected = random.choice(options)
    suspense_msg = await message.reply_text("🤔 Selecting a choice... 🎲")
    await asyncio.sleep(1.0)
    await suspense_msg.edit_text(f"🔮 **I choose:** `{selected}`", parse_mode="Markdown")

async def active_members_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    is_group = update.effective_chat.type in ["group", "supergroup"]
    
    if not is_group:
        await update.message.reply_text("⚠️ This command is only usable inside group chats.")
        return
        
    active_list = GROUP_ACTIVE_USERS.get(chat_id, [])
    if not active_list:
        await update.message.reply_text("👥 No active members recorded in this chat yet. Send some messages to build the pool!")
        return
        
    lines = [f"• {u['name']} ({u['username']})" for u in active_list]
    await update.message.reply_text(
        f"👥 **Active Group Members (Decision Pool)**:\n\n" + "\n".join(lines) + 
        f"\n\n💬 *Total Pool Size*: `{len(active_list)}`\n"
        "💡 *Tip*: Run `/choose` without any parameters to randomly pick one of these members!",
        parse_mode="Markdown"
    )

async def trivia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message = update.message
    
    if not GEMINI_API_KEY:
        await message.reply_text("⚠️ Google Gemini AI is not configured. Trivia command is unavailable.")
        return
        
    status_msg = await message.reply_text("🎲 Generating a fun trivia question using Gemini AI...")
    await update.message.reply_chat_action("typing")
    
    try:
        import json
        import asyncio
        
        prompt = (
            "Generate a single multiple-choice trivia question for a fun group game. "
            "The question must be interesting, have exactly 4 options, and have exactly one correct option. "
            "Respond ONLY with a valid JSON object. Do not include markdown code block syntax (like ```json). "
            "JSON structure MUST be exactly:\n"
            "{\n"
            "  \"question\": \"The question text\",\n"
            "  \"options\": [\"Option A\", \"Option B\", \"Option C\", \"Option D\"],\n"
            "  \"correct_option_index\": 0\n"
            "}\n"
            "Ensure correct_option_index is a number from 0 to 3."
        )
        
        model = genai.GenerativeModel(GEMINI_MODEL)
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: model.generate_content(prompt)
        )
        
        resp_text = response.text.strip()
        if resp_text.startswith("```"):
            lines = resp_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            resp_text = "\n".join(lines).strip()
            
        data = json.loads(resp_text)
        
        question = data["question"]
        options = data["options"]
        correct_index = int(data["correct_option_index"])
        
        if len(options) != 4 or not (0 <= correct_index <= 3):
            raise Exception("Invalid trivia formatting returned by AI.")
            
        await status_msg.delete()
        
        await context.bot.send_poll(
            chat_id=chat_id,
            question=question,
            options=options,
            type="quiz",
            correct_option_id=correct_index,
            is_anonymous=False
        )
    except Exception as e:
        logger.error(f"Trivia error: {e}")
        await status_msg.edit_text(f"❌ Error generating trivia: {str(e)}")

async def ocr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message = update.message
    
    # Check if we have a photo source
    photo_file = None
    if message.reply_to_message:
        reply = message.reply_to_message
        if reply.photo:
            photo_file = reply.photo[-1]
        elif reply.document and is_doc_image(reply.document):
            photo_file = reply.document
    elif message.photo:
        photo_file = message.photo[-1]
    elif message.document and is_doc_image(message.document):
        photo_file = message.document
        
    if not photo_file:
        await message.reply_text(
            "⚠️ **OCR Text Extractor Usage**:\n\n"
            "• Reply to any photo/image with: `/ocr`\n"
            "• Or upload a photo/image with the caption: `/ocr`",
            parse_mode="Markdown"
        )
        return
        
    if not GEMINI_API_KEY:
        await message.reply_text(
            "⚠️ Google Gemini AI features are not configured on this bot.\n\n"
            "Please add your `GEMINI_API_KEY` to the `.env` file to enable OCR."
        )
        return
        
    status_msg = await message.reply_text("⏳ Extracting text from image via Gemini AI...")
    try:
        temp_dir = tempfile.mkdtemp()
        file_name = "ocr_src.jpg"
        local_path = os.path.join(temp_dir, file_name)
        
        # Download photo
        new_file = await context.bot.get_file(photo_file.file_id)
        await new_file.download_to_drive(local_path)
        
        # Extract text via Gemini multimodal interface
        from PIL import Image
        img = Image.open(local_path)
        
        model = genai.GenerativeModel(GEMINI_MODEL)
        import asyncio
        loop = asyncio.get_running_loop()
        
        # Run blocking API call in executor
        response = await loop.run_in_executor(
            None, 
            lambda: model.generate_content([
                "Please extract all readable text from this image. Keep the original formatting as much as possible. Output only the extracted text.", 
                img
            ])
        )
        
        extracted_text = response.text.strip()
        if not extracted_text:
            await status_msg.edit_text("ℹ️ Gemini AI could not identify any readable text in this image.")
        else:
            # If text is too long (Telegram limit is 4096), send it as a file, otherwise as a message
            if len(extracted_text) > 3500:
                txt_file_path = os.path.join(temp_dir, "extracted_text.txt")
                with open(txt_file_path, "w", encoding="utf-8") as f:
                    f.write(extracted_text)
                await status_msg.edit_text("📤 Extracted text is quite long, sending as a text file...")
                with open(txt_file_path, "rb") as f:
                    await context.bot.send_document(chat_id, f, filename="extracted_text.txt", caption="📄 Extracted Text")
            else:
                await status_msg.edit_text(
                    f"📝 **Extracted Text**:\n\n```\n{extracted_text}\n```",
                    parse_mode="Markdown"
                )
                
        # Clean up files
        try:
            img.close()
            os.remove(local_path)
            os.rmdir(temp_dir)
        except Exception:
            pass
            
    except Exception as e:
        logger.error(f"OCR execution error: {e}")
        await status_msg.edit_text(f"❌ Error during OCR extraction: {str(e)}")

async def pil_upscale_fallback(chat_id, local_path, status_msg, context):
    try:
        await status_msg.edit_text("⏳ Upscaling image using High-Resolution Lanczos & Sharpening Engine...")
        from PIL import Image, ImageEnhance
        import asyncio
        loop = asyncio.get_running_loop()
        temp_dir = tempfile.mkdtemp()
        out_path = os.path.join(temp_dir, "upscaled_4k.png")
        
        def process_image():
            with Image.open(local_path) as img:
                img = img.convert("RGB")
                w, h = img.size
                new_w, new_h = w * 4, h * 4
                upscaled = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                enhanced = ImageEnhance.Sharpness(upscaled).enhance(1.5)
                enhanced.save(out_path, "PNG", quality=95)
                
        await loop.run_in_executor(None, process_image)
        
        await status_msg.edit_text("📤 Sending 4K upscaled image back to Telegram...")
        with open(out_path, "rb") as f_send:
            await context.bot.send_document(
                chat_id,
                f_send,
                filename="upscaled_image_4k.png",
                caption="✅ **4K Upscaled Image**\nEnhanced 4X resolution via Lanczos & Sharpness processing.",
                parse_mode="Markdown"
            )
        await status_msg.delete()
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as e:
        logger.error(f"PIL upscale fallback error: {e}")
        await status_msg.edit_text(f"❌ Error upscaling image: {str(e)}")

async def upscale_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message = update.message
    
    photo_file = None
    if message.reply_to_message:
        reply = message.reply_to_message
        if reply.photo:
            photo_file = reply.photo[-1]
        elif reply.document and is_doc_image(reply.document):
            photo_file = reply.document
    elif message.photo:
        photo_file = message.photo[-1]
    elif message.document and is_doc_image(message.document):
        photo_file = message.document
        
    if not photo_file:
        await message.reply_text(
            "⚠️ **AI Image Upscaler Usage**:\n\n"
            "• Reply to any photo with: `/upscale`\n"
            "• Or upload a photo with the caption: `/upscale`",
            parse_mode="Markdown"
        )
        return
        
    status_msg = await message.reply_text("⏳ Downloading source image for upscaling...")
    try:
        import base64
        import httpx
        import asyncio
        
        new_file = await context.bot.get_file(photo_file.file_id)
        temp_dir = tempfile.mkdtemp()
        local_path = os.path.join(temp_dir, "upscale_src.jpg")
        await new_file.download_to_drive(local_path)
        
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
        token = os.getenv("REPLICATE_API_TOKEN", "").strip()
        if not token:
            await pil_upscale_fallback(chat_id, local_path, status_msg, context)
            return
            
        with open(local_path, "rb") as f:
            encoded_data = base64.b64encode(f.read()).decode("utf-8")
        data_uri = f"data:image/jpeg;base64,{encoded_data}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        req_url = "https://api.replicate.com/v1/predictions"
        payload = {
            "version": "b3ef194191d13140337468c916c2c5b96dd0cb06dffc032a022a31807f6a5ea8",
            "input": {
                "image": data_uri,
                "scale": 4,
                "face_enhance": True
            }
        }
        
        await status_msg.edit_text("🚀 Running 4K Upscaler Engine...")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(req_url, json=payload, headers=headers)
            if res.status_code != 201:
                logger.warning(f"Replicate API status {res.status_code}, switching to PIL upscale fallback")
                await pil_upscale_fallback(chat_id, local_path, status_msg, context)
                return
                
            prediction = res.json()
            poll_url = prediction["urls"]["get"]
            
            for _ in range(40):
                await asyncio.sleep(2.0)
                poll_res = await client.get(poll_url, headers=headers)
                if poll_res.status_code != 200:
                    continue
                    
                prediction = poll_res.json()
                status = prediction["status"]
                
                if status == "succeeded":
                    output_url = prediction.get("output")
                    if not output_url:
                        await status_msg.edit_text("❌ No upscaled image received from Replicate.")
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        return
                        
                    await status_msg.edit_text("📥 Downloading 4K upscaled image...")
                    img_res = await client.get(output_url)
                    if img_res.status_code != 200:
                        await status_msg.edit_text("❌ Error downloading upscaled image.")
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        return
                        
                    out_filename = "upscaled_image_4k.png"
                    out_path = os.path.join(temp_dir, out_filename)
                    with open(out_path, "wb") as f_out:
                        f_out.write(img_res.content)
                        
                    await status_msg.edit_text("📤 Sending 4K image back to Telegram...")
                    with open(out_path, "rb") as f_send:
                        await context.bot.send_document(
                            chat_id, 
                            f_send, 
                            filename=out_filename,
                            caption="✅ **4K Upscaled & Enhanced Image**\nEnhanced using Real-ESRGAN and GFPGAN face reconstruction.",
                            parse_mode="Markdown"
                        )
                    await status_msg.delete()
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return
                elif status == "failed":
                    await status_msg.edit_text(f"❌ Upscaling failed: {prediction.get('error', 'unknown error')}")
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return
                elif status == "canceled":
                    await status_msg.edit_text("❌ Upscaling was canceled.")
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return
                    
            await status_msg.edit_text("⏱️ Upscaling timed out on Replicate.")
            shutil.rmtree(temp_dir, ignore_errors=True)
            
    except Exception as e:
        logger.error(f"Upscaler error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error during upscaling: {str(e)}")

async def gtts_fallback(update, context, text, status_msg):
    try:
        await status_msg.edit_text("⏳ Synthesizing voice note...")
        from gtts import gTTS
        import asyncio
        loop = asyncio.get_running_loop()
        temp_dir = tempfile.mkdtemp()
        out_path = os.path.join(temp_dir, "voice_note.mp3")
        
        def synthesize():
            tts = gTTS(text=text, lang="en")
            tts.save(out_path)
            
        await loop.run_in_executor(None, synthesize)
        
        await status_msg.edit_text("📤 Sending voice note to Telegram...")
        with open(out_path, "rb") as f_send:
            await context.bot.send_voice(
                update.effective_chat.id,
                f_send,
                caption=f"🗣️ **Voice note generated for**: \"_{text[:60]}..._\"",
                parse_mode="Markdown"
            )
        await status_msg.delete()
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as e:
        logger.error(f"gTTS fallback error: {e}")
        await status_msg.edit_text(f"❌ Error generating voice note: {str(e)}")

async def tts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message = update.message
    
    args_str = " ".join(context.args) if context.args else ""
    if not args_str and message.reply_to_message and message.reply_to_message.text:
        args_str = message.reply_to_message.text
        
    if not args_str:
        await message.reply_text(
            "⚠️ **AI Text-to-Speech Usage**:\n\n"
            "• `/tts Hello, welcome to our college group!`\n"
            "• Or reply to any text message with `/tts` to speak it.",
            parse_mode="Markdown"
        )
        return
        
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
    token = os.getenv("REPLICATE_API_TOKEN", "").strip()
    if not token:
        await gtts_fallback(update, context, args_str, await message.reply_text("⏳ Initializing TTS..."))
        return
        
    status_msg = await message.reply_text("⏳ Synthesizing voice note...")
    try:
        import httpx
        import asyncio
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        req_url = "https://api.replicate.com/v1/predictions"
        payload = {
            "version": "b76242b40d67c76ab6742e987628a2a9ac019e11d56ab96c4e91ce03b79b2787",
            "input": {
                "prompt": args_str,
                "text_temp": 0.7
            }
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(req_url, json=payload, headers=headers)
            if res.status_code != 201:
                logger.warning(f"Replicate API status {res.status_code}, switching to gTTS fallback")
                await gtts_fallback(update, context, args_str, status_msg)
                return
                
            prediction = res.json()
            poll_url = prediction["urls"]["get"]
            
            for _ in range(40):
                await asyncio.sleep(2.0)
                poll_res = await client.get(poll_url, headers=headers)
                if poll_res.status_code != 200:
                    continue
                    
                prediction = poll_res.json()
                status = prediction["status"]
                
                if status == "succeeded":
                    output_url = prediction.get("output")
                    if not output_url:
                        await status_msg.edit_text("❌ No audio output received from Bark.")
                        return
                        
                    if isinstance(output_url, dict):
                        audio_url = output_url.get("audio")
                    elif isinstance(output_url, list):
                        audio_url = output_url[0]
                    else:
                        audio_url = output_url
                        
                    if not audio_url:
                        await status_msg.edit_text("❌ No audio URL found in response.")
                        return
                        
                    await status_msg.edit_text("📥 Downloading synthesized voice note...")
                    audio_res = await client.get(audio_url)
                    if audio_res.status_code != 200:
                        await status_msg.edit_text("❌ Error downloading voice file.")
                        return
                        
                    temp_dir = tempfile.mkdtemp()
                    out_filename = "voice_note.wav"
                    out_path = os.path.join(temp_dir, out_filename)
                    with open(out_path, "wb") as f_out:
                        f_out.write(audio_res.content)
                        
                    await status_msg.edit_text("📤 Sending voice note to Telegram...")
                    with open(out_path, "rb") as f_send:
                        await context.bot.send_voice(
                            chat_id, 
                            f_send, 
                            caption=f"🗣️ **Voice note generated for**: \"_{args_str[:60]}..._\"",
                            parse_mode="Markdown"
                        )
                    await status_msg.delete()
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return
                elif status == "failed":
                    await gtts_fallback(update, context, args_str, status_msg)
                    return
                elif status == "canceled":
                    await gtts_fallback(update, context, args_str, status_msg)
                    return
                    
            await gtts_fallback(update, context, args_str, status_msg)
    except Exception as e:
        logger.error(f"TTS error: {e}, switching to gTTS fallback", exc_info=True)
        await gtts_fallback(update, context, args_str, status_msg)

async def music_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message = update.message
    
    args_str = " ".join(context.args) if context.args else ""
    if not args_str and message.caption and (message.caption.startswith("/music") or message.caption.startswith("/generate_music")):
        caption_parts = message.caption.split()
        if len(caption_parts) > 1:
            args_str = message.caption.replace(caption_parts[0], "", 1).strip()
            
    if not args_str:
        await message.reply_text(
            "⚠️ **AI Music Generator Usage**:\n\n"
            "• `/music lofi chill study beats`\n"
            "• `/music energetic rock guitar riff`\n"
            "• `/music ambient synth space wave`",
            parse_mode="Markdown"
        )
        return
        
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
    token = os.getenv("REPLICATE_API_TOKEN", "").strip()
    if not token:
        await message.reply_text(
            "⚠️ **Replicate API Token is not configured!**\n\n"
            "Please configure `REPLICATE_API_TOKEN` in your `.env` file to generate music."
        )
        return
        
    status_msg = await message.reply_text(f"⏳ Generating 10s of music for: `{args_str}`...")
    try:
        import httpx
        import asyncio
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        req_url = "https://api.replicate.com/v1/predictions"
        payload = {
            "version": "671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb",
            "input": {
                "prompt": args_str,
                "duration": 10,
                "model_version": "melody"
            }
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(req_url, json=payload, headers=headers)
            if res.status_code != 201:
                logger.warning(f"Replicate API status {res.status_code} on music command")
                await status_msg.edit_text(
                    "🎵 **AI Music Generation Note**:\n\n"
                    "AI Music synthesis (`/music`) requires an active Replicate API key with billing enabled.\n\n"
                    "💡 *Try these 100% FREE unlimited AI features instead*:\n"
                    "• `/generate <prompt>` - Free Unlimited AI Art\n"
                    "• `/tts <text>` - Free Unlimited Voice Notes\n"
                    "• `/website <topic>` - Free Web App Creator\n"
                    "• `/code <snippet>` - Free AI Code Auditor",
                    parse_mode="Markdown"
                )
                return
                
            prediction = res.json()
            poll_url = prediction["urls"]["get"]
            
            for _ in range(40):
                await asyncio.sleep(2.0)
                poll_res = await client.get(poll_url, headers=headers)
                if poll_res.status_code != 200:
                    continue
                    
                prediction = poll_res.json()
                status = prediction["status"]
                
                if status == "succeeded":
                    output_url = prediction.get("output")
                    if not output_url:
                        await status_msg.edit_text("❌ No music output received from Replicate.")
                        return
                        
                    await status_msg.edit_text("📤 Downloading music track...")
                    track_res = await client.get(output_url)
                    if track_res.status_code != 200:
                        await status_msg.edit_text("❌ Error downloading generated music file.")
                        return
                        
                    temp_dir = tempfile.mkdtemp()
                    out_filename = "music_track.wav"
                    out_path = os.path.join(temp_dir, out_filename)
                    with open(out_path, "wb") as f_out:
                        f_out.write(track_res.content)
                        
                    await status_msg.edit_text("📤 Sending track back to Telegram...")
                    with open(out_path, "rb") as f_send:
                        await context.bot.send_audio(
                            chat_id, 
                            f_send, 
                            title="AI Generated Music",
                            performer="MusicGen",
                            caption=f"🎵 **Vibe**: `{args_str}`",
                            parse_mode="Markdown"
                        )
                    await status_msg.delete()
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return
                elif status == "failed":
                    await status_msg.edit_text(f"❌ Music generation failed: {prediction.get('error', 'unknown error')}")
                    return
                elif status == "canceled":
                    await status_msg.edit_text("❌ Music generation was canceled.")
                    return
                    
            await status_msg.edit_text("⏱️ Music generation timed out on Replicate.")
    except Exception as e:
        logger.error(f"Music generation error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error generating music: {str(e)}")

async def stylize_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message = update.message
    
    # Get photo source
    photo_file = None
    if message.reply_to_message:
        reply = message.reply_to_message
        if reply.photo:
            photo_file = reply.photo[-1]
        elif reply.document and is_doc_image(reply.document):
            photo_file = reply.document
    elif message.photo:
        photo_file = message.photo[-1]
    elif message.document and is_doc_image(message.document):
        photo_file = message.document
        
    if not photo_file:
        await message.reply_text(
            "⚠️ **AI Avatar Stylizer Usage**:\n\n"
            "• Reply to any face photo with: `/avatar` or `/stylize`\n"
            "• Or upload a face photo with the caption: `/avatar` or `/stylize`",
            parse_mode="Markdown"
        )
        return
        
    clear_session(chat_id, user_id)
    session = get_session(chat_id, user_id)
    session["avatar_photo_id"] = photo_file.file_id
    session["action"] = "avatar_stylize"
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧱 Claymation", callback_data="style:Clay"),
            InlineKeyboardButton("🎮 Video Game", callback_data="style:Video game"),
        ],
        [
            InlineKeyboardButton("👾 Pixel Art", callback_data="style:Pixel art"),
            InlineKeyboardButton("🧸 3D Toy", callback_data="style:Toy"),
        ],
        [
            InlineKeyboardButton("😃 Emoji", callback_data="style:Emoji"),
            InlineKeyboardButton("🎬 Pixar 3D", callback_data="style:3D"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel")
        ]
    ])
    await message.reply_text(
        "🎭 **Select Avatar Style**\n\nPlease choose the artistic style for your stylized face avatar:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def execute_webapp_generation(query_or_msg, prompt_desc, chat_id, context):
    if not GEMINI_API_KEY:
        if hasattr(query_or_msg, "edit_message_text"):
            await query_or_msg.edit_message_text("⚠️ Google Gemini AI is not configured.")
        else:
            await query_or_msg.reply_text("⚠️ Google Gemini AI is not configured.")
        return

    if hasattr(query_or_msg, "edit_message_text"):
        status_msg = query_or_msg
        await status_msg.edit_message_text("⚡ **Antigravity AI**: Designing layout, styling CSS, and coding JavaScript logic...")
    else:
        status_msg = await query_or_msg.reply_text("⚡ **Antigravity AI**: Designing layout, styling CSS, and coding JavaScript logic...")

    try:
        import asyncio
        import zipfile
        import re

        system_prompt = (
            "You are Antigravity, a world-class AI Web Developer. "
            "Generate a complete, production-grade, self-contained single-file HTML web application based on the user prompt.\n\n"
            "STRICT DESIGN & CODE REQUIREMENTS:\n"
            "1. Output MUST be a single valid HTML5 document containing all HTML, embedded CSS within <style>, and JavaScript within <script>.\n"
            "2. STYLING (CSS): Use stunning modern aesthetics—vibrant curated HSL color palettes, dark mode, smooth glassmorphism, flexbox/grid layout, Google Fonts (e.g. Inter/Roboto), smooth hover transitions, micro-animations, and responsive media queries.\n"
            "3. LOGIC (JS): Implement full interactive JavaScript functionality (e.g. functional buttons, dark/light toggle, dynamic calculators, interactive cards, smooth scrolling, modal dialogs, local storage saving if applicable).\n"
            "4. NO PLACEHOLDERS: Create complete text content, features, and realistic UI elements.\n"
            "5. OUTPUT FORMAT: Return ONLY the code inside ```html ... ``` block. Do not include markdown chatter outside the code block."
        )

        full_user_prompt = f"{system_prompt}\n\nUSER REQUEST: {prompt_desc}"

        model = genai.GenerativeModel(GEMINI_MODEL)
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: model.generate_content(full_user_prompt)
        )

        raw_text = response.text if hasattr(response, "text") else ""

        html_code = ""
        match = re.search(r"```html\s*(.*?)\s*```", raw_text, re.DOTALL | re.IGNORECASE)
        if match:
            html_code = match.group(1).strip()
        elif "<!DOCTYPE html>" in raw_text or "<html" in raw_text:
            html_code = raw_text.strip()
        else:
            html_code = f"<!DOCTYPE html>\n<html>\n<head><title>Web Page</title></head>\n<body>{raw_text}</body>\n</html>"

        temp_dir = tempfile.mkdtemp()
        html_filename = "index.html"
        html_path = os.path.join(temp_dir, html_filename)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_code)

        zip_filename = "web_application.zip"
        zip_path = os.path.join(temp_dir, zip_filename)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(html_path, arcname="index.html")

        if hasattr(query_or_msg, "edit_message_text"):
            await query_or_msg.edit_message_text("📤 Uploading web application files to Telegram...")

        with open(html_path, "rb") as f_html:
            await context.bot.send_document(
                chat_id,
                f_html,
                filename="index.html",
                caption=(
                    f"✨ **Antigravity AI Web Page Created!**\n\n"
                    f"🎯 **Template**: \"_{prompt_desc[:60]}..._\"\n"
                    "📄 `index.html` (Double-click to open in any browser!)"
                ),
                parse_mode="Markdown"
            )

        with open(zip_path, "rb") as f_zip:
            await context.bot.send_document(
                chat_id,
                f_zip,
                filename="website_package.zip",
                caption="📦 **Complete Web Application ZIP Archive**",
                parse_mode="Markdown"
            )

        if hasattr(query_or_msg, "delete"):
            await query_or_msg.delete()
        shutil.rmtree(temp_dir, ignore_errors=True)

    except Exception as e:
        logger.error(f"Antigravity Web Page error: {e}", exc_info=True)
        if hasattr(query_or_msg, "edit_message_text"):
            await query_or_msg.edit_message_text(f"❌ Error generating web page: {str(e)}")
        else:
            await query_or_msg.reply_text(f"❌ Error generating web page: {str(e)}")

async def webapp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message = update.message
    
    args_str = " ".join(context.args) if context.args else ""
    if not args_str and message.reply_to_message and message.reply_to_message.text:
        args_str = message.reply_to_message.text
        
    if args_str:
        await execute_webapp_generation(message, args_str, chat_id, context)
        return

    keyboard = [
        [InlineKeyboardButton("💻 Dev Portfolio", callback_data="webpreset:Developer Portfolio with Dark Mode & Glassmorphism"), InlineKeyboardButton("🚀 SaaS Landing Page", callback_data="webpreset:Modern SaaS Landing Page with Pricing Cards")],
        [InlineKeyboardButton("⏱️ Study / Pomodoro Timer", callback_data="webpreset:Interactive Pomodoro Study Timer App"), InlineKeyboardButton("🎵 Lofi Audio Player", callback_data="webpreset:Futuristic Lofi Music Player with Visualizer Controls")],
        [InlineKeyboardButton("📊 Business Showcase", callback_data="webpreset:Corporate Business Showcase Landing Page with Contact Form"), InlineKeyboardButton("🧮 Interactive Calculator", callback_data="webpreset:Smart Unit & Currency Converter Calculator App")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text(
        "⚡ **Antigravity AI Web Creator**\n\n"
        "Click a ready-made template below to generate your web app instantly, or type a topic (e.g. `/website fitness tracker`):",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def code_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message = update.message
    
    args_str = " ".join(context.args) if context.args else ""
    if not args_str and message.reply_to_message and message.reply_to_message.text:
        args_str = message.reply_to_message.text
        
    if not args_str:
        await message.reply_text(
            "💻 **Antigravity AI Code Reviewer Usage**:\n\n"
            "• `/code <paste code snippet or error trace>`\n"
            "• Or reply to any code/error message with `/code`\n\n"
            "Antigravity AI will analyze bugs, optimize logic, provide refactored code, and explain key improvements!",
            parse_mode="Markdown"
        )
        return
        
    if not GEMINI_API_KEY:
        await message.reply_text("⚠️ Google Gemini AI is not configured.")
        return
        
    status_msg = await message.reply_text("💻 **Antigravity AI**: Analyzing code structure and auditing logic...")
    await message.reply_chat_action("typing")
    
    try:
        import asyncio
        
        system_prompt = (
            "You are Antigravity, an expert Senior Software Engineer and Code Auditor. "
            "Analyze the provided code snippet, error log, or architecture request.\n\n"
            "STRUCTURE YOUR RESPONSE CLEARLY AS FOLLOWS:\n"
            "1. 🔍 **Issue & Bug Diagnosis**: Briefly explain any syntax errors, logical bugs, performance bottlenecks, or security flaws.\n"
            "2. 💡 **Fixed & Refactored Code**: Provide complete, production-ready, clean code inside Markdown code blocks (e.g. ```python ... ```).\n"
            "3. 🚀 **Key Improvements**: Bullet points explaining why the fixes work and best practices applied."
        )
        
        full_user_prompt = f"{system_prompt}\n\nCODE / ERROR TO AUDIT:\n{args_str}"
        
        model = genai.GenerativeModel(GEMINI_MODEL)
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: model.generate_content(full_user_prompt)
        )
        
        res_text = response.text if hasattr(response, "text") else "No response generated."
        
        header = "💻 **Antigravity AI Code Audit & Review**:\n\n"
        full_message = header + res_text
        
        try:
            await status_msg.edit_text(full_message, parse_mode="Markdown")
        except Exception:
            await status_msg.edit_text(full_message)
            
    except Exception as e:
        logger.error(f"Antigravity Code Auditor error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error during code review: {str(e)}")

async def summarize_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message = update.message
    
    args_str = " ".join(context.args) if context.args else ""
    if not args_str and message.reply_to_message and message.reply_to_message.text:
        args_str = message.reply_to_message.text
        
    if not args_str:
        await message.reply_text(
            "🌐 **AI Web Summarizer Usage**:\n\n"
            "• `/summarize https://example.com/article`\n"
            "• Or reply to any long article/text message with `/summarize`\n\n"
            "Gemini AI will extract key takeaways and provide an executive summary!",
            parse_mode="Markdown"
        )
        return
        
    if not GEMINI_API_KEY:
        await message.reply_text("⚠️ Google Gemini AI is not configured.")
        return
        
    status_msg = await message.reply_text("🌐 **Antigravity AI**: Reading webpage content and summarizing key takeaways...")
    await message.reply_chat_action("typing")
    
    try:
        import asyncio
        import httpx
        import re
        
        text_content = args_str
        
        url_match = re.search(r'https?://[^\s]+', args_str)
        if url_match:
            target_url = url_match.group(0)
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                res = await client.get(target_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                if res.status_code == 200:
                    try:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(res.text, "html.parser")
                        for element in soup(["script", "style", "nav", "footer", "header"]):
                            element.extract()
                        raw_extracted = soup.get_text(separator=" ", strip=True)
                    except Exception:
                        raw_extracted = re.sub(r'<[^>]+>', ' ', res.text)
                    text_content = f"URL: {target_url}\n\nPAGE CONTENT:\n{raw_extracted[:8000]}"
                    
        system_prompt = (
            "You are Antigravity, an expert Executive Research Assistant. "
            "Summarize the provided article, web page content, or text.\n\n"
            "STRUCTURE YOUR RESPONSE CLEARLY AS FOLLOWS:\n"
            "📌 **Executive Summary**: A concise 2-3 sentence overview.\n"
            "🔑 **Key Takeaways**: Bullet points highlighting main arguments and data.\n"
            "⏱️ **Estimated Reading Time**: Total read time."
        )
        
        full_prompt = f"{system_prompt}\n\nCONTENT TO SUMMARIZE:\n{text_content}"
        
        model = genai.GenerativeModel(GEMINI_MODEL)
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: model.generate_content(full_prompt)
        )
        
        res_text = response.text if hasattr(response, "text") else "No summary generated."
        header = "🌐 **AI Web Page & Article Summary**:\n\n"
        full_message = header + res_text
        
        try:
            await status_msg.edit_text(full_message, parse_mode="Markdown")
        except Exception:
            await status_msg.edit_text(full_message)
            
    except Exception as e:
        logger.error(f"Summarizer error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error summarizing content: {str(e)}")

async def seminar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message = update.message
    
    args_str = " ".join(context.args) if context.args else ""
    if not args_str and message.caption and (message.caption.startswith("/seminar") or message.caption.startswith("/create_seminar")):
        caption_parts = message.caption.split()
        if len(caption_parts) > 1:
            args_str = message.caption.replace(caption_parts[0], "", 1).strip()
            
    if not args_str:
        await message.reply_text(
            "🎓 **AI Seminar Presentation & Report Creator**\n\n"
            "Usage:\n"
            "• `/seminar Quantum Computing`\n"
            "• `/seminar Blockchain Technology in Finance`\n"
            "• `/seminar Deep Learning for Medical Diagnostics`",
            parse_mode="Markdown"
        )
        return
        
    clear_session(chat_id, user_id)
    session = get_session(chat_id, user_id)
    session["seminar_topic"] = args_str
    session["action"] = "seminar_creator"
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌑 Tech Dark", callback_data="theme:dark"),
            InlineKeyboardButton("Clean Minimalist ⚪", callback_data="theme:clean"),
        ],
        [
            InlineKeyboardButton("🔵 Corporate Blue", callback_data="theme:corporate"),
            InlineKeyboardButton("Creative Warm 🍊", callback_data="theme:warm"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel")
        ]
    ])
    await message.reply_text(
        f"🎓 **Seminar Topic**: `{args_str}`\n\n"
        "Please choose a design theme for your presentation slides and report:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def execute_seminar_generation(query_or_msg, session, chat_id, user_id, context):
    def get_notify():
        async def notify(text):
            try:
                if hasattr(query_or_msg, "edit_message_text"):
                    await query_or_msg.edit_message_text(text, parse_mode="Markdown")
                else:
                    await query_or_msg.reply_text(text, parse_mode="Markdown")
            except Exception:
                pass
        return notify
        
    notify = get_notify()
    
    topic = session.get("seminar_topic")
    theme = session.get("selected_theme", "clean")
    
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
    if not GEMINI_API_KEY:
        await notify("⚠️ **Gemini API Key is not configured!**")
        clear_session(chat_id, user_id)
        return
        
    try:
        import json
        import google.generativeai as genai
        
        await notify(f"⏳ **Generating Seminar Content**...\n"
                     f"Connecting to Gemini AI for topic: `{topic}`")
                     
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        
        prompt = (
            f"You are an academic expert. Generate a comprehensive seminar presentation outline and detailed research report content on the topic: '{topic}'.\n"
            f"You must return ONLY a valid JSON object matching the following structure. Do not wrap it in markdown code blocks like ```json:\n"
            "{\n"
            "  \"title\": \"Direct Topic Title\",\n"
            "  \"slides\": [\n"
            "    {\n"
            "      \"title\": \"Slide Title (e.g. Introduction to ...)\",\n"
            "      \"bullets\": [\"Bullet point 1\", \"Bullet point 2\", \"Bullet point 3\"],\n"
            "      \"notes\": \"Detailed speaker notes script for this slide to read aloud.\"\n"
            "    }\n"
            "  ],\n"
            "  \"report\": [\n"
            "    {\n"
            "      \"heading\": \"Abstract\",\n"
            "      \"content\": \"Abstract text summarizing the seminar.\"\n"
            "    },\n"
            "    {\n"
            "      \"heading\": \"1. Introduction\",\n"
            "      \"content\": \"Introduction content paragraphs.\"\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "Make sure you generate at least 6 content slides and at least 5 detailed report sections (Abstract, Introduction, Technical Architecture/Core Details, Applications/Use-cases, Conclusion)."
        )
        
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Clean JSON if wrapped
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            response_text = "\n".join(lines).strip()
            
        try:
            data = json.loads(response_text)
        except Exception as json_err:
            logger.error(f"JSON parse error: {json_err}, raw text: {response_text}")
            await notify("❌ Error: Failed to parse generated content into JSON. Retrying with a simplified prompt...")
            # Retry once with simplified prompt
            response = model.generate_content("Generate simple valid JSON outlining 5 slides for: " + topic + ". Same schema.")
            response_text = response.text.strip()
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                response_text = "\n".join(lines).strip()
            data = json.loads(response_text)
            
        title = data.get("title", topic)
        slides_list = data.get("slides", [])
        report_list = data.get("report", [])
        
        await notify("🛠️ Generating PowerPoint presentation slides and Word report files...")
        
        temp_dir = tempfile.mkdtemp()
        ppt_filename = f"presentation_{topic.lower().replace(' ', '_')}.pptx"
        doc_filename = f"report_{topic.lower().replace(' ', '_')}.docx"
        
        ppt_path = os.path.join(temp_dir, ppt_filename)
        doc_path = os.path.join(temp_dir, doc_filename)
        
        from seminar_utils import create_seminar_presentation, create_seminar_report
        
        create_seminar_presentation(ppt_path, title, slides_list, theme)
        create_seminar_report(doc_path, title, report_list, theme)
        
        await notify("📤 Uploading files to Telegram...")
        
        # Send PPTX
        with open(ppt_path, "rb") as f_ppt:
            await context.bot.send_document(
                chat_id, 
                f_ppt, 
                filename=ppt_filename,
                caption=f"📊 **Presentation Slides** (`.pptx`)\nTheme: `{theme.upper()}`\nTopic: `{title}`",
                parse_mode="Markdown"
            )
            
        # Send DOCX
        with open(doc_path, "rb") as f_doc:
            await context.bot.send_document(
                chat_id, 
                f_doc, 
                filename=doc_filename,
                caption=f"📝 **Detailed Seminar Report** (`.docx`)\nTopic: `{title}`",
                parse_mode="Markdown"
            )
            
        if hasattr(query_or_msg, "delete"):
            try:
                await query_or_msg.delete()
            except Exception:
                pass
                
        shutil.rmtree(temp_dir, ignore_errors=True)
        clear_session(chat_id, user_id)
        
    except Exception as e:
        logger.error(f"Seminar creation error: {e}", exc_info=True)
        await notify(f"❌ Error generating seminar: {str(e)}")
        clear_session(chat_id, user_id)

async def start_action_command(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    clear_session(chat_id, user_id)
    
    session = get_session(chat_id, user_id)
    session["action"] = action
    session["temp_dir"] = tempfile.mkdtemp()
    session["files"] = []
    session["step"] = "waiting_for_files"
    
    prompt_texts = {
        "merge": "🔗 **Merge Files (PDF, PPT, Word, Excel, Images)**\nPlease upload **multiple files** (PDF, PPT, Word, Excel, Images) one by one (supports **up to 100 files**). Once done, click **Merge Now** below.",
        "split": "✂️ **Split PDF**\nPlease upload the PDF document you want to split.",
        "rotate": "🔄 **Rotate PDF**\nPlease upload the PDF document you want to rotate.",
        "layout_settings": "⚙️ **Add Layout Settings**\nPlease upload the PDF document you want to add headers, footers, or page numbers to.",
        "word2pdf": "📝 **Word ➔ PDF**\nPlease upload your Word document (`.docx` or `.doc`).",
        "pdf2word": "📥 **PDF ➔ Word**\nPlease upload your PDF document to convert to Word (`.docx`).",
        "ppt2pdf": "📊 **PPT ➔ PDF**\nPlease upload your PowerPoint presentation (`.pptx` or `.ppt`).",
        "pdf2ppt": "📥 **PDF ➔ PPT**\nPlease upload your PDF document to convert to PowerPoint (`.pptx`).",
        "excel2pdf": "📈 **Excel ➔ PDF**\nPlease upload your Excel spreadsheet (`.xlsx` or `.xls`).",
        "pdf2excel": "📥 **PDF ➔ Excel**\nPlease upload your PDF document to convert to Excel (`.xlsx`).",
        "ppt2images": "🖼️ **PPT ➔ Images**\nPlease upload your PowerPoint presentation.",
        "pdf2images": "🖼️ **PDF ➔ Images**\nPlease upload your PDF document.",
        "images2pdf": "➕ **Images ➔ PDF**\nPlease upload **one or more images** (JPG/PNG). Once you have uploaded all images, click the **Convert Now** button below.",
        "img_rotate": "🔄 **Rotate Image**\nPlease upload the photo you want to rotate (JPG or PNG).",
        "img_resize": "📐 **Resize Image**\nPlease upload the photo you want to resize (JPG or PNG).",
        "img_compress": "📉 **Compress Image**\nPlease upload the photo you want to compress (JPG or PNG).",
        "img_convert": "🔄 **Convert Format**\nPlease upload the photo you want to convert (JPG or PNG).",
        "img_grayscale": "🎨 **Grayscale Filter**\nPlease upload the photo you want to apply grayscale to (JPG or PNG).",
        "video2gif": "🎞️ **Video to GIF**\nPlease upload the video file you want to convert to an animated GIF.",
        "images2gif": "🖼️ **Images to GIF**\nPlease upload **multiple images** (JPG/PNG). Once you have uploaded all frames, click the **Generate GIF** button below.",
        "pdf_encrypt": "🔒 **Lock PDF (Password Protect)**\nPlease upload the PDF document you want to lock with a password.",
        "pdf_decrypt": "🔓 **Unlock PDF (Remove Password)**\nPlease upload the locked PDF document.",
        "pdf_watermark": "✍️ **Watermark PDF**\nPlease upload the PDF document you want to add a watermark to.",
        "pdf_rem_watermark": "🧼 **Remove PDF Watermark**\nPlease upload the PDF document you want to remove the text watermark from.",
        "excel_chart": "📊 **Excel/CSV Chart Generator**\nPlease upload the Excel sheet (`.xlsx`, `.xls`) or CSV file to plot.",
    }
    
    prompt = prompt_texts.get(action, "Please upload your document.")
    
    keyboard = None
    if action == "merge":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔗 Merge Now", callback_data="process:merge_now"),
            InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
        ]])
    elif action == "images2pdf":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Convert Now", callback_data="process:convert_images"),
            InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
        ]])
    elif action == "images2gif":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🖼️ Generate GIF", callback_data="process:generate_gif_now"),
            InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
        ]])
    else:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel")]])
        
    await update.message.reply_text(prompt, reply_markup=keyboard, parse_mode="Markdown")


# --- Callback Queries (Buttons) ---

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CURRENT_IMAGE_MODEL, CURRENT_EDIT_MODEL
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"handle_callback: chat_id={chat_id}, user_id={user_id}, data='{data}'")
    
    # 1. Menu Navigations
    if data.startswith("menu:"):
        menu_name = data.split(":")[1]
        clear_session(chat_id, user_id) # Reset session on menu change
        
        if menu_name == "main":
            await query.edit_message_text("Select a category below:", reply_markup=get_main_keyboard())
        elif menu_name == "pdf":
            await query.edit_message_text("📂 **PDF Utilities**:\nSelect an operation:", reply_markup=get_pdf_keyboard(), parse_mode="Markdown")
        elif menu_name == "office":
            await query.edit_message_text("🔄 **Office Conversions**:\nSelect an operation:", reply_markup=get_office_keyboard(), parse_mode="Markdown")
        elif menu_name == "image_utils":
            await query.edit_message_text("🖼️ **Image Utilities**:\nSelect an operation:", reply_markup=get_image_keyboard(), parse_mode="Markdown")
            
    # 2. Cancel Button
    elif data == "btn:cancel":
        clear_session(chat_id, user_id)
        await query.edit_message_text("❌ Operation cancelled. Use /start to open the menu again.")
        
    # 3. Action Buttons
    elif data.startswith("action:"):
        action = data.split(":")[1]
        session = get_session(chat_id, user_id)
        session["action"] = action
        session["temp_dir"] = tempfile.mkdtemp()
        session["files"] = []
        
        prompt_texts = {
            "merge": "🔗 **Merge Files (PDF, PPT, Word, Excel, Images)**\nPlease upload **multiple files** (PDF, PPT, Word, Excel, Images) one by one (supports **up to 100 files**). Once done, click **Merge Now** below.",
            "split": "✂️ **Split PDF**\nPlease upload the PDF document you want to split.",
            "rotate": "🔄 **Rotate PDF**\nPlease upload the PDF document you want to rotate.",
            "layout_settings": "⚙️ **Add Layout Settings**\nPlease upload the PDF document you want to add headers, footers, or page numbers to.",
            "word2pdf": "📝 **Word ➔ PDF**\nPlease upload your Word document (`.docx` or `.doc`).",
            "pdf2word": "📥 **PDF ➔ Word**\nPlease upload your PDF document to convert to Word (`.docx`).",
            "ppt2pdf": "📊 **PPT ➔ PDF**\nPlease upload your PowerPoint presentation (`.pptx` or `.ppt`).",
            "pdf2ppt": "📥 **PDF ➔ PPT**\nPlease upload your PDF document to convert to PowerPoint (`.pptx`).",
            "excel2pdf": "📈 **Excel ➔ PDF**\nPlease upload your Excel spreadsheet (`.xlsx` or `.xls`).",
            "pdf2excel": "📥 **PDF ➔ Excel**\nPlease upload your PDF document to convert to Excel (`.xlsx`).",
            "ppt2images": "🖼️ **PPT ➔ Images**\nPlease upload your PowerPoint presentation.",
            "pdf2images": "🖼️ **PDF ➔ Images**\nPlease upload your PDF document.",
            "images2pdf": "➕ **Images ➔ PDF**\nPlease upload **one or more images** (JPG/PNG). Once you have uploaded all images, click the **Convert Now** button below.",
            "img_rotate": "🔄 **Rotate Image**\nPlease upload the photo you want to rotate (JPG or PNG).",
            "img_resize": "📐 **Resize Image**\nPlease upload the photo you want to resize (JPG or PNG).",
            "img_compress": "📉 **Compress Image**\nPlease upload the photo you want to compress (JPG or PNG).",
            "img_convert": "🔄 **Convert Format**\nPlease upload the photo you want to convert (JPG or PNG).",
            "img_grayscale": "🎨 **Grayscale Filter**\nPlease upload the photo you want to apply grayscale to (JPG or PNG).",
            "video2gif": "🎞️ **Video to GIF**\nPlease upload the video file you want to convert to an animated GIF.",
            "images2gif": "🖼️ **Images to GIF**\nPlease upload **multiple images** (JPG/PNG). Once you have uploaded all frames, click the **Generate GIF** button below.",
            "pdf_encrypt": "🔒 **Lock PDF (Password Protect)**\nPlease upload the PDF document you want to lock with a password.",
            "pdf_decrypt": "🔓 **Unlock PDF (Remove Password)**\nPlease upload the locked PDF document.",
            "pdf_watermark": "✍️ **Watermark PDF**\nPlease upload the PDF document you want to add a watermark to.",
            "pdf_rem_watermark": "🧼 **Remove PDF Watermark**\nPlease upload the PDF document you want to remove the text watermark from.",
            "excel_chart": "📊 **Excel/CSV Chart Generator**\nPlease upload the Excel sheet (`.xlsx`, `.xls`) or CSV file to plot.",
        }
        
        prompt = prompt_texts.get(action, "Please upload your document.")
        
        # Add a special button for multi-file actions (Merge and Images➔PDF)
        keyboard = None
        if action == "merge":
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔗 Merge Now", callback_data="process:merge_now"),
                InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
            ]])
        elif action == "images2pdf":
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("➕ Convert Now", callback_data="process:convert_images"),
                InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
            ]])
        elif action == "images2gif":
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🖼️ Generate GIF", callback_data="process:generate_gif_now"),
                InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
            ]])
        else:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel")]])
            
        await query.edit_message_text(prompt, reply_markup=keyboard, parse_mode="Markdown")
        session["step"] = "waiting_for_files"

    # 4. Multi-file Processing Triggers
    elif data == "process:merge_now":
        session = get_session(chat_id, user_id)
        if len(session["files"]) < 2:
            await context.bot.send_message(chat_id, "⚠️ Please upload at least 2 PDF files before merging!")
            return
        # Go to layout selection for the merged PDF
        await start_layout_config_flow(query, session)
        
    elif data == "process:convert_images":
        session = get_session(chat_id, user_id)
        if not session["files"]:
            await context.bot.send_message(chat_id, "⚠️ Please upload at least 1 image before converting!")
            return
        # Go to layout selection for the images PDF
        await start_layout_config_flow(query, session)
        
    elif data == "process:generate_gif_now":
        session = get_session(chat_id, user_id)
        if len(session["files"]) < 2:
            await context.bot.send_message(chat_id, "⚠️ Please upload at least 2 images to generate a GIF!")
            return
        await execute_operation(query, session, chat_id, user_id, context)
        
    elif data.startswith("chart_type:"):
        chart_type = data.split(":")[1]
        session = get_session(chat_id, user_id)
        session["chart_type"] = chart_type
        await execute_operation(query, session, chat_id, user_id, context)
        
    elif data.startswith("style:"):
        selected_style = data.split(":")[1]
        session = get_session(chat_id, user_id)
        session["selected_style"] = selected_style
        await query.edit_message_text(f"⏳ Generating stylized avatar in `{selected_style}` style...")
        await execute_avatar_stylize(query, session, chat_id, user_id, context)
        
    elif data.startswith("theme:"):
        selected_theme = data.split(":")[1]
        session = get_session(chat_id, user_id)
        session["selected_theme"] = selected_theme
        topic = session.get("seminar_topic")
        if not topic:
            await query.edit_message_text("❌ Error: Seminar topic not found in session.")
            clear_session(chat_id, user_id)
            return
        await query.edit_message_text(
            f"⏳ **Selected Theme**: `{selected_theme.upper()}`\n"
            f"🚀 Generating seminar outline and detailed content for `{topic}` using Gemini AI..."
        )
        await execute_seminar_generation(query, session, chat_id, user_id, context)
        
    elif data.startswith("webpreset:"):
        preset_prompt = data.split("webpreset:")[1]
        await execute_webapp_generation(query, preset_prompt, chat_id, context)
        
    # 5. Layout Setup Callbacks
    elif data.startswith("layout:"):
        layout_type = data.split(":")[1]
        session = get_session(chat_id, user_id)
        
        if layout_type == "none":
            # Skip layout configs, execute immediately
            await execute_operation(query, session, chat_id, user_id, context)
        elif layout_type == "page_nums":
            session["config"]["add_page_numbers"] = True
            await prompt_exclude_first_page(query, session)
        elif layout_type == "custom":
            session["config"]["add_page_numbers"] = True
            await prompt_exclude_first_page(query, session, custom_layout=True)
            
    elif data.startswith("exclude:"):
        choice = data.split(":")[1]
        session = get_session(chat_id, user_id)
        session["config"]["exclude_first_page"] = (choice == "yes")
        
        # Check if they wanted custom layout details or page numbers only
        # We can tell by config_step
        if session["config_step"] == "ask_exclude_first_custom":
            session["config_step"] = "ask_header"
            await query.edit_message_text("✍️ Please type the **Header Text** to place at the top-left of each page (or click /skip if you don't want a header).", parse_mode="Markdown")
        else:
            # Page numbers only, skip header/footer prompts
            await execute_operation(query, session, chat_id, user_id, context)
            
    elif data.startswith("rotate_angle:"):
        angle = int(data.split(":")[1])
        session = get_session(chat_id, user_id)
        session["rotation_angle"] = angle
        await query.edit_message_text(f"⏳ Rotating PDF pages by {angle}°...")
        await execute_operation(query, session, chat_id, user_id, context)
        
    elif data.startswith("compress_level:"):
        level = data.split(":")[1]
        session = get_session(chat_id, user_id)
        session["compress_level"] = level
        await query.edit_message_text(f"⏳ Compressing PDF (level: `{level}`)...")
        await execute_operation(query, session, chat_id, user_id, context)
        
    elif data.startswith("img_rotate_angle:"):
        angle = int(data.split(":")[1])
        session = get_session(chat_id, user_id)
        session["img_rotate_angle"] = angle
        await query.edit_message_text(f"⏳ Rotating photo by {angle}°...")
        await execute_image_operation(query, session, context)
        
    elif data.startswith("img_resize_pct:"):
        pct = int(data.split(":")[1])
        session = get_session(chat_id, user_id)
        session["img_resize_pct"] = pct
        await query.edit_message_text(f"⏳ Resizing photo to {pct}%...")
        await execute_image_operation(query, session, context)
        
    elif data.startswith("img_resize_width:"):
        session = get_session(chat_id, user_id)
        session["config_step"] = "ask_img_custom_width"
        await query.edit_message_text("📐 Please type your **target width in pixels** (e.g. `800`):", parse_mode="Markdown")
        
    elif data.startswith("img_compress_level:"):
        level = data.split(":")[1]
        session = get_session(chat_id, user_id)
        session["img_compress_level"] = level
        await query.edit_message_text(f"⏳ Compressing photo with {level.upper()} quality...")
        await execute_image_operation(query, session, context)
        
    elif data.startswith("img_convert_format:"):
        fmt = data.split(":")[1]
        session = get_session(chat_id, user_id)
        session["img_convert_format"] = fmt
        await query.edit_message_text(f"⏳ Converting photo format to {fmt.upper()}...")
        await execute_image_operation(query, session, context)

    elif data == "set_model_cat:gen":
        keyboard = [
            [InlineKeyboardButton("Flux 1.1 Pro ⚡", callback_data="set_model_select:gen:black-forest-labs/flux-1.1-pro")],
            [InlineKeyboardButton("Flux 2 Pro 💎", callback_data="set_model_select:gen:black-forest-labs/flux-2-pro")],
            [InlineKeyboardButton("Google Imagen 4 🌟", callback_data="set_model_select:gen:google/imagen-4")],
            [InlineKeyboardButton("Flux Kontext Pro 📖", callback_data="set_model_select:gen:black-forest-labs/flux-kontext-pro")],
            [InlineKeyboardButton("Ideogram v3 Turbo 🚀", callback_data="set_model_select:gen:ideogram-ai/ideogram-v3-turbo")],
            [InlineKeyboardButton("« Back", callback_data="menu:set_model_back")]
        ]
        await query.edit_message_text("🎨 Choose a **Text-to-Image** model:", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "set_model_cat:edit":
        keyboard = [
            [InlineKeyboardButton("InstructPix2Pix (Fast Edit) 🖼️", callback_data="set_model_select:edit:timothybrooks/instruct-pix2pix")],
            [InlineKeyboardButton("Flux 1.1 Pro (Guided Edit) ⚡", callback_data="set_model_select:edit:black-forest-labs/flux-1.1-pro")],
            [InlineKeyboardButton("« Back", callback_data="menu:set_model_back")]
        ]
        await query.edit_message_text("🖼️ Choose an **Image-to-Image / Edit** model:", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "menu:set_model_back":
        prompt = (
            "⚙️ **Select AI Models**\n\n"
            f"• **Current Image Gen Model**: `{CURRENT_IMAGE_MODEL}`\n"
            f"• **Current Image Edit Model**: `{CURRENT_EDIT_MODEL}`\n\n"
            "Choose a model category to customize:"
        )
        keyboard = [
            [InlineKeyboardButton("🎨 Text-to-Image Models", callback_data="set_model_cat:gen")],
            [InlineKeyboardButton("🖼️ Image-to-Image / Edit Models", callback_data="set_model_cat:edit")],
            [InlineKeyboardButton("❌ Close", callback_data="btn:cancel")]
        ]
        await query.edit_message_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif data.startswith("set_model_select:gen:"):
        model_path = data.replace("set_model_select:gen:", "")
        CURRENT_IMAGE_MODEL = model_path
        await query.edit_message_text(f"✅ Text-to-Image model has been set to:\n`{model_path}`\n\nUse `/generate <prompt>` to create images!", parse_mode="Markdown")
        
    elif data.startswith("set_model_select:edit:"):
        model_path = data.replace("set_model_select:edit:", "")
        CURRENT_EDIT_MODEL = model_path
        await query.edit_message_text(f"✅ Image-to-Image / Edit model has been set to:\n`{model_path}`\n\nSend or reply to photos with prompts to edit them!", parse_mode="Markdown")



# --- Interactive Layout Config Flow ---

async def start_layout_config_flow(query, session):
    session["config_step"] = "ask_layout"
    prompt = (
        "⚙️ **PDF Layout Settings**\n\n"
        "Would you like to overlay page numbers, headers, or footers onto your final output PDF?"
    )
    keyboard = [
        [
            InlineKeyboardButton("No, Keep Original", callback_data="layout:none"),
        ],
        [
            InlineKeyboardButton("Add Page Numbers Only", callback_data="layout:page_nums"),
            InlineKeyboardButton("Add Custom Header/Footer & Page No.", callback_data="layout:custom"),
        ]
    ]
    await query.edit_message_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def prompt_exclude_first_page(query, session, custom_layout=False):
    session["config_step"] = "ask_exclude_first_custom" if custom_layout else "ask_exclude_first"
    prompt = (
        "📄 **Cover Page Setting**\n\n"
        "Do you want to exclude the **first page** (e.g. cover page) from displaying headers, footers, and page numbers?"
    )
    keyboard = [
        [
            InlineKeyboardButton("Yes, Exclude First Page", callback_data="exclude:yes"),
            InlineKeyboardButton("No, Apply to All Pages", callback_data="exclude:no"),
        ]
    ]
    await query.edit_message_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# --- Interactive Image Config Flow ---

async def proceed_image_setup(query_or_msg, session, context):
    action = session["action"]
    
    # Check if we were passed a Message (e.g. from handle_photo / handle_document download)
    is_query = hasattr(query_or_msg, "edit_message_text")
    
    async def send_prompt(text, markup=None):
        if is_query:
            await query_or_msg.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
        else:
            await query_or_msg.reply_text(text, reply_markup=markup, parse_mode="Markdown")

    if action == "img_rotate":
        keyboard = [
            [
                InlineKeyboardButton("Rotate 90° ➡️", callback_data="img_rotate_angle:90"),
                InlineKeyboardButton("Rotate 180° 🔄", callback_data="img_rotate_angle:180"),
            ],
            [
                InlineKeyboardButton("Rotate 270° ⬅️", callback_data="img_rotate_angle:270"),
                InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
            ]
        ]
        await send_prompt("🔄 **Rotation Configuration**\n\nChoose the rotation angle:", InlineKeyboardMarkup(keyboard))
        
    elif action == "img_resize":
        keyboard = [
            [
                InlineKeyboardButton("75% Size", callback_data="img_resize_pct:75"),
                InlineKeyboardButton("50% Size", callback_data="img_resize_pct:50"),
            ],
            [
                InlineKeyboardButton("25% Size", callback_data="img_resize_pct:25"),
                InlineKeyboardButton("Custom Width 📐", callback_data="img_resize_width:custom"),
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
            ]
        ]
        await send_prompt("📐 **Resize Configuration**\n\nChoose a scale percentage or specify a custom width:", InlineKeyboardMarkup(keyboard))
        
    elif action == "img_compress":
        keyboard = [
            [
                InlineKeyboardButton("Low (High Quality)", callback_data="img_compress_level:low"),
            ],
            [
                InlineKeyboardButton("Medium", callback_data="img_compress_level:medium"),
            ],
            [
                InlineKeyboardButton("High (Small File)", callback_data="img_compress_level:high"),
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
            ]
        ]
        await send_prompt("📉 **Compression Configuration**\n\nChoose the compression level:", InlineKeyboardMarkup(keyboard))
        
    elif action == "img_convert":
        keyboard = [
            [
                InlineKeyboardButton("Convert to JPG 🖼️", callback_data="img_convert_format:jpg"),
                InlineKeyboardButton("Convert to PNG 🖼️", callback_data="img_convert_format:png"),
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
            ]
        ]
        await send_prompt("🔄 **Format Configuration**\n\nChoose the target format to convert to:", InlineKeyboardMarkup(keyboard))
        
    elif action == "img_grayscale":
        if is_query:
            await query_or_msg.edit_message_text("⏳ Converting image to grayscale...")
        else:
            await query_or_msg.reply_text("⏳ Converting image to grayscale...")
        await execute_image_operation(query_or_msg, session, context)

async def execute_image_operation(query_or_msg, session, context):
    chat_id = session.get("chat_id")
    user_id = session.get("user_id")
    is_query = hasattr(query_or_msg, "edit_message_text")
    
    async def notify(text):
        if is_query:
            try:
                await query_or_msg.edit_message_text(text)
            except Exception:
                await context.bot.send_message(chat_id, text)
        else:
            await query_or_msg.reply_text(text)
            
    try:
        if not session["files"]:
            await notify("⚠️ No source image found. Please restart the operation.")
            return
            
        src_path = session["files"][0]
        src_filename = os.path.basename(src_path)
        name, ext = os.path.splitext(src_filename)
        action = session["action"]
        
        output_filename = f"edited_{src_filename}"
        
        def run_pil():
            nonlocal output_filename
            out_path = os.path.join(session["temp_dir"], output_filename)
            if action == "img_rotate":
                angle = session.get("img_rotate_angle", 90)
                rotate_image(src_path, out_path, angle)
            elif action == "img_resize":
                pct = session.get("img_resize_pct")
                custom_w = session.get("img_resize_width")
                resize_image(src_path, out_path, scale_percent=pct, custom_width=custom_w)
            elif action == "img_compress":
                level = session.get("img_compress_level", "medium")
                output_filename = f"compressed_{name}.jpg"
                out_path = os.path.join(session["temp_dir"], output_filename)
                compress_image(src_path, out_path, level)
            elif action == "img_convert":
                fmt = session.get("img_convert_format", "jpg")
                target_ext = f".{fmt.lower()}"
                output_filename = f"converted_{name}{target_ext}"
                out_path = os.path.join(session["temp_dir"], output_filename)
                convert_image_format(src_path, out_path)
            elif action == "img_grayscale":
                grayscale_image(src_path, out_path)
            return out_path
            
        import asyncio
        loop = asyncio.get_running_loop()
        await notify("⏳ Modifying image...")
        output_path = await loop.run_in_executor(None, run_pil)
        
        await notify("📤 Sending processed image back to you...")
        with open(output_path, "rb") as f:
            await context.bot.send_document(chat_id, f, filename=output_filename, caption="✅ Image modified successfully without watermarks!")
            
    except Exception as e:
        logger.error(f"Image modification error: {e}", exc_info=True)
        await notify(f"❌ An error occurred during image modification: {str(e)}")
    finally:
        clear_session(chat_id, user_id)

def is_doc_image(doc):
    if not doc or not doc.file_name:
        return False
    file_ext = os.path.splitext(doc.file_name)[1].lower()
    return file_ext in [".jpg", ".jpeg", ".png"]

async def start_replicate_from_photo_or_doc(update, context, file_id, file_name_hint, prompt):
    chat_id = update.effective_chat.id
    update_msg = await update.message.reply_text("⏳ Downloading image for AI editing...")
    
    try:
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
        token = os.getenv("REPLICATE_API_TOKEN", "").strip()
        if not token:
            await pollinations_image_fallback(chat_id, prompt, update_msg, context)
            return
            
        await update_msg.edit_text("⏳ Processing image request...")
        
        import base64
        import httpx
        import asyncio
        
        new_file = await context.bot.get_file(file_id)
        temp_dir = tempfile.mkdtemp()
        local_path = os.path.join(temp_dir, file_name_hint)
        await new_file.download_to_drive(local_path)
        
        with open(local_path, "rb") as f:
            encoded_data = base64.b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(file_name_hint)[1].lower().replace(".", "")
        mime = "jpeg" if ext in ["jpg", "jpeg"] else ext
        data_uri = f"data:image/{mime};base64,{encoded_data}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        if CURRENT_EDIT_MODEL == "timothybrooks/instruct-pix2pix":
            req_url = "https://api.replicate.com/v1/predictions"
            payload = {
                "version": "30c1d0b916a6f8efce20493f5d61ee27491ab2a60437c13c588468b9810ec23f",
                "input": {
                    "image": data_uri,
                    "prompt": prompt,
                    "num_inference_steps": 25
                }
            }
        else:
            owner, model_name = CURRENT_EDIT_MODEL.split("/")
            req_url = f"https://api.replicate.com/v1/models/{owner}/{model_name}/predictions"
            payload = {
                "input": {
                    "prompt": prompt,
                    "image_prompt": data_uri
                }
            }
            
        await update_msg.edit_text("🚀 Sending request to AI Engine...")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(
                req_url, 
                json=payload, 
                headers=headers
            )
            if res.status_code != 201:
                logger.warning(f"Replicate API status {res.status_code}, switching to Pollinations.ai fallback")
                await pollinations_image_fallback(chat_id, prompt, update_msg, context)
                return
                
            prediction = res.json()
            poll_url = prediction["urls"]["get"]
            
            await update_msg.edit_text("🎨 Editing your image... (this may take 5-15 seconds)")
            
            for _ in range(30):
                await asyncio.sleep(1.5)
                poll_res = await client.get(poll_url, headers=headers)
                if poll_res.status_code != 200:
                    continue
                    
                prediction = poll_res.json()
                status = prediction["status"]
                
                if status == "succeeded":
                    output_urls = prediction.get("output")
                    if not output_urls or not isinstance(output_urls, list):
                        await update_msg.edit_text("❌ No output image received from Replicate.")
                        return
                    
                    output_url = output_urls[0]
                    await update_msg.edit_text("📤 Downloading edited image...")
                    img_res = await client.get(output_url)
                    if img_res.status_code != 200:
                        await update_msg.edit_text("❌ Error downloading final image from Replicate.")
                        return
                        
                    out_filename = f"edited_{os.path.basename(src_path)}"
                    out_path = os.path.join(tempfile.gettempdir(), out_filename)
                    with open(out_path, "wb") as f_out:
                        f_out.write(img_res.content)
                        
                    await update_msg.edit_text("📤 Sending finished image to Telegram...")
                    with open(out_path, "rb") as f_send:
                        await context.bot.send_photo(
                            chat_id, 
                            f_send, 
                            caption=f"✅ Image edited via prompt: *{prompt}*\n\n💬 **Tip**: Reply to this photo with another edit instruction to keep editing!",
                            parse_mode="Markdown"
                        )
                    await update_msg.delete()
                    return
                elif status == "failed":
                    await update_msg.edit_text(f"❌ Image editing failed: {prediction.get('error', 'unknown error')}")
                    return
                elif status == "canceled":
                    await update_msg.edit_text("❌ Image editing was canceled.")
                    return
            
            await update_msg.edit_text("⏱️ Image editing timed out on Replicate.")
            
    except Exception as e:
        logger.error(f"Replicate API connection error: {e}", exc_info=True)
        await update_msg.edit_text(f"❌ Error communicating with Replicate: {str(e)}")

async def execute_avatar_stylize(query_or_msg, session, chat_id, user_id, context):
    def get_notify():
        async def notify(text):
            try:
                if hasattr(query_or_msg, "edit_message_text"):
                    await query_or_msg.edit_message_text(text)
                else:
                    await query_or_msg.reply_text(text)
            except Exception:
                pass
        return notify
        
    notify = get_notify()
    
    photo_id = session.get("avatar_photo_id")
    style = session.get("selected_style", "3D")
    
    if not photo_id:
        await notify("❌ Error: No source portrait found.")
        clear_session(chat_id, user_id)
        return
        
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
    token = os.getenv("REPLICATE_API_TOKEN", "").strip()
    if not token:
        avatar_prompt = f"portrait face avatar in {style} style, highly detailed character art"
        msg_obj = query_or_msg.message if hasattr(query_or_msg, "message") else query_or_msg
        status_msg = await msg_obj.reply_text("⏳ Generating avatar using Free AI Engine...")
        await pollinations_image_fallback(chat_id, avatar_prompt, status_msg, context)
        clear_session(chat_id, user_id)
        return
        
    try:
        import base64
        import httpx
        import asyncio
        
        await notify("⏳ Downloading source portrait...")
        new_file = await context.bot.get_file(photo_id)
        temp_dir = tempfile.mkdtemp()
        local_path = os.path.join(temp_dir, "face_src.jpg")
        await new_file.download_to_drive(local_path)
        
        with open(local_path, "rb") as f:
            encoded_data = base64.b64encode(f.read()).decode("utf-8")
        data_uri = f"data:image/jpeg;base64,{encoded_data}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        req_url = "https://api.replicate.com/v1/predictions"
        payload = {
            "version": "a07f252abbbd832009640b27f063ea52d87d7a23a185ca165bec23b5adc8deaf",
            "input": {
                "image": data_uri,
                "style": style,
                "prompt": "a person portrait, high quality, detailed face",
                "lora_scale": 1.0,
                "prompt_strength": 4.5,
                "denoising_strength": 0.65,
                "instant_id_strength": 0.8,
                "control_depth_strength": 0.8
            }
        }
        
        await notify("🚀 Initiating avatar stylization...")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(req_url, json=payload, headers=headers)
            if res.status_code != 201:
                logger.warning(f"Replicate API status {res.status_code}, switching to Pollinations.ai fallback for avatar")
                shutil.rmtree(temp_dir, ignore_errors=True)
                avatar_prompt = f"portrait face avatar in {style} style, highly detailed character art"
                msg_obj = query_or_msg.message if hasattr(query_or_msg, "message") else query_or_msg
                status_msg = await msg_obj.reply_text("⏳ Generating avatar using Free AI Engine...")
                await pollinations_image_fallback(chat_id, avatar_prompt, status_msg, context)
                clear_session(chat_id, user_id)
                return
                
            prediction = res.json()
            poll_url = prediction["urls"]["get"]
            
            await notify(f"🎨 Generating {style} avatar... (usually takes 10-15 seconds)")
            
            for _ in range(40):
                await asyncio.sleep(2.0)
                poll_res = await client.get(poll_url, headers=headers)
                if poll_res.status_code != 200:
                    continue
                    
                prediction = poll_res.json()
                status = prediction["status"]
                
                if status == "succeeded":
                    output_urls = prediction.get("output")
                    if not output_urls or not isinstance(output_urls, list):
                        await notify("❌ No stylized image received from Replicate.")
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        clear_session(chat_id, user_id)
                        return
                        
                    output_url = output_urls[0]
                    await notify("📥 Downloading final stylized avatar...")
                    img_res = await client.get(output_url)
                    if img_res.status_code != 200:
                        await notify("❌ Error downloading generated image.")
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        clear_session(chat_id, user_id)
                        return
                        
                    out_filename = f"stylized_{style.lower().replace(' ', '_')}.png"
                    out_path = os.path.join(temp_dir, out_filename)
                    with open(out_path, "wb") as f_out:
                        f_out.write(img_res.content)
                        
                    await notify("📤 Sending stylized photo...")
                    with open(out_path, "rb") as f_send:
                        await context.bot.send_photo(
                            chat_id, 
                            f_send, 
                            caption=f"🎭 **Stylized Avatar**\nStyle: `{style}`\n\n💬 **Tip**: Reply to this photo with another edit instruction to keep editing!",
                            parse_mode="Markdown"
                        )
                    # Delete the status message
                    if hasattr(query_or_msg, "delete"):
                        try:
                            await query_or_msg.delete()
                        except Exception:
                            pass
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    clear_session(chat_id, user_id)
                    return
                elif status == "failed":
                    await notify(f"❌ Avatar generation failed: {prediction.get('error', 'unknown error')}")
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    clear_session(chat_id, user_id)
                    return
                elif status == "canceled":
                    await notify("❌ Avatar generation was canceled.")
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    clear_session(chat_id, user_id)
                    return
                    
            await notify("⏱️ Avatar generation timed out on Replicate.")
            shutil.rmtree(temp_dir, ignore_errors=True)
            clear_session(chat_id, user_id)
    except Exception as e:
        logger.error(f"Avatar stylizer error: {e}", exc_info=True)
        await notify(f"❌ Error: {str(e)}")
        clear_session(chat_id, user_id)

async def pollinations_image_fallback(chat_id, prompt, update_msg, context):
    try:
        await update_msg.edit_text("⏳ Generating image...")
        import httpx
        import urllib.parse
        encoded_prompt = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(url)
            if res.status_code == 200:
                temp_dir = tempfile.mkdtemp()
                out_path = os.path.join(temp_dir, "generated_image.jpg")
                with open(out_path, "wb") as f:
                    f.write(res.content)
                    
                await update_msg.edit_text("📤 Uploading generated image to Telegram...")
                with open(out_path, "rb") as f_send:
                    await context.bot.send_photo(
                        chat_id,
                        f_send,
                        caption=f"🎨 **Generated Image**: *{prompt}*",
                        parse_mode="Markdown"
                    )
                await update_msg.delete()
                shutil.rmtree(temp_dir, ignore_errors=True)
                return
            else:
                await update_msg.edit_text(f"❌ Error generating image: HTTP status {res.status_code}")
    except Exception as e:
        logger.error(f"Pollinations fallback error: {e}")
        await update_msg.edit_text(f"❌ Error generating image: {str(e)}")

async def generate_image_with_replicate(chat_id, prompt, update_msg, context):
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
    token = os.getenv("REPLICATE_API_TOKEN", "").strip()
    if not token or not token.startswith("r8_"):
        await pollinations_image_fallback(chat_id, prompt, update_msg, context)
        return

    await update_msg.edit_text(f"⏳ Generating image using `{CURRENT_IMAGE_MODEL}`...")
    
    try:
        import httpx
        import asyncio
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "input": {
                "prompt": prompt
            }
        }
        
        owner, name = CURRENT_IMAGE_MODEL.split("/")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(
                f"https://api.replicate.com/v1/models/{owner}/{name}/predictions", 
                json=payload, 
                headers=headers
            )
            if res.status_code != 201:
                logger.warning(f"Replicate API status {res.status_code}, switching to Pollinations.ai fallback")
                await pollinations_image_fallback(chat_id, prompt, update_msg, context)
                return
                
            prediction = res.json()
            poll_url = prediction["urls"]["get"]
            
            await update_msg.edit_text("🎨 Generating your image... (this may take 5-15 seconds)")
            
            for _ in range(30):
                await asyncio.sleep(1.5)
                poll_res = await client.get(poll_url, headers=headers)
                if poll_res.status_code != 200:
                    continue
                    
                prediction = poll_res.json()
                status = prediction["status"]
                
                if status == "succeeded":
                    output_urls = prediction.get("output")
                    if not output_urls:
                        await pollinations_image_fallback(chat_id, prompt, update_msg, context)
                        return
                    
                    output_url = output_urls[0] if isinstance(output_urls, list) else output_urls
                    await update_msg.edit_text("📤 Downloading generated image...")
                    img_res = await client.get(output_url)
                    if img_res.status_code != 200:
                        await pollinations_image_fallback(chat_id, prompt, update_msg, context)
                        return
                        
                    out_filename = f"generated_{name}_{hash(prompt) % 10000}.png"
                    out_path = os.path.join(tempfile.gettempdir(), out_filename)
                    with open(out_path, "wb") as f_out:
                        f_out.write(img_res.content)
                        
                    await update_msg.edit_text("📤 Sending finished image...")
                    with open(out_path, "rb") as f_send:
                        await context.bot.send_photo(
                            chat_id, 
                            f_send, 
                            caption=f"✅ Generated via `{CURRENT_IMAGE_MODEL}`:\n*{prompt}*\n\n💬 **Tip**: Reply to this photo with an edit instruction (e.g. *\"add a hat\"*) to modify it!",
                            parse_mode="Markdown"
                        )
                    await update_msg.delete()
                    return
                elif status == "failed":
                    await pollinations_image_fallback(chat_id, prompt, update_msg, context)
                    return
                elif status == "canceled":
                    await pollinations_image_fallback(chat_id, prompt, update_msg, context)
                    return
            
            await pollinations_image_fallback(chat_id, prompt, update_msg, context)
            
    except Exception as e:
        logger.error(f"Replicate error: {e}, falling back to Pollinations.ai", exc_info=True)
        await pollinations_image_fallback(chat_id, prompt, update_msg, context)

# --- File Message Handling ---

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_active_group_user(update)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    is_group = update.effective_chat.type in ["group", "supergroup"]
    doc = update.message.document
    caption = update.message.caption or ""
    
    # Check if document is an image and user has a caption command for Replicate
    if doc and is_doc_image(doc):
        bot_username = context.bot.username
        bot_mention = f"@{bot_username}"
        is_mentioned = bot_mention.lower() in caption.lower()
        
        if is_group and is_mentioned:
            prompt = caption.lower().replace(bot_mention.lower(), "").strip()
            if prompt:
                await start_replicate_from_photo_or_doc(update, context, doc.file_id, doc.file_name, prompt)
                return
        elif not is_group and caption:
            if not session or not session["action"]:
                await start_replicate_from_photo_or_doc(update, context, doc.file_id, doc.file_name, caption)
                return
                
    session = USER_SESSIONS.get((chat_id, user_id))
    
    # 1. Group checks: ignore if no active session initialized via menu/command
    if not session or not session["action"]:
        if is_group:
            return  # Ignore completely to avoid bot clutter
        else:
            await update.message.reply_text("Please open the dashboard first using /start to select an action.")
            return
            
    # Check if we are waiting for files
    if session["step"] != "waiting_for_files":
        return
        
    doc_obj = update.message.document
    video_obj = update.message.video
    anim_obj = update.message.animation
    
    file_id = None
    file_name = None
    
    if doc_obj:
        file_id = doc_obj.file_id
        file_name = doc_obj.file_name
    elif video_obj:
        file_id = video_obj.file_id
        file_name = getattr(video_obj, "file_name", None) or "video.mp4"
    elif anim_obj:
        file_id = anim_obj.file_id
        file_name = getattr(anim_obj, "file_name", None) or "animation.mp4"
        
    if not file_id:
        await update.message.reply_text("⚠️ Could not detect any valid document or video file.")
        return
        
    file_ext = os.path.splitext(file_name)[1].lower() if file_name else ""
    
    # Download the document
    await update.message.reply_chat_action("upload_document")
    try:
        new_file = await context.bot.get_file(file_id)
        local_path = os.path.join(session["temp_dir"], file_name)
        await new_file.download_to_drive(local_path)
        session["files"].append(local_path)
    except Exception as e:
        logger.error(f"Download error: {e}")
        await update.message.reply_text("❌ Error downloading the file. Please try again.")
        return

    action = session["action"]
    
    # 2. Flow route based on action
    if action == "merge":
        allowed_merge_exts = [".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls", ".png", ".jpg", ".jpeg"]
        if file_ext not in allowed_merge_exts:
            await update.message.reply_text("⚠️ Invalid file format for merging! Supported: PDF, PPT, Word, Excel, Images (JPG/PNG).")
            session["files"].pop()
            return
            
        if len(session["files"]) > 100:
            await update.message.reply_text("⚠️ Limit reached! Maximum 100 files can be merged in a single batch.")
            session["files"].pop()
            return

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔗 Merge Now", callback_data="process:merge_now"),
                InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
            ]
        ])
        await update.message.reply_text(
            f"📥 Received `{file_name}`.\n\nTotal files to merge: **{len(session['files'])} / 100**.\nUpload more files (PDF, PPT, Word, Excel, Images) or click **Merge Now**.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
    elif action in ["img_rotate", "img_resize", "img_compress", "img_convert", "img_grayscale"]:
        if file_ext not in [".jpg", ".jpeg", ".png"]:
            await update.message.reply_text("⚠️ Invalid file type! Please upload a JPG or PNG image.")
            session["files"].pop()
            return
        prompt_msg = await update.message.reply_text("⏳ Processing image upload...")
        await proceed_image_setup(prompt_msg, session, context)
        
    elif action in ["word2pdf", "ppt2pdf", "excel2pdf"]:
        # Ensure correct file type uploaded
        valid_extensions = {
            "word2pdf": [".docx", ".doc"],
            "ppt2pdf": [".pptx", ".ppt"],
            "excel2pdf": [".xlsx", ".xls"],
        }
        if file_ext not in valid_extensions[action]:
            await update.message.reply_text(f"⚠️ Invalid file type! Please upload a file with extensions: {', '.join(valid_extensions[action])}")
            session["files"].pop() # remove invalid file
            return
            
        # Proceed to layout selection
        prompt_msg = await update.message.reply_text("⏳ Processing file uploads...")
        await start_layout_config_flow(prompt_msg, session)
        
    elif action == "video2gif":
        valid_video_exts = [".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp"]
        if file_ext not in valid_video_exts:
            await update.message.reply_text("⚠️ Invalid file type! Please upload a video file.")
            session["files"].pop()
            return
        await update.message.reply_text("⏳ Processing video-to-GIF conversion...")
        await execute_operation(update.message, session, chat_id, user_id, context)
        
    elif action == "images2gif":
        if file_ext not in [".jpg", ".jpeg", ".png"]:
            await update.message.reply_text("⚠️ Invalid file type! Please upload a JPG or PNG image.")
            session["files"].pop()
            return
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🖼️ Generate GIF", callback_data="process:generate_gif_now"),
                InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
            ]
        ])
        await update.message.reply_text(
            f"🖼️ Frame received! Total frames: **{len(session['files'])}**.\nSend more images or click Generate GIF.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
    elif action == "excel_chart":
        if file_ext not in [".xlsx", ".xls", ".csv"]:
            await update.message.reply_text("⚠️ Invalid file type! Please upload an Excel (.xlsx, .xls) or CSV file.")
            session["files"].pop()
            return
            
        try:
            from chart_utils import parse_spreadsheet, get_numeric_and_text_cols
            headers, rows = parse_spreadsheet(local_path)
            num_cols, txt_cols = get_numeric_and_text_cols(headers, rows)
            
            if not headers:
                raise ValueError("No headers found.")
                
            x_guess = txt_cols[0] if txt_cols else headers[0]
            y_guess = None
            if num_cols:
                y_guess = num_cols[0]
            else:
                for h in headers:
                    if h != x_guess:
                        y_guess = h
                        break
                if not y_guess:
                    y_guess = headers[0]
                    
            session["chart_x"] = x_guess
            session["chart_y"] = y_guess
            
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📊 Bar Chart", callback_data="chart_type:bar"),
                    InlineKeyboardButton("📈 Line Chart", callback_data="chart_type:line"),
                ],
                [
                    InlineKeyboardButton("🍕 Pie Chart", callback_data="chart_type:pie"),
                    InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
                ]
            ])
            await update.message.reply_text(
                "📊 **Chart Generator**\n\n"
                f"📁 File: `{os.path.basename(local_path)}`\n"
                f"• **X-Axis (labels)**: `{x_guess}`\n"
                f"• **Y-Axis (values)**: `{y_guess}`\n\n"
                "Please choose the chart type to generate:",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Excel parsing error: {e}")
            await update.message.reply_text(f"❌ Error reading spreadsheet data: {e}")
            session["files"].pop()
            return
        
    elif action in ["pdf2word", "pdf2ppt", "pdf2excel", "pdf2images", "layout_settings", "split", "rotate", "pdf_compress", "pdf_encrypt", "pdf_decrypt", "pdf_watermark", "pdf_rem_watermark"]:
        if file_ext != ".pdf":
            await update.message.reply_text("⚠️ Invalid file type! Please upload a PDF file.")
            session["files"].pop()
            return
            
        if action == "pdf_encrypt":
            session["step"] = "waiting_for_encrypt_password"
            await update.message.reply_text("🔑 **Please enter the password** to lock/encrypt this PDF:")
        elif action == "pdf_decrypt":
            session["step"] = "waiting_for_decrypt_password"
            await update.message.reply_text("🔓 **Please enter the password** to unlock/decrypt this PDF:")
        elif action == "pdf_watermark":
            session["step"] = "waiting_for_watermark_text"
            await update.message.reply_text("✍️ **Please enter the text** for the diagonal watermark (e.g. `CONFIDENTIAL`, `DO NOT COPY`):")
        elif action == "pdf_rem_watermark":
            session["step"] = "waiting_for_remove_watermark_text"
            await update.message.reply_text("🧼 **Please enter the exact text** of the watermark you want to search and remove:")
        elif action == "layout_settings":
            prompt_msg = await update.message.reply_text("⏳ Processing PDF file...")
            await start_layout_config_flow(prompt_msg, session)
        elif action == "pdf_compress":
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🟢 Low (Lossless)", callback_data="compress_level:low"),
                    InlineKeyboardButton("🟡 Medium (60%)", callback_data="compress_level:medium"),
                ],
                [
                    InlineKeyboardButton("🔴 High (30% + Resize)", callback_data="compress_level:high"),
                ],
                [
                    InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel")
                ]
            ])
            await update.message.reply_text(
                "📉 **Choose PDF Compression Level**:\n\n"
                "• **Low**: Lossless cleanups (safe, small reduction)\n"
                "• **Medium**: Compresses photos inside to 60% quality (best balance)\n"
                "• **High**: Compresses photos to 30% and resizes large images (max size savings)",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        elif action == "split":
            session["step"] = "waiting_for_split_range"
            await update.message.reply_text(
                "🔢 **Split Range Configuration**\n\n"
                "Please type the page numbers or ranges to extract (e.g., `1, 3-5, 8`):\n"
                "Type /cancel to abort."
            )
        elif action == "rotate":
            keyboard = [
                [
                    InlineKeyboardButton("Rotate 90° ➡️", callback_data="rotate_angle:90"),
                    InlineKeyboardButton("Rotate 180° 🔄", callback_data="rotate_angle:180"),
                ],
                [
                    InlineKeyboardButton("Rotate 270° ⬅️", callback_data="rotate_angle:270"),
                    InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
                ]
            ]
            await update.message.reply_text(
                "🔄 **Rotation Configuration**\n\nChoose the rotation angle:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Immediate executions (pdf2word, pdf2ppt, pdf2excel, pdf2images)
            await update.message.reply_text("⏳ Processing document conversion...")
            # Create a mock query-like object or pass None, we can edit message or send message
            await execute_operation(update.message, session, chat_id, user_id, context)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_active_group_user(update)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    is_group = update.effective_chat.type in ["group", "supergroup"]
    logger.info(f"handle_photo: chat_id={chat_id}, user_id={user_id}")
    
    caption = update.message.caption or ""
    bot_username = context.bot.username
    bot_mention = f"@{bot_username}"
    is_mentioned = bot_mention.lower() in caption.lower()
    
    if is_group and is_mentioned:
        prompt = caption.lower().replace(bot_mention.lower(), "").strip()
        if prompt:
            photo = update.message.photo[-1]
            await start_replicate_from_photo_or_doc(update, context, photo.file_id, "photo.jpg", prompt)
            return
    elif not is_group and caption:
        session = USER_SESSIONS.get((chat_id, user_id))
        if not session or not session["action"]:
            photo = update.message.photo[-1]
            await start_replicate_from_photo_or_doc(update, context, photo.file_id, "photo.jpg", caption)
            return
            
    session = USER_SESSIONS.get((chat_id, user_id))
    
    if not session or not session["action"]:
        if is_group:
            return
        else:
            await update.message.reply_text("Please open the dashboard first using /start to select an action.")
            return
            
    if session["action"] in ["img_rotate", "img_resize", "img_compress", "img_convert", "img_grayscale"]:
        if session["step"] != "waiting_for_files":
            return
        await update.message.reply_chat_action("upload_document")
        try:
            photo = update.message.photo[-1]
            new_file = await context.bot.get_file(photo.file_id)
            local_path = os.path.join(session["temp_dir"], f"source_{photo.file_id[-8:]}.jpg")
            await new_file.download_to_drive(local_path)
            session["files"].append(local_path)
        except Exception as e:
            logger.error(f"Image download error: {e}")
            await update.message.reply_text("❌ Error downloading image.")
            return
        await proceed_image_setup(update.message, session, context)
        return

    if session["action"] not in ["images2pdf", "images2gif"] or session["step"] != "waiting_for_files":
        return
        
    await update.message.reply_chat_action("upload_document")
    try:
        photo = update.message.photo[-1] # Largest size
        new_file = await context.bot.get_file(photo.file_id)
        local_path = os.path.join(session["temp_dir"], f"image_{len(session['files'])}.jpg")
        await new_file.download_to_drive(local_path)
        session["files"].append(local_path)
    except Exception as e:
        logger.error(f"Image download error: {e}")
        await update.message.reply_text("❌ Error downloading image.")
        return
        
    if session["action"] == "images2gif":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🖼️ Generate GIF", callback_data="process:generate_gif_now"),
                InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
            ]
        ])
        await update.message.reply_text(
            f"🖼️ Image received! Total frames: **{len(session['files'])}**.\nSend more images or click Generate GIF.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ Convert Now", callback_data="process:convert_images"),
                InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
            ]
        ])
        await update.message.reply_text(
            f"🖼️ Image received! Total images: **{len(session['files'])}**.\nSend more images or click Convert Now.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

# --- Text Message Input Handler (Config States) ---

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_active_group_user(update)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.strip()
    logger.info(f"handle_text: chat_id={chat_id}, user_id={user_id}, text='{text}'")
    
    session = USER_SESSIONS.get((chat_id, user_id))
    
    # If no active document processing session, check for AI doubt-resolution queries
    if not session or not session["action"]:
        is_group = update.effective_chat.type in ["group", "supergroup"]
        bot_username = (await context.bot.get_me()).username
        bot_mention = f"@{bot_username}"
        
        # Check if they replied to a photo or document image!
        replied_msg = update.message.reply_to_message
        if replied_msg and (replied_msg.photo or replied_msg.document):
            is_mentioned = bot_mention.lower() in text.lower()
            should_edit = False
            prompt = text
            if not is_group:
                should_edit = True
            else:
                if is_mentioned:
                    should_edit = True
                    prompt = text.lower().replace(bot_mention.lower(), "").strip()
            
            if should_edit and prompt:
                target_photo_id = None
                file_name_hint = "photo.jpg"
                if replied_msg.photo:
                    target_photo_id = replied_msg.photo[-1].file_id
                elif replied_msg.document and is_doc_image(replied_msg.document):
                    target_photo_id = replied_msg.document.file_id
                    file_name_hint = replied_msg.document.file_name
                
                if target_photo_id:
                    await start_replicate_from_photo_or_doc(update, context, target_photo_id, file_name_hint, prompt)
                    return
        
        is_mentioned = bot_mention in text
        is_reply_to_bot = (
            update.message.reply_to_message 
            and update.message.reply_to_message.from_user.id == context.bot.id
        )
        
        should_respond_ai = False
        prompt = text
        
        if not is_group:
            should_respond_ai = True
        else:
            if is_mentioned:
                should_respond_ai = True
                prompt = text.replace(bot_mention, "").strip()
            elif is_reply_to_bot:
                should_respond_ai = True
                
        if should_respond_ai:
            if not GEMINI_API_KEY:
                await update.message.reply_text(
                    "⚠️ Google Gemini AI features are not configured on this bot.\n\n"
                    "Please get a Gemini API key and add it to your `.env` file:\n"
                    "`GEMINI_API_KEY=your_gemini_key` to activate this feature."
                )
                return
                
            if not prompt:
                await update.message.reply_text(
                    "👋 Hello! I am equipped with Google Gemini AI. "
                    "Ask me any question or clear your doubts directly!"
                )
                return
                
            await update.message.reply_chat_action("typing")
            try:
                import asyncio
                model = genai.GenerativeModel(GEMINI_MODEL)
                # Run the blocking Gemini API call in a thread pool executor to keep event loop responsive
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None, lambda: model.generate_content(prompt)
                )
                try:
                    await update.message.reply_text(response.text, parse_mode="Markdown")
                except Exception:
                    await update.message.reply_text(response.text)
            except Exception as e:
                logger.error(f"Gemini AI error: {e}")
                await update.message.reply_text(f"❌ Error communicating with Gemini AI: {str(e)}")
        return

    step = session["config_step"]
    action = session["action"]
    
    # 1. Check if waiting for Split Ranges
    if session["step"] == "waiting_for_split_range" and action == "split":
        session["split_range"] = text
        await update.message.reply_text(f"⏳ Extracting page range `{text}`...", parse_mode="Markdown")
        await execute_operation(update.message, session, chat_id, user_id, context)
        return

    if session["step"] == "waiting_for_encrypt_password" and action == "pdf_encrypt":
        session["encrypt_password"] = text
        await update.message.reply_text("⏳ Locking PDF with password...")
        await execute_operation(update.message, session, chat_id, user_id, context)
        return

    if session["step"] == "waiting_for_decrypt_password" and action == "pdf_decrypt":
        session["decrypt_password"] = text
        await update.message.reply_text("⏳ Unlocking PDF...")
        await execute_operation(update.message, session, chat_id, user_id, context)
        return

    if session["step"] == "waiting_for_watermark_text" and action == "pdf_watermark":
        session["watermark_text"] = text
        await update.message.reply_text(f"⏳ Overlaying watermark `{text}`...", parse_mode="Markdown")
        await execute_operation(update.message, session, chat_id, user_id, context)
        return

    if session["step"] == "waiting_for_remove_watermark_text" and action == "pdf_rem_watermark":
        session["remove_watermark_text"] = text
        await update.message.reply_text(f"⏳ Removing occurrences of watermark `{text}`...", parse_mode="Markdown")
        await execute_operation(update.message, session, chat_id, user_id, context)
        return

    # 1.5 Check if waiting for Custom Image Width
    if step == "ask_img_custom_width" and action == "img_resize":
        try:
            width = int(text)
            if width <= 0:
                raise ValueError
            session["img_resize_width"] = width
        except ValueError:
            await update.message.reply_text("⚠️ Please enter a valid positive integer for the width!")
            return
            
        await update.message.reply_text(f"⏳ Resizing photo to width {width}px...")
        await execute_image_operation(update.message, session, context)
        return

    # 2. Check if in Layout Settings Flow
    if step == "ask_header":
        if text.lower() == "/skip":
            session["config"]["header_text"] = None
        else:
            session["config"]["header_text"] = text
            
        session["config_step"] = "ask_footer"
        await update.message.reply_text("✍️ Please type the **Footer Text** to place at the bottom-left of each page (or click /skip if you don't want a footer).", parse_mode="Markdown")
        
    elif step == "ask_footer":
        if text.lower() == "/skip":
            session["config"]["footer_text"] = None
        else:
            session["config"]["footer_text"] = text
            
        session["config_step"] = "ask_start_num"
        await update.message.reply_text("🔢 Please enter the **Starting Page Number** (usually 1, or click /skip):", parse_mode="Markdown")
        
    elif step == "ask_start_num":
        if text.lower() == "/skip":
            session["config"]["start_page_num"] = 1
        else:
            try:
                session["config"]["start_page_num"] = int(text)
            except ValueError:
                await update.message.reply_text("⚠️ Please enter a valid integer for the page number!")
                return
                
        # Layout config is finished, run operation
        await update.message.reply_text("⏳ Processing and building document layout...")
        await execute_operation(update.message, session, chat_id, user_id, context)

# --- Core Execution Router ---

async def execute_operation(msg_or_query, session, chat_id, user_id, context):
    # helper to send message/update text
    async def notify(text):
        if hasattr(msg_or_query, "edit_message_text"):
            await msg_or_query.edit_message_text(text)
        else:
            await context.bot.send_message(chat_id, text)

    action = session["action"]
    files = session["files"]
    temp_dir = session["temp_dir"]
    
    if not files:
        await notify("❌ Error: No files were uploaded!")
        clear_session(chat_id, user_id)
        return
        
    output_filename = ""
    output_path = ""
    
    try:
        # Route conversions
        if action == "word2pdf":
            input_file = files[0]
            output_filename = os.path.splitext(os.path.basename(input_file))[0] + ".pdf"
            output_path = os.path.join(temp_dir, output_filename)
            await notify("⏳ Converting Word to PDF...")
            word_to_pdf(input_file, output_path)
            
        elif action == "pdf2word":
            input_file = files[0]
            output_filename = os.path.splitext(os.path.basename(input_file))[0] + ".docx"
            output_path = os.path.join(temp_dir, output_filename)
            await notify("⏳ Converting PDF to Word...")
            pdf_to_word(input_file, output_path)
            
        elif action == "ppt2pdf":
            input_file = files[0]
            output_filename = os.path.splitext(os.path.basename(input_file))[0] + ".pdf"
            output_path = os.path.join(temp_dir, output_filename)
            await notify("⏳ Converting PowerPoint to PDF...")
            ppt_to_pdf(input_file, output_path)
            
        elif action == "pdf2ppt":
            input_file = files[0]
            output_filename = os.path.splitext(os.path.basename(input_file))[0] + ".pptx"
            output_path = os.path.join(temp_dir, output_filename)
            await notify("⏳ Converting PDF to PowerPoint...")
            pdf_to_ppt(input_file, output_path)
            
        elif action == "excel2pdf":
            input_file = files[0]
            output_filename = os.path.splitext(os.path.basename(input_file))[0] + ".pdf"
            output_path = os.path.join(temp_dir, output_filename)
            await notify("⏳ Converting Excel to PDF...")
            excel_to_pdf(input_file, output_path)
            
        elif action == "pdf2excel":
            input_file = files[0]
            output_filename = os.path.splitext(os.path.basename(input_file))[0] + ".xlsx"
            output_path = os.path.join(temp_dir, output_filename)
            await notify("⏳ Extracting PDF Tables to Excel...")
            pdf_to_excel(input_file, output_path)
            
        elif action == "merge":
            output_filename = "merged_document.pdf"
            output_path = os.path.join(temp_dir, output_filename)
            await notify("⏳ Merging PDF files...")
            merge_pdfs(files, output_path)
            
        elif action == "images2pdf":
            output_filename = "converted_images.pdf"
            output_path = os.path.join(temp_dir, output_filename)
            await notify("⏳ Converting images to PDF...")
            images_to_pdf(files, output_path)
            
        elif action == "split":
            input_file = files[0]
            output_filename = "split_" + os.path.basename(input_file)
            output_path = os.path.join(temp_dir, output_filename)
            split_pdf(input_file, session["split_range"], output_path)
            
        elif action == "rotate":
            input_file = files[0]
            output_filename = "rotated_" + os.path.basename(input_file)
            output_path = os.path.join(temp_dir, output_filename)
            rotate_pdf(input_file, session["rotation_angle"], output_path)
            
        elif action == "layout_settings":
            # Just copy file to output, we will run overlay on it next
            input_file = files[0]
            output_filename = "configured_" + os.path.basename(input_file)
            output_path = os.path.join(temp_dir, output_filename)
            shutil.copy(input_file, output_path)
            
        elif action == "pdf_compress":
            input_file = files[0]
            level = session.get("compress_level", "medium")
            output_filename = "compressed_" + os.path.basename(input_file)
            output_path = os.path.join(temp_dir, output_filename)
            await notify(f"⏳ Compressing PDF (level: `{level}`)...")
            from compress_utils import compress_pdf
            compress_pdf(input_file, output_path, level=level)
            
        elif action == "pdf_encrypt":
            input_file = files[0]
            password = session.get("encrypt_password")
            output_filename = "locked_" + os.path.basename(input_file)
            output_path = os.path.join(temp_dir, output_filename)
            await notify("⏳ Locking PDF with password...")
            from security_utils import encrypt_pdf
            encrypt_pdf(input_file, output_path, password)
            
        elif action == "pdf_decrypt":
            input_file = files[0]
            password = session.get("decrypt_password")
            output_filename = "unlocked_" + os.path.basename(input_file)
            output_path = os.path.join(temp_dir, output_filename)
            await notify("⏳ Decrypting PDF...")
            from security_utils import decrypt_pdf
            try:
                decrypt_pdf(input_file, output_path, password)
            except Exception as err:
                await notify(f"❌ Decryption failed: {err}")
                clear_session(chat_id, user_id)
                return
                
        elif action == "pdf_watermark":
            input_file = files[0]
            watermark_text = session.get("watermark_text")
            output_filename = "watermarked_" + os.path.basename(input_file)
            output_path = os.path.join(temp_dir, output_filename)
            await notify("⏳ Adding watermark to PDF...")
            from watermark_utils import add_pdf_watermark
            add_pdf_watermark(input_file, output_path, watermark_text)
            
        elif action == "pdf_rem_watermark":
            input_file = files[0]
            watermark_text = session.get("remove_watermark_text")
            output_filename = "cleared_" + os.path.basename(input_file)
            output_path = os.path.join(temp_dir, output_filename)
            await notify(f"⏳ Removing watermark `{watermark_text}`...")
            from watermark_utils import remove_pdf_watermark
            remove_pdf_watermark(input_file, output_path, watermark_text)
            
        elif action == "excel_chart":
            input_file = files[0]
            chart_type = session.get("chart_type", "bar")
            x_col = session.get("chart_x")
            y_col = session.get("chart_y")
            output_filename = "chart.png"
            output_path = os.path.join(temp_dir, output_filename)
            await notify("⏳ Plotting chart from spreadsheet...")
            from chart_utils import generate_chart
            import asyncio
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, lambda: generate_chart(input_file, chart_type, output_path, x_col, y_col))
            except Exception as err:
                await notify(f"❌ Error generating chart: {err}")
                clear_session(chat_id, user_id)
                return
                
            await notify("📤 Sending generated chart back to you...")
            with open(output_path, "rb") as f:
                await context.bot.send_photo(chat_id, f, caption=f"📊 `{chart_type.upper()}` chart: {y_col} by {x_col}")
            clear_session(chat_id, user_id)
            return
            
        elif action == "video2gif":
            input_file = files[0]
            output_filename = os.path.splitext(os.path.basename(input_file))[0] + ".gif"
            output_path = os.path.join(temp_dir, output_filename)
            await notify("⏳ Converting video to GIF...")
            from gif_utils import video_to_gif
            import asyncio
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: video_to_gif(input_file, output_path))
            
            await notify("📤 Sending animation back to you...")
            with open(output_path, "rb") as f:
                await context.bot.send_animation(chat_id, f, filename=output_filename, caption="🎞️ Converted Video to Animated GIF!")
            clear_session(chat_id, user_id)
            return
            
        elif action == "images2gif":
            output_filename = "animated_images.gif"
            output_path = os.path.join(temp_dir, output_filename)
            await notify("⏳ Combining images to GIF...")
            from gif_utils import images_to_gif
            images_to_gif(files, output_path, duration=500)
            
            await notify("📤 Sending animation back to you...")
            with open(output_path, "rb") as f:
                await context.bot.send_animation(chat_id, f, filename=output_filename, caption="🖼️ Combined Images to Animated GIF!")
            clear_session(chat_id, user_id)
            return
            
        elif action == "ppt2images":
            input_file = files[0]
            output_subdir = os.path.join(temp_dir, "ppt_slides")
            await notify("⏳ Converting slides to images...")
            slide_images = ppt_to_images(input_file, output_subdir)
            
            # Send images as a ZIP file or media group
            if not slide_images:
                await notify("❌ Error: No slides found in PowerPoint presentation.")
                clear_session(chat_id, user_id)
                return
                
            # Create a zip of slides
            zip_filename = os.path.splitext(os.path.basename(input_file))[0] + "_slides.zip"
            zip_path = os.path.join(temp_dir, zip_filename)
            # Create zip archive
            shutil.make_archive(os.path.join(temp_dir, os.path.splitext(zip_filename)[0]), 'zip', output_subdir)
            
            await notify("📤 Sending slides package...")
            with open(zip_path, "rb") as f:
                await context.bot.send_document(chat_id, f, filename=zip_filename, caption="🖼️ PowerPoint Slides as PNG Images")
            clear_session(chat_id, user_id)
            return
            
        elif action == "pdf2images":
            input_file = files[0]
            output_subdir = os.path.join(temp_dir, "pdf_pages")
            await notify("⏳ Exporting PDF pages to images...")
            page_images = pdf_to_images(input_file, output_subdir)
            
            if not page_images:
                await notify("❌ Error exporting pages.")
                clear_session(chat_id, user_id)
                return
                
            zip_filename = os.path.splitext(os.path.basename(input_file))[0] + "_pages.zip"
            zip_path = os.path.join(temp_dir, zip_filename)
            shutil.make_archive(os.path.join(temp_dir, os.path.splitext(zip_filename)[0]), 'zip', output_subdir)
            
            await notify("📤 Sending pages package...")
            with open(zip_path, "rb") as f:
                await context.bot.send_document(chat_id, f, filename=zip_filename, caption="🖼️ PDF Pages as PNG Images")
            clear_session(chat_id, user_id)
            return
            
        # Post-process with Layout settings if applicable
        # Applicable actions that result in a PDF output
        pdf_producing_actions = ["word2pdf", "ppt2pdf", "excel2pdf", "merge", "images2pdf", "layout_settings"]
        if action in pdf_producing_actions:
            cfg = session["config"]
            if cfg["add_page_numbers"] or cfg["header_text"] or cfg["footer_text"]:
                await notify("✏️ Overlaying headers, footers, and page numbers...")
                decorated_filename = "styled_" + output_filename
                decorated_path = os.path.join(temp_dir, decorated_filename)
                
                add_header_footer_page_numbers(
                    pdf_path=output_path,
                    output_path=decorated_path,
                    header_text=cfg["header_text"],
                    footer_text=cfg["footer_text"],
                    add_page_numbers=cfg["add_page_numbers"],
                    start_page_num=cfg["start_page_num"],
                    exclude_first_page=cfg["exclude_first_page"]
                )
                output_path = decorated_path
                output_filename = decorated_filename

        # Send back the document
        await notify("📤 Sending result back to you...")
        with open(output_path, "rb") as f:
            await context.bot.send_document(chat_id, f, filename=output_filename, caption="✅ Processing completed successfully without watermarks!")
            
    except Exception as e:
        logger.error(f"Execution error for action {action}: {e}", exc_info=True)
        await notify(f"❌ An error occurred during conversion: {str(e)}")
    finally:
        clear_session(chat_id, user_id)

# --- Main Entry Point ---

async def post_init(application):
    commands = [
        BotCommand("start", "Open the main dashboard menu"),
        BotCommand("help", "Show help guide and group usage details"),
        BotCommand("cancel", "Cancel current active operation"),
        BotCommand("merge", "Merge multiple PDF files into one"),
        BotCommand("split", "Extract pages from a PDF document"),
        BotCommand("rotate", "Rotate pages of a PDF document"),
        BotCommand("layout", "Add Header, Footer, and Page Numbers"),
        BotCommand("word_to_pdf", "Convert Word document to PDF"),
        BotCommand("pdf_to_word", "Convert PDF document to Word"),
        BotCommand("ppt_to_pdf", "Convert PowerPoint to PDF"),
        BotCommand("pdf_to_ppt", "Convert PDF document to PowerPoint"),
        BotCommand("excel_to_pdf", "Convert Excel spreadsheet to PDF"),
        BotCommand("pdf_to_excel", "Convert PDF document to Excel"),
        BotCommand("ppt_to_images", "Convert PPT slides to ZIP images"),
        BotCommand("pdf_to_images", "Convert PDF pages to ZIP images"),
        BotCommand("images_to_pdf", "Combine multiple images into a PDF"),
        BotCommand("img_rotate", "Rotate an image (90, 180, 270)"),
        BotCommand("img_resize", "Resize image dimensions"),
        BotCommand("img_compress", "Compress image file size"),
        BotCommand("img_convert", "Convert format (JPG/PNG)"),
        BotCommand("img_grayscale", "Convert image to grayscale"),
        BotCommand("generate", "Generate an image using active AI model"),
        BotCommand("set_model", "Change Replicate image gen and edit models"),
        BotCommand("pdf_compress", "Compress PDF document file size"),
        BotCommand("meme", "Overlay text on photo to generate a meme"),
        BotCommand("download", "Download social media videos (YouTube, TikTok, etc.)"),
        BotCommand("choose", "Randomly select one option from a list or pick active member"),
        BotCommand("members", "View list of active group members in the decision pool"),
        BotCommand("trivia", "Start a group AI quiz poll game"),
        BotCommand("video_to_gif", "Convert a video clip into animated GIF"),
        BotCommand("images_to_gif", "Combine multiple images into animated GIF"),
        BotCommand("ocr", "Extract text from textbook pages / photos"),
        BotCommand("remove_watermark", "Search and remove specific text watermark from PDF"),
        BotCommand("avatar", "Stylize a face portrait into Claymation, Pixel Art, 3D, etc."),
        BotCommand("music", "Generate 10s custom AI lofi/music beats from text prompt"),
        BotCommand("seminar", "Create full Seminar PowerPoint slides & Word Report from topic"),
        BotCommand("website", "Antigravity AI: Create interactive web page / HTML app from prompt"),
        BotCommand("code", "Antigravity AI: Audit code, debug error traces & optimize performance"),
        BotCommand("summarize", "Antigravity AI: Read webpage URL / article & extract key takeaways"),
        BotCommand("upscale", "Upscale low-res photo to high-res 4K image"),
        BotCommand("tts", "Convert text to speech/voice note using Suno Bark"),
    ]
    await application.bot.set_my_commands(commands)

def main():
    builder = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init)
    if PROXY_URL:
        builder.proxy(PROXY_URL)
    app = builder.build()
    
    # Register command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("generate", generate_command))
    app.add_handler(CommandHandler("generate_image", generate_command))
    app.add_handler(CommandHandler("set_model", set_model_command))
    app.add_handler(CommandHandler("meme", meme_command))
    app.add_handler(CommandHandler("download", download_command))
    app.add_handler(CommandHandler("dl", download_command))
    app.add_handler(CommandHandler("choose", choose_command))
    app.add_handler(CommandHandler("members", active_members_command))
    app.add_handler(CommandHandler("active", active_members_command))
    app.add_handler(CommandHandler("trivia", trivia_command))
    app.add_handler(CommandHandler("ocr", ocr_command))
    app.add_handler(CommandHandler("avatar", stylize_command))
    app.add_handler(CommandHandler("stylize", stylize_command))
    app.add_handler(CommandHandler("music", music_command))
    app.add_handler(CommandHandler("generate_music", music_command))
    app.add_handler(CommandHandler("seminar", seminar_command))
    app.add_handler(CommandHandler("create_seminar", seminar_command))
    app.add_handler(CommandHandler("website", webapp_command))
    app.add_handler(CommandHandler("webapp", webapp_command))
    app.add_handler(CommandHandler("code", code_command))
    app.add_handler(CommandHandler("debug", code_command))
    app.add_handler(CommandHandler("summarize", summarize_command))
    app.add_handler(CommandHandler("upscale", upscale_command))
    app.add_handler(CommandHandler("tts", tts_command))
    app.add_handler(CommandHandler("speak", tts_command))
    
    # Generic action commands registration
    async def cmd_merge(u, c): await start_action_command(u, c, "merge")
    async def cmd_split(u, c): await start_action_command(u, c, "split")
    async def cmd_rotate(u, c): await start_action_command(u, c, "rotate")
    async def cmd_layout(u, c): await start_action_command(u, c, "layout_settings")
    async def cmd_word2pdf(u, c): await start_action_command(u, c, "word2pdf")
    async def cmd_pdf2word(u, c): await start_action_command(u, c, "pdf2word")
    async def cmd_ppt2pdf(u, c): await start_action_command(u, c, "ppt2pdf")
    async def cmd_pdf2ppt(u, c): await start_action_command(u, c, "pdf2ppt")
    async def cmd_excel2pdf(u, c): await start_action_command(u, c, "excel2pdf")
    async def cmd_pdf2excel(u, c): await start_action_command(u, c, "pdf2excel")
    async def cmd_ppt2images(u, c): await start_action_command(u, c, "ppt2images")
    async def cmd_pdf2images(u, c): await start_action_command(u, c, "pdf2images")
    async def cmd_images2pdf(u, c): await start_action_command(u, c, "images2pdf")
    async def cmd_img_rotate(u, c): await start_action_command(u, c, "img_rotate")
    async def cmd_img_resize(u, c): await start_action_command(u, c, "img_resize")
    async def cmd_img_compress(u, c): await start_action_command(u, c, "img_compress")
    async def cmd_img_convert(u, c): await start_action_command(u, c, "img_convert")
    async def cmd_img_grayscale(u, c): await start_action_command(u, c, "img_grayscale")
    async def cmd_pdf_compress(u, c): await start_action_command(u, c, "pdf_compress")
    async def cmd_video2gif(u, c): await start_action_command(u, c, "video2gif")
    async def cmd_images2gif(u, c): await start_action_command(u, c, "images2gif")
    async def cmd_pdf_encrypt(u, c): await start_action_command(u, c, "pdf_encrypt")
    async def cmd_pdf_decrypt(u, c): await start_action_command(u, c, "pdf_decrypt")
    async def cmd_pdf_watermark(u, c): await start_action_command(u, c, "pdf_watermark")
    async def cmd_pdf_rem_watermark(u, c): await start_action_command(u, c, "pdf_rem_watermark")
    async def cmd_excel_chart(u, c): await start_action_command(u, c, "excel_chart")

    app.add_handler(CommandHandler("merge", cmd_merge))
    app.add_handler(CommandHandler("split", cmd_split))
    app.add_handler(CommandHandler("rotate", cmd_rotate))
    app.add_handler(CommandHandler("layout", cmd_layout))
    app.add_handler(CommandHandler("layout_settings", cmd_layout))
    app.add_handler(CommandHandler("pdf_compress", cmd_pdf_compress))
    app.add_handler(CommandHandler("compress", cmd_pdf_compress))
    app.add_handler(CommandHandler("video_to_gif", cmd_video2gif))
    app.add_handler(CommandHandler("video2gif", cmd_video2gif))
    app.add_handler(CommandHandler("images_to_gif", cmd_images2gif))
    app.add_handler(CommandHandler("images2gif", cmd_images2gif))
    app.add_handler(CommandHandler("lock_pdf", cmd_pdf_encrypt))
    app.add_handler(CommandHandler("lock", cmd_pdf_encrypt))
    app.add_handler(CommandHandler("unlock_pdf", cmd_pdf_decrypt))
    app.add_handler(CommandHandler("unlock", cmd_pdf_decrypt))
    app.add_handler(CommandHandler("watermark_pdf", cmd_pdf_watermark))
    app.add_handler(CommandHandler("watermark", cmd_pdf_watermark))
    app.add_handler(CommandHandler("remove_watermark", cmd_pdf_rem_watermark))
    app.add_handler(CommandHandler("rem_watermark", cmd_pdf_rem_watermark))
    app.add_handler(CommandHandler("excel_chart", cmd_excel_chart))
    app.add_handler(CommandHandler("chart", cmd_excel_chart))
    
    app.add_handler(CommandHandler("word2pdf", cmd_word2pdf))
    app.add_handler(CommandHandler("word_to_pdf", cmd_word2pdf))
    app.add_handler(CommandHandler("pdf2word", cmd_pdf2word))
    app.add_handler(CommandHandler("pdf_to_word", cmd_pdf2word))
    
    app.add_handler(CommandHandler("ppt2pdf", cmd_ppt2pdf))
    app.add_handler(CommandHandler("ppt_to_pdf", cmd_ppt2pdf))
    app.add_handler(CommandHandler("pdf2ppt", cmd_pdf2ppt))
    app.add_handler(CommandHandler("pdf_to_ppt", cmd_pdf2ppt))
    
    app.add_handler(CommandHandler("excel2pdf", cmd_excel2pdf))
    app.add_handler(CommandHandler("excel_to_pdf", cmd_excel2pdf))
    app.add_handler(CommandHandler("pdf2excel", cmd_pdf2excel))
    app.add_handler(CommandHandler("pdf_to_excel", cmd_pdf2excel))
    
    app.add_handler(CommandHandler("ppt2images", cmd_ppt2images))
    app.add_handler(CommandHandler("ppt_to_images", cmd_ppt2images))
    app.add_handler(CommandHandler("pdf2images", cmd_pdf2images))
    app.add_handler(CommandHandler("pdf_to_images", cmd_pdf2images))
    
    app.add_handler(CommandHandler("images2pdf", cmd_images2pdf))
    app.add_handler(CommandHandler("images_to_pdf", cmd_images2pdf))
    
    app.add_handler(CommandHandler("img_rotate", cmd_img_rotate))
    app.add_handler(CommandHandler("img_resize", cmd_img_resize))
    app.add_handler(CommandHandler("img_compress", cmd_img_compress))
    app.add_handler(CommandHandler("img_convert", cmd_img_convert))
    app.add_handler(CommandHandler("img_grayscale", cmd_img_grayscale))
    
    # Register callback query handler for menus and inline buttons
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    # Register document and photo message handlers
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO, handle_document))
    app.add_handler(MessageHandler(filters.ANIMATION, handle_document))
    
    # Register text inputs for layout text setups and split ranges
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Start background HTTP health check server for Render / Koyeb 100% Free Web Service hosting
    def start_dummy_health_check_server():
        import threading
        from http.server import HTTPServer, BaseHTTPRequestHandler

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Telegram Bot is running 24/7!")

            def log_message(self, format, *args):
                pass

        port = int(os.getenv("PORT", "10000"))
        try:
            server = HTTPServer(("0.0.0.0", port), HealthHandler)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            logger.info(f"Health check HTTP server listening on port {port}")
        except Exception as e:
            logger.warning(f"Could not start dummy health check server: {e}")

    start_dummy_health_check_server()
    
    logger.info("Bot started successfully in polling mode. Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    import sys
    main()

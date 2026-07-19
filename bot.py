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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

CURRENT_IMAGE_MODEL = "black-forest-labs/flux-1.1-pro"
CURRENT_EDIT_MODEL = "timothybrooks/instruct-pix2pix"

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)



# In-memory user sessions tracking: key=(chat_id, user_id), value=dict
USER_SESSIONS = {}

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
        
    msg = await update.message.reply_text("⏳ Initializing Replicate image generation...")
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
        "• `/watermark` - Add a transparent watermark to a PDF\n\n"
        "🔄 **Office Conversions (Watermark-Free)**:\n"
        "• `/word_to_pdf` - Convert Word to PDF\n"
        "• `/pdf_to_word` - Convert PDF to Word\n"
        "• `/ppt_to_pdf` - Convert PowerPoint to PDF\n"
        "• `/pdf_to_ppt` - Convert PDF to PowerPoint\n"
        "• `/excel_to_pdf` - Convert Excel to PDF\n"
        "• `/pdf_to_excel` - Convert PDF to Excel\n"
        "• `/chart` - Generate Bar/Line/Pie charts from Excel/CSV\n\n"
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
        "• **Prompt Editing**: Reply to any photo (or upload with caption) and mention the bot with an edit instruction (e.g. `@pptpdf_bot blur background`)\n"
        "• `/meme Top Text | Bottom Text` - Overlay text on image to make a meme\n\n"
        "🎲 **Group Games & Social Tools**:\n"
        "• `/download <link>` - Download videos from YouTube, TikTok, Reels, etc.\n"
        "• `/choose <options>` - Randomly pick an option from a list\n"
        "• `/trivia` - Start a Gemini AI-powered quiz poll in the group\n\n"
        "🤖 **Google Gemini AI**:\n"
        "• Direct DM: Send any text message to chat directly.\n"
        "• Group Chats: Mention the bot (e.g. `@pptpdf_bot question`) or reply to any bot message.\n\n"
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
    input_text = " ".join(context.args) if context.args else ""
    
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
        "merge": "🔗 **Merge PDFs**\nPlease upload **multiple PDF files** one by one. Once you are done, click the **Merge Now** button below.",
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
            "merge": "🔗 **Merge PDFs**\nPlease upload **multiple PDF files** one by one. Once you are done, click the **Merge Now** button below.",
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
    msg = await update.message.reply_text("⏳ Downloading image for AI editing...")
    
    try:
        new_file = await context.bot.get_file(file_id)
        temp_dir = tempfile.mkdtemp()
        local_path = os.path.join(temp_dir, f"source_{file_name_hint}")
        await new_file.download_to_drive(local_path)
        
        await edit_image_with_replicate(chat_id, local_path, prompt, msg, context)
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as e:
        logger.error(f"start_replicate_from_photo_or_doc error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Error downloading image: {e}")

async def edit_image_with_replicate(chat_id, src_path, prompt, update_msg, context):
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)
    token = os.getenv("REPLICATE_API_TOKEN", "").strip()
    if not token:
        await update_msg.edit_text(
            "⚠️ **Replicate API Token is not configured!**\n\n"
            "To use conversational image editing via prompts, please obtain a free/cheap API token from [Replicate](https://replicate.com) and add it to your `.env` file:\n"
            "`REPLICATE_API_TOKEN=r8_your_token_here`"
        )
        return

    await update_msg.edit_text("⏳ Preparing image for AI processing...")
    
    try:
        import base64
        import httpx
        import asyncio
        
        # Convert local image to base64 Data URI
        with open(src_path, "rb") as f:
            encoded_data = base64.b64encode(f.read()).decode("utf-8")
        
        file_ext = os.path.splitext(src_path)[1].lower()
        mime_type = "image/png" if file_ext == ".png" else "image/jpeg"
        data_uri = f"data:{mime_type};base64,{encoded_data}"
        
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
            
        await update_msg.edit_text("🚀 Sending request to Replicate AI...")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(
                req_url, 
                json=payload, 
                headers=headers
            )
            if res.status_code != 201:
                error_detail = res.json().get("detail", res.text)
                await update_msg.edit_text(f"❌ Replicate API Error: {error_detail}")
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
                        await context.bot.send_document(
                            chat_id, 
                            f_send, 
                            filename=out_filename, 
                            caption=f"✅ Image edited via prompt: *{prompt}*",
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

async def generate_image_with_replicate(chat_id, prompt, update_msg, context):
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)
    token = os.getenv("REPLICATE_API_TOKEN", "").strip()
    if not token:
        await update_msg.edit_text(
            "⚠️ **Replicate API Token is not configured!**\n\n"
            "Please obtain an API token from [Replicate](https://replicate.com) and add it to your `.env` file:\n"
            "`REPLICATE_API_TOKEN=r8_your_token_here`"
        )
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
                error_detail = res.json().get("detail", res.text)
                await update_msg.edit_text(f"❌ Replicate API Error: {error_detail}")
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
                        await update_msg.edit_text("❌ No output image received from Replicate.")
                        return
                    
                    output_url = output_urls[0] if isinstance(output_urls, list) else output_urls
                    await update_msg.edit_text("📤 Downloading generated image...")
                    img_res = await client.get(output_url)
                    if img_res.status_code != 200:
                        await update_msg.edit_text("❌ Error downloading generated image.")
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
                            caption=f"✅ Generated via `{CURRENT_IMAGE_MODEL}`:\n*{prompt}*",
                            parse_mode="Markdown"
                        )
                    await update_msg.delete()
                    return
                elif status == "failed":
                    await update_msg.edit_text(f"❌ Image generation failed: {prediction.get('error', 'unknown error')}")
                    return
                elif status == "canceled":
                    await update_msg.edit_text("❌ Image generation was canceled.")
                    return
            
            await update_msg.edit_text("⏱️ Image generation timed out on Replicate.")
            
    except Exception as e:
        logger.error(f"Replicate API connection error: {e}", exc_info=True)
        await update_msg.edit_text(f"❌ Error communicating with Replicate: {str(e)}")

# --- File Message Handling ---

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        # Let user know we received it, show Merge Now trigger
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔗 Merge Now", callback_data="process:merge_now"),
                InlineKeyboardButton("❌ Cancel", callback_data="btn:cancel"),
            ]
        ])
        await update.message.reply_text(
            f"📥 Received `{file_name}`.\n\nTotal files to merge: **{len(session['files'])}**.\nUpload another PDF or click Merge Now.",
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
                await update.message.reply_text(response.text, parse_mode="Markdown")
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
        BotCommand("choose", "Randomly select one option from a list"),
        BotCommand("trivia", "Start a group AI quiz poll game"),
        BotCommand("video_to_gif", "Convert a video clip into animated GIF"),
        BotCommand("images_to_gif", "Combine multiple images into animated GIF"),
        BotCommand("ocr", "Extract text from textbook pages / photos"),
        BotCommand("remove_watermark", "Search and remove specific text watermark from PDF"),
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
    app.add_handler(CommandHandler("trivia", trivia_command))
    app.add_handler(CommandHandler("ocr", ocr_command))
    
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
    
    logger.info("Bot started successfully in polling mode. Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    import sys
    main()

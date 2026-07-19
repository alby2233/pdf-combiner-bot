import os
import shutil
import tempfile
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv

# Import our utility functions
from pdf_utils import (
    word_to_pdf, pdf_to_word,
    ppt_to_pdf, pdf_to_ppt,
    excel_to_pdf, pdf_to_excel,
    add_header_footer_page_numbers,
    merge_pdfs, split_pdf, rotate_pdf,
    ppt_to_images, pdf_to_images, images_to_pdf
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# In-memory user sessions tracking: key=(chat_id, user_id), value=dict
USER_SESSIONS = {}

def get_session(chat_id, user_id):
    key = (chat_id, user_id)
    if key not in USER_SESSIONS:
        USER_SESSIONS[key] = {
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
            InlineKeyboardButton("❌ Cancel Operation", callback_data="btn:cancel")
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

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "💡 **PDF & Office Bot Help**\n\n"
        "• Use `/start` to open the main dashboard.\n"
        "• Use `/cancel` at any time to abort the current operation.\n\n"
        "👥 **Group Chat Usage**:\n"
        "To use this bot in groups, simply call it using commands (e.g. `/merge`, `/word2pdf`, `/start`) or mention the bot. "
        "The bot will ignore files uploaded by other group members unless they have initialized a command session, preventing spam."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    clear_session(chat_id, user_id)
    await update.message.reply_text("❌ Current operation has been cancelled. Use /start to open the dashboard again.")

# --- Callback Queries (Buttons) ---

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    data = query.data
    
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

# --- File Message Handling ---

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    is_group = update.effective_chat.type in ["group", "supergroup"]
    
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
        
    doc = update.message.document
    file_ext = os.path.splitext(doc.file_name)[1].lower() if doc.file_name else ""
    
    # Download the document
    await update.message.reply_chat_action("upload_document")
    try:
        new_file = await context.bot.get_file(doc.file_id)
        local_path = os.path.join(session["temp_dir"], doc.file_name)
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
            f"📥 Received `{doc.file_name}`.\n\nTotal files to merge: **{len(session['files'])}**.\nUpload another PDF or click Merge Now.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
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
        
    elif action in ["pdf2word", "pdf2ppt", "pdf2excel", "pdf2images", "layout_settings", "split", "rotate"]:
        if file_ext != ".pdf":
            await update.message.reply_text("⚠️ Invalid file type! Please upload a PDF file.")
            session["files"].pop()
            return
            
        if action == "layout_settings":
            prompt_msg = await update.message.reply_text("⏳ Processing PDF file...")
            await start_layout_config_flow(prompt_msg, session)
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
    
    session = USER_SESSIONS.get((chat_id, user_id))
    
    if not session or not session["action"]:
        if is_group:
            return
        else:
            await update.message.reply_text("Please open the dashboard first using /start to select an action.")
            return
            
    if session["action"] != "images2pdf" or session["step"] != "waiting_for_files":
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
    
    session = USER_SESSIONS.get((chat_id, user_id))
    if not session or not session["action"]:
        return # Ignore random texts

    step = session["config_step"]
    action = session["action"]
    
    # 1. Check if waiting for Split Ranges
    if session["step"] == "waiting_for_split_range" and action == "split":
        session["split_range"] = text
        await update.message.reply_text(f"⏳ Extracting page range `{text}`...", parse_mode="Markdown")
        await execute_operation(update.message, session, chat_id, user_id, context)
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

def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.critical("Error: TELEGRAM_BOT_TOKEN not found in environment variables. Please check your .env file.")
        sys.exit(1)
        
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Register command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    
    # Register callback query handler for menus and inline buttons
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    # Register document and photo message handlers
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Register text inputs for layout text setups and split ranges
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("Bot started successfully in polling mode. Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    import sys
    main()

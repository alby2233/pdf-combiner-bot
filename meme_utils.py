from PIL import Image, ImageDraw, ImageFont, ImageOps
import os

def generate_meme(image_path, top_text, bottom_text, output_path):
    """
    Generates a meme by overlaying top and bottom text on an image.
    Text is converted to uppercase and drawn with a thick black outline.
    """
    img = Image.open(image_path)
    
    # Handle image rotation EXIF tags if present
    img = ImageOps.exif_transpose(img)
    
    # Convert RGBA to RGB for standard format output
    if img.mode != "RGB":
        img = img.convert("RGB")
        
    width, height = img.size
    draw = ImageDraw.Draw(img)
    
    # Locate a suitable system font
    possible_fonts = [
        "C:\\Windows\\Fonts\\Impact.ttf",
        "C:\\Windows\\Fonts\\Arial.ttf",
        "C:\\Windows\\Fonts\\tahoma.ttf",
        "arial.ttf"
    ]
    font_path = None
    for p in possible_fonts:
        if os.path.exists(p) or p == "arial.ttf":
            try:
                # Test load
                ImageFont.truetype(p, 20)
                font_path = p
                break
            except Exception:
                continue
                
    # Standard base font size is 8% of image height
    base_font_size = max(20, int(height * 0.08))
    
    def get_font_and_lines(text, max_w):
        # Dynamically scale font size down if it wraps too much or overflows
        f_size = base_font_size
        while f_size > 12:
            try:
                font = ImageFont.truetype(font_path, f_size) if font_path else ImageFont.load_default()
            except Exception:
                font = ImageFont.load_default()
            
            # Wrap text
            lines = []
            words = text.split()
            curr = []
            for w in words:
                test = " ".join(curr + [w])
                if font_path:
                    bbox = draw.textbbox((0, 0), test, font=font)
                    w_line = bbox[2] - bbox[0]
                else:
                    w_line = len(test) * 6 # crude fallback
                if w_line <= max_w:
                    curr.append(w)
                else:
                    if curr:
                        lines.append(" ".join(curr))
                        curr = [w]
                    else:
                        lines.append(w)
            if curr:
                lines.append(" ".join(curr))
                
            # If we fit in 3 lines or less, we use this font size!
            if len(lines) <= 3:
                return font, lines
            f_size -= 4
        # fallback
        try:
            return ImageFont.truetype(font_path, 12) if font_path else ImageFont.load_default(), [text]
        except Exception:
            return ImageFont.load_default(), [text]

    # Draw helper
    def draw_text_lines(lines, font, is_top=True):
        margin = int(height * 0.03)
        outline_color = "black"
        fill_color = "white"
        thickness = max(1, int(base_font_size * 0.08))
        
        # Calculate line height
        if font_path:
            bbox = draw.textbbox((0, 0), "Ay", font=font)
            line_height = (bbox[3] - bbox[1]) + 5
        else:
            line_height = 15
            
        total_h = line_height * len(lines)
        
        if is_top:
            start_y = margin
        else:
            start_y = height - total_h - margin
            
        for i, line in enumerate(lines):
            y = start_y + (i * line_height)
            if font_path:
                bbox = draw.textbbox((0, 0), line, font=font)
                w_line = bbox[2] - bbox[0]
            else:
                w_line = len(line) * 6
                
            x = (width - w_line) // 2
            
            # Draw black outline
            for dx in range(-thickness, thickness + 1):
                for dy in range(-thickness, thickness + 1):
                    if dx*dx + dy*dy <= thickness*thickness: # smooth outline circle
                        draw.text((x + dx, y + dy), line, font=font, fill=outline_color)
            # Draw white fill
            draw.text((x, y), line, font=font, fill=fill_color)

    # Process Top text
    if top_text and top_text.strip():
        top_font, top_lines = get_font_and_lines(top_text.upper().strip(), int(width * 0.9))
        draw_text_lines(top_lines, top_font, is_top=True)
        
    # Process Bottom text
    if bottom_text and bottom_text.strip():
        bot_font, bot_lines = get_font_and_lines(bottom_text.upper().strip(), int(width * 0.9))
        draw_text_lines(bot_lines, bot_font, is_top=False)
        
    img.save(output_path, format="JPEG", quality=90)

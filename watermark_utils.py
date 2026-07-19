import fitz
import os
import tempfile
from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color

def create_watermark_pdf(output_path, text, page_width, page_height):
    c = canvas.Canvas(output_path, pagesize=(page_width, page_height))
    # Draw transparent diagonal text
    c.translate(page_width / 2.0, page_height / 2.0)
    c.rotate(45)
    c.setFont("Helvetica", 45)
    # 0.15 opacity for subtle watermark appearance
    c.setFillColor(Color(0.5, 0.5, 0.5, alpha=0.15))
    c.drawCentredString(0, 0, text)
    c.save()

def add_pdf_watermark(input_path, output_path, watermark_text):
    doc = fitz.open(input_path)
    if len(doc) == 0:
        doc.close()
        raise ValueError("The PDF document is empty.")

    # Create temporary file for the watermark PDF page
    temp_fd, watermark_temp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(temp_fd)
    
    try:
        # Use first page dimensions for the watermark template
        first_page = doc[0]
        rect = first_page.rect
        width = rect.width
        height = rect.height
        
        create_watermark_pdf(watermark_temp_path, watermark_text, width, height)
        
        watermark_doc = fitz.open(watermark_temp_path)
        
        for page in doc:
            # Draw watermark page over existing contents
            page.show_pdf_page(page.rect, watermark_doc, 0)
            
        doc.save(output_path)
        doc.close()
        watermark_doc.close()
    finally:
        try:
            if os.path.exists(watermark_temp_path):
                os.remove(watermark_temp_path)
        except Exception:
            pass

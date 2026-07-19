import fitz
from PIL import Image
import io
import os
import logging

logger = logging.getLogger(__name__)

def compress_pdf(input_path, output_path, level="medium"):
    """
    Compresses a PDF file.
    Levels:
      - 'low': Lossless compression (garbage collection and deflate).
      - 'medium': Compresses images to JPEG with 60% quality.
      - 'high': Compresses images to JPEG with 30% quality and downsizes large images.
    """
    doc = fitz.open(input_path)
    
    if level in ["medium", "high"]:
        quality = 60 if level == "medium" else 30
        for page_num in range(len(doc)):
            page = doc[page_num]
            images = page.get_images(full=True)
            for img_info in images:
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    if not base_image:
                        continue
                    
                    image_bytes = base_image["image"]
                    
                    # Read image
                    img = Image.open(io.BytesIO(image_bytes))
                    
                    # Convert to RGB if necessary (e.g. CMYK or RGBA to RGB for JPEG)
                    if img.mode in ["RGBA", "LA"]:
                        # Blend transparency with white background
                        background = Image.new("RGB", img.size, (255, 255, 255))
                        # Use split for alpha channel mask
                        alpha = img.split()[-1]
                        background.paste(img, mask=alpha)
                        img = background
                    elif img.mode != "RGB":
                        img = img.convert("RGB")
                    
                    # Downsample image for high compression level if it's very large
                    if level == "high" and (img.width > 1200 or img.height > 1200):
                        img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                    
                    # Save image to bytes as JPEG with specified quality
                    out_io = io.BytesIO()
                    img.save(out_io, format="JPEG", quality=quality, optimize=True)
                    compressed_bytes = out_io.getvalue()
                    
                    # Only replace if compressed bytes are actually smaller than original
                    if len(compressed_bytes) < len(image_bytes):
                        page.replace_image(xref, stream=compressed_bytes)
                except Exception as e:
                    logger.debug(f"Skipped image xref {xref} on page {page_num} due to: {e}")
                    continue
                    
    # Save optimized PDF
    doc.save(
        output_path,
        garbage=4,
        deflate=True,
        clean=True
    )
    doc.close()

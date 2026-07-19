import os
from PIL import Image

def rotate_image(img_path: str, output_path: str, angle: int):
    """
    Rotates an image by the specified angle (clockwise) and saves it.
    """
    with Image.open(img_path) as img:
        # PIL rotate is counter-clockwise by default, so use -angle to rotate clockwise
        # expand=True ensures the image size is adjusted to fit the rotated content without cropping
        rotated = img.rotate(-angle, expand=True)
        
        # JPEG does not support alpha (transparency), convert to RGB if target is JPEG
        if output_path.lower().endswith((".jpg", ".jpeg")) and rotated.mode in ("RGBA", "P"):
            rotated = rotated.convert("RGB")
            
        rotated.save(output_path)

def resize_image(img_path: str, output_path: str, scale_percent: int = None, custom_width: int = None):
    """
    Resizes an image using a scale percentage or custom width (maintaining aspect ratio).
    """
    with Image.open(img_path) as img:
        w, h = img.size
        if scale_percent:
            new_w = max(1, int(w * (scale_percent / 100)))
            new_h = max(1, int(h * (scale_percent / 100)))
        elif custom_width:
            new_w = max(1, int(custom_width))
            new_h = max(1, int(h * (new_w / w)))
        else:
            new_w, new_h = w, h
            
        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        if output_path.lower().endswith((".jpg", ".jpeg")) and resized.mode in ("RGBA", "P"):
            resized = resized.convert("RGB")
            
        resized.save(output_path)

def compress_image(img_path: str, output_path: str, compression_level: str):
    """
    Compresses an image to reduce file size.
    Levels: 'low' (80% quality), 'medium' (50% quality), 'high' (25% quality).
    Always exports as JPEG for maximum compression.
    """
    quality_map = {"low": 80, "medium": 50, "high": 25}
    quality = quality_map.get(compression_level.lower(), 70)
    
    with Image.open(img_path) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
            
        img.save(output_path, "JPEG", quality=quality, optimize=True)

def convert_image_format(img_path: str, output_path: str):
    """
    Converts an image's format (e.g. JPG -> PNG, PNG -> JPG) based on output file extension.
    """
    with Image.open(img_path) as img:
        if output_path.lower().endswith((".jpg", ".jpeg")) and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        elif output_path.lower().endswith(".png") and img.mode == "CMYK":
            img = img.convert("RGB")
            
        img.save(output_path)

def grayscale_image(img_path: str, output_path: str):
    """
    Applies a grayscale filter to an image.
    """
    with Image.open(img_path) as img:
        grayscaled = img.convert("L")
        grayscaled.save(output_path)

import imageio
from PIL import Image
import os
import logging

logger = logging.getLogger(__name__)

def video_to_gif(video_path, output_path, fps=10, max_width=480):
    """
    Converts a video file (MP4, AVI, etc.) to an optimized animated GIF using imageio.
    """
    reader = imageio.get_reader(video_path)
    meta = reader.get_meta_data()
    orig_fps = meta.get("fps", 25.0)
    
    # Calculate skip frame frequency to match target fps
    skip = max(1, int(orig_fps / fps))
    
    frames = []
    for i, frame in enumerate(reader):
        if i % skip != 0:
            continue
            
        img = Image.fromarray(frame)
        
        # Resize to target width to keep file size small
        if img.width > max_width:
            ratio = max_width / float(img.width)
            new_height = int(float(img.height) * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            
        frames.append(img)
        
        # Cap at 150 frames to avoid memory issues and giant file sizes
        if len(frames) >= 150:
            break
            
    reader.close()
    
    if not frames:
        raise Exception("Could not extract frames from the video file.")
        
    duration_ms = int(1000 / fps)
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=True
    )

def images_to_gif(image_paths, output_path, duration=500):
    """
    Combines multiple images into an animated GIF. Standardizes all frame sizes.
    """
    frames = []
    for path in image_paths:
        img = Image.open(path)
        if img.mode in ["RGBA", "LA"]:
            bg = Image.new("RGB", img.size, (255, 255, 255))
            alpha = img.split()[-1]
            bg.paste(img, mask=alpha)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        frames.append(img)
        
    if not frames:
        raise Exception("No images provided to create GIF.")
        
    # Resize all frames to the first frame size to prevent layout glitched GIFs
    base_size = frames[0].size
    for i in range(len(frames)):
        if frames[i].size != base_size:
            frames[i] = frames[i].resize(base_size, Image.Resampling.LANCZOS)
            
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=duration,
        loop=0,
        optimize=True
    )

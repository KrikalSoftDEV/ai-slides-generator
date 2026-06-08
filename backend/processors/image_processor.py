import base64
import io
import numpy as np

from PIL import Image, ImageSequence, ImageDraw, ImageFont, ImageFilter
import easyocr
from typing import Any, Dict, List, Tuple


PPT_SAFE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg"}

# Initialize OCR reader (lazy load)
_ocr_reader = None

def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        _ocr_reader = easyocr.Reader(['en'], gpu=False)
    return _ocr_reader


def _normalize_for_presentation(img: Image.Image, content_type: str) -> tuple[bytes, str]:
    buf = io.BytesIO()
    if content_type in {"image/jpeg", "image/jpg"} and img.mode == "RGB":
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue(), "image/jpeg"

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")
    img.save(buf, format="PNG")
    return buf.getvalue(), "image/png"


def process_image(content: bytes, content_type: str) -> dict:
    img = Image.open(io.BytesIO(content))
    if getattr(img, "is_animated", False):
        img = next(ImageSequence.Iterator(img)).copy()

    content_type = "image/jpeg" if content_type == "image/jpg" else content_type

    if content_type not in PPT_SAFE_IMAGE_TYPES:
        content, content_type = _normalize_for_presentation(img, content_type)

    img = Image.open(io.BytesIO(content))
    max_dim = 1568
    if img.width > max_dim or img.height > max_dim:
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        content, content_type = _normalize_for_presentation(img, content_type)

    img_b64 = base64.b64encode(content).decode()
    return {
        "base64": img_b64,
        "media_type": content_type,
        "source_type": "image",
    }


def extract_text_from_image(content: bytes) -> Dict[str, any]:
    """
    Extract text from image using OCR.
    
    Returns:
        Dict with extracted text and coordinates
    """
    try:
        img = Image.open(io.BytesIO(content))
        
        # Get OCR reader
        reader = _get_ocr_reader()
        
        # Convert PIL image to numpy array for OCR
        img_array = np.array(img)
        
        # Perform OCR
        results = reader.readtext(img_array)
        
        # Format results
        extracted_texts = []
        for (bbox, text, confidence) in results:
            extracted_texts.append({
                "text": text,
                "confidence": float(confidence),
                "bbox": [
                    [int(point[0]), int(point[1])]
                    for point in bbox
                ],
            })
        
        return {
            "success": True,
            "text_blocks": extracted_texts,
            "full_text": "\n".join([item["text"] for item in extracted_texts]),
            "image_width": img.width,
            "image_height": img.height,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_paths = [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _load_font_from_path(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return _load_font(size)


def _font_candidates() -> List[str]:
    return [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]


def _bbox_bounds(bbox: List[List[float]]) -> Tuple[int, int, int, int]:
    xs = [point[0] for point in bbox]
    ys = [point[1] for point in bbox]
    return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))


def _color_tuple(values: np.ndarray) -> Tuple[int, int, int]:
    return tuple(int(channel) for channel in values[:3])


def _sample_block_colors(img: Image.Image, box: Tuple[int, int, int, int]) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    x0, y0, x1, y1 = box
    width, height = img.size
    crop = img.convert("RGB").crop((
        max(0, x0),
        max(0, y0),
        min(width, x1),
        min(height, y1),
    ))
    if not crop.width or not crop.height:
        return (255, 255, 255), (0, 0, 0)

    pixels = np.array(crop).reshape(-1, 3)
    luminance = pixels @ np.array([0.299, 0.587, 0.114])
    background = _color_tuple(np.median(pixels, axis=0))
    background_luminance = (0.299 * background[0]) + (0.587 * background[1]) + (0.114 * background[2])

    if background_luminance > 145:
        text_pixels = pixels[luminance <= np.percentile(luminance, 12)]
    else:
        text_pixels = pixels[luminance >= np.percentile(luminance, 88)]

    if len(text_pixels) == 0:
        text_color = (15, 23, 42) if background_luminance > 145 else (248, 250, 252)
    else:
        text_color = _color_tuple(np.median(text_pixels, axis=0))

    return background, text_color


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> List[str]:
    lines = []
    for paragraph in text.splitlines() or [""]:
        words = paragraph.split(" ")
        current_line = ""
        for word in words:
            candidate = word if not current_line else f"{current_line} {word}"
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                current_line = candidate
                continue

            if current_line:
                lines.append(current_line)
                current_line = word

            while draw.textbbox((0, 0), current_line, font=font)[2] > max_width and len(current_line) > 1:
                for split_at in range(len(current_line) - 1, 0, -1):
                    if draw.textbbox((0, 0), current_line[:split_at], font=font)[2] <= max_width:
                        lines.append(current_line[:split_at])
                        current_line = current_line[split_at:]
                        break

        lines.append(current_line)
    return lines


def _fit_text(
    text: str,
    draw: ImageDraw.ImageDraw,
    max_width: int,
    max_height: int,
    preferred_font_path: str | None = None,
) -> Tuple[ImageFont.ImageFont, List[str], int]:
    text = text.strip()
    if not text:
        return _load_font(10), [], 0

    for size in range(min(72, max(10, max_height)), 7, -1):
        font = _load_font_from_path(preferred_font_path, size) if preferred_font_path else _load_font(size)
        line_spacing = max(2, size // 5)
        lines = _wrap_text(text, font, max_width, draw)
        line_heights = [
            draw.textbbox((0, 0), line or " ", font=font)[3]
            - draw.textbbox((0, 0), line or " ", font=font)[1]
            for line in lines
        ]
        total_height = sum(line_heights) + max(0, len(lines) - 1) * line_spacing
        if total_height <= max_height:
            return font, lines, line_spacing

    font = _load_font_from_path(preferred_font_path, 8) if preferred_font_path else _load_font(8)
    return font, _wrap_text(text, font, max_width, draw), 2


def _estimate_font_path_and_size(
    original_text: str,
    box_width: int,
    box_height: int,
    draw: ImageDraw.ImageDraw,
) -> Tuple[str | None, int | None]:
    if not original_text.strip():
        return None, None

    best = None
    for font_path in _font_candidates():
        for size in range(8, 120):
            try:
                font = ImageFont.truetype(font_path, size)
            except OSError:
                continue
            bounds = draw.textbbox((0, 0), original_text, font=font)
            text_width = bounds[2] - bounds[0]
            text_height = bounds[3] - bounds[1]
            score = (
                abs(text_width - box_width) / max(box_width, 1)
                + 0.65 * abs(text_height - box_height) / max(box_height, 1)
            )
            if best is None or score < best[0]:
                best = (score, font_path, size)

    if best is None:
        return None, None
    return best[1], best[2]


def _normalise_image_blocks(updated_content: Any) -> List[Dict[str, Any]]:
    if isinstance(updated_content, dict):
        if isinstance(updated_content.get("blocks"), list):
            return updated_content["blocks"]
        if "text" in updated_content:
            return [{"text": str(updated_content.get("text", "")), "bbox": None}]
    if isinstance(updated_content, list):
        return updated_content
    return [{"text": str(updated_content), "bbox": None}]


def _erase_text_pixels(
    target: Image.Image,
    source: Image.Image,
    box: Tuple[int, int, int, int],
    background: Tuple[int, int, int],
    text_color: Tuple[int, int, int],
    exclusions: List[Tuple[int, int, int, int]],
) -> None:
    x0, y0, x1, y1 = box
    crop = source.crop(box).convert("RGB")
    pixels = np.array(crop).astype(np.int16)
    bg = np.array(background, dtype=np.int16)
    text = np.array(text_color, dtype=np.int16)

    distance_to_bg = np.linalg.norm(pixels - bg, axis=2)
    distance_to_text = np.linalg.norm(pixels - text, axis=2)
    mask_array = (distance_to_text < distance_to_bg).astype(np.uint8) * 255

    for ex0, ey0, ex1, ey1 in exclusions:
        ix0 = max(x0, ex0) - x0
        iy0 = max(y0, ey0) - y0
        ix1 = min(x1, ex1) - x0
        iy1 = min(y1, ey1) - y0
        if ix1 > ix0 and iy1 > iy0:
            mask_array[iy0:iy1, ix0:ix1] = 0

    mask = Image.fromarray(mask_array, mode="L").filter(ImageFilter.MaxFilter(3))
    fill = Image.new("RGB", crop.size, background)
    target.paste(fill, box, mask)


def update_image_with_text(content: bytes, content_type: str, updated_content: Any) -> Tuple[bytes, str]:
    """
    Update image with edited text.
    
    Args:
        content: Original image bytes
        content_type: Image MIME type
        updated_content: Edited text blocks with OCR bounding boxes, or legacy text
    
    Returns:
        Tuple of (updated_image_bytes, content_type)
    """
    try:
        img = Image.open(io.BytesIO(content))
        if getattr(img, "is_animated", False):
            img = next(ImageSequence.Iterator(img)).copy()
        img = img.convert("RGB")
        
        img_copy = img.copy()
        draw = ImageDraw.Draw(img_copy)
        blocks = _normalise_image_blocks(updated_content)

        for index, block in enumerate(blocks):
            text = str(block.get("text", "")) if isinstance(block, dict) else str(block)
            original_text = str(block.get("originalText", "")) if isinstance(block, dict) else ""
            if original_text and text == original_text:
                continue

            bbox = block.get("bbox") if isinstance(block, dict) else None
            if not bbox:
                font = _load_font(20)
                draw.text((10, 10), text, fill=(0, 0, 0), font=font)
                continue

            x0, y0, x1, y1 = _bbox_bounds(bbox)
            box_width = max(1, x1 - x0)
            box_height = max(1, y1 - y0)
            text_padding = max(1, min(box_width, box_height) // 18)

            background, text_color = _sample_block_colors(img, (x0, y0, x1, y1))
            exclusions = []
            for other_index, other_block in enumerate(blocks):
                if other_index == index or not isinstance(other_block, dict) or not other_block.get("bbox"):
                    continue
                exclusions.append(_bbox_bounds(other_block["bbox"]))
            _erase_text_pixels(
                img_copy,
                img,
                (x0, y0, x1, y1),
                background,
                text_color,
                exclusions,
            )

            text_box = (
                max(0, x0 - text_padding),
                max(0, y0 - text_padding),
                min(img_copy.width, x1 + text_padding),
                min(img_copy.height, y1 + text_padding),
            )
            max_text_width = max(1, text_box[2] - text_box[0])
            max_text_height = max(1, text_box[3] - text_box[1])
            preferred_font_path, preferred_size = _estimate_font_path_and_size(
                original_text or text,
                box_width,
                box_height,
                draw,
            )
            if preferred_size:
                preferred_font = _load_font_from_path(preferred_font_path, preferred_size)
                preferred_bounds = draw.textbbox((0, 0), text, font=preferred_font)
                preferred_width = preferred_bounds[2] - preferred_bounds[0]
                preferred_height = preferred_bounds[3] - preferred_bounds[1]
                if preferred_width <= max_text_width and preferred_height <= max_text_height:
                    font = preferred_font
                    lines = [text]
                    line_spacing = 0
                else:
                    font, lines, line_spacing = _fit_text(
                        text,
                        draw,
                        max_text_width,
                        max_text_height,
                        preferred_font_path,
                    )
            else:
                font, lines, line_spacing = _fit_text(
                    text,
                    draw,
                    max_text_width,
                    max_text_height,
                )

            line_bounds = [draw.textbbox((0, 0), line or " ", font=font) for line in lines]
            total_text_height = sum(bounds[3] - bounds[1] for bounds in line_bounds)
            total_text_height += max(0, len(lines) - 1) * line_spacing
            y = text_box[1] + max(0, (max_text_height - total_text_height) // 2)
            for line in lines:
                bounds = draw.textbbox((0, 0), line or " ", font=font)
                draw.text((text_box[0] - bounds[0], y - bounds[1]), line, fill=text_color, font=font)
                y += (bounds[3] - bounds[1]) + line_spacing
        
        output = io.BytesIO()
        save_format = "JPEG" if content_type in {"image/jpeg", "image/jpg"} else "PNG"
        img_copy.save(output, format=save_format, quality=95)
        
        return output.getvalue(), content_type
    except Exception as e:
        raise ValueError(f"Failed to update image: {str(e)}")

import base64
import io
import re
import numpy as np

from PIL import Image, ImageSequence, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import easyocr
import cv2
from typing import Any, Dict, List, Tuple


PPT_SAFE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg"}

# Initialize OCR reader (lazy load)
_ocr_reader = None

def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        _ocr_reader = easyocr.Reader(['en'], gpu=False)
    return _ocr_reader


def _bbox_from_bounds(x0: float, y0: float, x1: float, y1: float) -> List[List[int]]:
    return [
        [int(round(x0)), int(round(y0))],
        [int(round(x1)), int(round(y0))],
        [int(round(x1)), int(round(y1))],
        [int(round(x0)), int(round(y1))],
    ]


def _scale_bbox(bbox: List[List[float]], scale: float) -> List[List[int]]:
    return [
        [int(round(point[0] / scale)), int(round(point[1] / scale))]
        for point in bbox
    ]


def _normalise_ocr_text(text: str) -> str:
    return " ".join(str(text).replace("|", "I").split())


COMMON_OCR_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "edit",
    "for", "format", "from", "give", "good", "have", "i", "image", "in",
    "is", "it", "life", "me", "my", "name", "never", "of", "on", "or",
    "other", "others", "same", "text", "that", "the", "this", "to", "up",
    "upload", "user", "with", "you", "your", "download", "compare",
    "developer", "test", "result", "content", "slide", "file",
}


def _match_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement.capitalize()
    return replacement


def _split_known_words(token: str) -> str:
    lower = token.lower()
    if len(lower) < 7 or lower in COMMON_OCR_WORDS:
        return token

    best: Dict[int, Tuple[float, List[str]]] = {0: (0.0, [])}
    for index in range(len(lower)):
        if index not in best:
            continue
        score, words = best[index]
        for end in range(index + 1, len(lower) + 1):
            word = lower[index:end]
            if word not in COMMON_OCR_WORDS:
                continue
            word_score = len(word) ** 1.35
            if len(word) <= 2:
                word_score -= 1.5
            candidate = (score + word_score, words + [word])
            if end not in best or candidate[0] > best[end][0]:
                best[end] = candidate

    if len(lower) not in best:
        return token

    _, words = best[len(lower)]
    if len(words) < 2 or sum(len(word) for word in words) != len(lower):
        return token

    repaired_words = []
    for index, word in enumerate(words):
        source = token if index == 0 else word
        repaired_words.append(_match_case(source, word))
    return " ".join(repaired_words)


def _repair_ocr_spacing(text: str) -> str:
    repaired = []
    current = []
    for char in text:
        if char.isalpha():
            current.append(char)
            continue
        if current:
            repaired.append(_split_known_words("".join(current)))
            current = []
        repaired.append(char)
    if current:
        repaired.append(_split_known_words("".join(current)))

    repaired_text = " ".join("".join(repaired).split())
    return re.sub(r"([,.;:!?])(?=[A-Za-z])", r"\1 ", repaired_text)


def _line_alignment(bounds: Tuple[int, int, int, int], image_width: int) -> str:
    x0, _, x1, _ = bounds
    center = (x0 + x1) / 2
    if abs(center - (image_width / 2)) <= image_width * 0.08:
        return "center"
    if center > image_width * 0.62:
        return "right"
    return "left"


def _prepare_ocr_images(img: Image.Image) -> List[Tuple[np.ndarray, float]]:
    rgb = img.convert("RGB")
    variants = [(rgb, 1.0)]

    scale = 2.0 if max(rgb.size) < 1800 else 1.35
    enlarged = rgb.resize(
        (int(rgb.width * scale), int(rgb.height * scale)),
        Image.Resampling.LANCZOS,
    )
    variants.append((enlarged, scale))

    gray = enlarged.convert("L")
    gray = ImageEnhance.Contrast(gray).enhance(1.8)
    gray = ImageEnhance.Sharpness(gray).enhance(1.6)
    variants.append((gray.convert("RGB"), scale))

    return [(np.array(variant), scale) for variant, scale in variants]


def _read_ocr_results(reader: easyocr.Reader, img: Image.Image) -> List[Dict[str, Any]]:
    best_results = []
    best_score = -1.0
    for img_array, scale in _prepare_ocr_images(img):
        try:
            results = reader.readtext(
                img_array,
                decoder="beamsearch",
                beamWidth=8,
                paragraph=False,
                text_threshold=0.35,
                low_text=0.2,
                link_threshold=0.25,
                width_ths=0.9,
                ycenter_ths=0.7,
            )
        except TypeError:
            results = reader.readtext(img_array)

        formatted = []
        for bbox, text, confidence in results:
            clean_text = _normalise_ocr_text(text)
            if not clean_text:
                continue
            scaled_bbox = _scale_bbox(bbox, scale)
            clean_text = _repair_ocr_spacing(clean_text)
            x0, y0, x1, y1 = _bbox_bounds(scaled_bbox)
            formatted.append({
                "text": clean_text,
                "confidence": float(confidence),
                "bbox": scaled_bbox,
                "bounds": (x0, y0, x1, y1),
            })

        score = sum(len(item["text"]) * max(item["confidence"], 0.05) for item in formatted)
        if score > best_score:
            best_score = score
            best_results = formatted

    return best_results


def _group_ocr_blocks(items: List[Dict[str, Any]], image_width: int, image_height: int) -> List[Dict[str, Any]]:
    if not items:
        return []

    items = sorted(items, key=lambda item: (item["bounds"][1], item["bounds"][0]))
    lines = []
    for item in items:
        x0, y0, x1, y1 = item["bounds"]
        center_y = (y0 + y1) / 2
        height = max(1, y1 - y0)
        matched_line = None
        for line in lines:
            line_center = (line["y0"] + line["y1"]) / 2
            line_height = max(1, line["y1"] - line["y0"])
            if abs(center_y - line_center) <= max(height, line_height) * 0.55:
                matched_line = line
                break

        if matched_line is None:
            lines.append({
                "items": [item],
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
            })
            continue

        matched_line["items"].append(item)
        matched_line["x0"] = min(matched_line["x0"], x0)
        matched_line["y0"] = min(matched_line["y0"], y0)
        matched_line["x1"] = max(matched_line["x1"], x1)
        matched_line["y1"] = max(matched_line["y1"], y1)

    normalised_lines = []
    for line in lines:
        line["items"].sort(key=lambda item: item["bounds"][0])
        text = " ".join(item["text"] for item in line["items"])
        confidence = sum(item["confidence"] for item in line["items"]) / len(line["items"])
        normalised_lines.append({
            "text": text,
            "confidence": confidence,
            "bbox": _bbox_from_bounds(line["x0"], line["y0"], line["x1"], line["y1"]),
            "bounds": (line["x0"], line["y0"], line["x1"], line["y1"]),
            "alignment": _line_alignment((line["x0"], line["y0"], line["x1"], line["y1"]), image_width),
        })

    normalised_lines.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    line_heights = [max(1, item["bounds"][3] - item["bounds"][1]) for item in normalised_lines]
    median_height = float(np.median(line_heights)) if line_heights else 1.0

    groups = []
    for line in normalised_lines:
        if not groups:
            groups.append([line])
            continue

        previous = groups[-1][-1]
        gap = line["bounds"][1] - previous["bounds"][3]
        horizontal_overlap = max(
            0,
            min(line["bounds"][2], previous["bounds"][2]) - max(line["bounds"][0], previous["bounds"][0]),
        )
        min_width = max(1, min(
            line["bounds"][2] - line["bounds"][0],
            previous["bounds"][2] - previous["bounds"][0],
        ))
        same_paragraph = gap <= median_height * 1.35 and horizontal_overlap / min_width >= 0.1
        if same_paragraph:
            groups[-1].append(line)
        else:
            groups.append([line])

    blocks = []
    for index, group in enumerate(groups):
        x0 = min(line["bounds"][0] for line in group)
        y0 = min(line["bounds"][1] for line in group)
        x1 = max(line["bounds"][2] for line in group)
        y1 = max(line["bounds"][3] for line in group)
        confidence = sum(line["confidence"] for line in group) / len(group)
        alignments = [line["alignment"] for line in group]
        alignment = max(set(alignments), key=alignments.count)
        blocks.append({
            "text": "\n".join(line["text"] for line in group),
            "confidence": float(confidence),
            "bbox": _bbox_from_bounds(x0, y0, x1, y1),
            "line_bboxes": [line["bbox"] for line in group],
            "alignment": alignment,
        })

    return blocks


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
        extracted_texts = _group_ocr_blocks(
            _read_ocr_results(reader, img),
            img.width,
            img.height,
        )
        
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


def _sample_strip_color(arr: np.ndarray, y: int, x0: int, x1: int) -> np.ndarray | None:
    height, width = arr.shape[:2]
    x0 = max(0, min(width, x0))
    x1 = max(0, min(width, x1))
    if x1 <= x0:
        return None

    y0 = max(0, y - 2)
    y1 = min(height, y + 3)
    pixels = arr[y0:y1, x0:x1].reshape(-1, 3)
    if len(pixels) == 0:
        return None
    return np.median(pixels, axis=0)


def _fill_text_box_with_local_background(
    target: Image.Image,
    source: Image.Image,
    box: Tuple[int, int, int, int],
) -> None:
    x0, y0, x1, y1 = box
    width, height = source.size
    x0 = max(0, min(width, x0))
    x1 = max(0, min(width, x1))
    y0 = max(0, min(height, y0))
    y1 = max(0, min(height, y1))
    if x1 <= x0 or y1 <= y0:
        return

    source_arr = np.array(source.convert("RGB"))
    box_width = x1 - x0
    box_height = y1 - y0
    fill = np.zeros((box_height, box_width, 3), dtype=np.uint8)
    fallback = np.median(source_arr.reshape(-1, 3), axis=0)

    for row_index, y in enumerate(range(y0, y1)):
        left_color = _sample_strip_color(source_arr, y, x0 - 18, x0 - 3)
        right_color = _sample_strip_color(source_arr, y, x1 + 3, x1 + 18)
        if left_color is None and right_color is None:
            left_color = right_color = fallback
        elif left_color is None:
            left_color = right_color
        elif right_color is None:
            right_color = left_color

        weights = np.linspace(0, 1, box_width)[:, None]
        fill[row_index] = ((1 - weights) * left_color + weights * right_color).astype(np.uint8)

    target.paste(Image.fromarray(fill, mode="RGB"), (x0, y0, x1, y1))


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


def _fit_text_to_line_count(
    text: str,
    draw: ImageDraw.ImageDraw,
    max_width: int,
    max_height: int,
    target_line_count: int,
    preferred_font_path: str | None = None,
) -> Tuple[ImageFont.ImageFont, List[str], int]:
    target_line_count = max(1, target_line_count)
    text = text.strip()
    if not text:
        return _load_font(10), [], 0

    paragraphs = text.splitlines()
    if len(paragraphs) == target_line_count:
        candidate_lines = [line.strip() for line in paragraphs]
    else:
        candidate_lines = []

    for size in range(min(120, max(10, max_height)), 7, -1):
        font = _load_font_from_path(preferred_font_path, size) if preferred_font_path else _load_font(size)
        line_spacing = max(2, size // 5)
        lines = candidate_lines or _wrap_text(text, font, max_width, draw)
        if len(lines) > target_line_count + 1:
            continue

        line_bounds = [draw.textbbox((0, 0), line or " ", font=font) for line in lines]
        if any(bounds[2] - bounds[0] > max_width for bounds in line_bounds):
            continue

        total_height = sum(bounds[3] - bounds[1] for bounds in line_bounds)
        total_height += max(0, len(lines) - 1) * line_spacing
        if total_height <= max_height:
            return font, lines, line_spacing

    return _fit_text(text, draw, max_width, max_height, preferred_font_path)


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


def _block_alignment(block: Dict[str, Any], bbox: Tuple[int, int, int, int], image_width: int) -> str:
    alignment = str(block.get("alignment", "")).lower()
    if alignment in {"left", "center", "right"}:
        return alignment
    return _line_alignment(bbox, image_width)


def _expanded_text_region(
    block: Dict[str, Any],
    bbox: Tuple[int, int, int, int],
    image_size: Tuple[int, int],
) -> Tuple[int, int, int, int]:
    img_width, img_height = image_size
    x0, y0, x1, y1 = bbox
    boxes = [bbox]
    for line_bbox in block.get("line_bboxes", []) or []:
        try:
            boxes.append(_bbox_bounds(line_bbox))
        except (TypeError, ValueError, IndexError):
            continue

    x0 = min(box[0] for box in boxes)
    y0 = min(box[1] for box in boxes)
    x1 = max(box[2] for box in boxes)
    y1 = max(box[3] for box in boxes)

    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    pad_x = max(8, int(width * 0.08))
    pad_y = max(5, int(height * 0.12))
    alignment = _block_alignment(block, (x0, y0, x1, y1), img_width)

    if alignment == "center":
        center = (x0 + x1) / 2
        region_width = min(img_width, max(width + (2 * pad_x), int(img_width * 0.88)))
        x0 = int(round(center - (region_width / 2)))
        x1 = x0 + region_width
    elif alignment == "right":
        x0 -= pad_x * 2
        x1 += pad_x
    else:
        x0 -= pad_x
        x1 += pad_x * 2

    y0 -= pad_y
    y1 += pad_y
    return (
        max(0, x0),
        max(0, y0),
        min(img_width, x1),
        min(img_height, y1),
    )


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


def _inpaint_text_pixels(
    target: Image.Image,
    source: Image.Image,
    box: Tuple[int, int, int, int],
    background: Tuple[int, int, int],
    text_color: Tuple[int, int, int],
) -> None:
    x0, y0, x1, y1 = box
    width, height = source.size
    x0 = max(0, min(width, x0))
    x1 = max(0, min(width, x1))
    y0 = max(0, min(height, y0))
    y1 = max(0, min(height, y1))
    if x1 <= x0 or y1 <= y0:
        return

    crop = source.crop((x0, y0, x1, y1)).convert("RGB")
    pixels = np.array(crop)
    pixel_values = pixels.astype(np.int16)
    bg = np.array(background, dtype=np.int16)
    text = np.array(text_color, dtype=np.int16)

    distance_to_bg = np.linalg.norm(pixel_values - bg, axis=2)
    distance_to_text = np.linalg.norm(pixel_values - text, axis=2)
    text_distance_limit = np.maximum(48, distance_to_bg * 0.8)
    mask_array = (distance_to_text <= text_distance_limit).astype(np.uint8) * 255
    mask = Image.fromarray(mask_array, mode="L").filter(ImageFilter.MaxFilter(7))
    mask = mask.filter(ImageFilter.GaussianBlur(0.4))
    mask_array = np.array(mask)

    if not np.any(mask_array):
        return

    inpainted = cv2.inpaint(
        cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR),
        mask_array,
        3,
        cv2.INPAINT_TELEA,
    )
    inpainted_rgb = cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB)
    target.paste(Image.fromarray(inpainted_rgb, mode="RGB"), (x0, y0, x1, y1))


def _line_count_from_block(block: Dict[str, Any], original_text: str, text: str) -> int:
    line_bboxes = block.get("line_bboxes", []) or []
    if line_bboxes:
        return len(line_bboxes)
    if original_text.strip():
        return max(1, len(original_text.splitlines()))
    return max(1, len(text.splitlines()))


def _original_font(
    original_text: str,
    text: str,
    bbox: Tuple[int, int, int, int],
    line_count: int,
    draw: ImageDraw.ImageDraw,
) -> ImageFont.ImageFont:
    x0, y0, x1, y1 = bbox
    box_width = max(1, x1 - x0)
    box_height = max(1, y1 - y0)
    sample_text = original_text or text
    sample_lines = [line.strip() for line in sample_text.splitlines() if line.strip()]
    sample_line = max(sample_lines, key=len) if sample_lines else sample_text
    preferred_font_path, preferred_size = _estimate_font_path_and_size(
        sample_line,
        box_width,
        max(1, box_height // max(1, line_count)),
        draw,
    )
    if preferred_size:
        return _load_font_from_path(preferred_font_path, preferred_size)
    return _load_font(max(10, box_height // max(1, line_count)))


def _replacement_lines(text: str, target_line_count: int) -> List[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        return lines
    return [text.strip()] if text.strip() else []


def _erase_boxes_from_block(block: Dict[str, Any], bbox: Tuple[int, int, int, int]) -> List[Tuple[int, int, int, int]]:
    boxes = []
    for line_bbox in block.get("line_bboxes", []) or []:
        try:
            boxes.append(_bbox_bounds(line_bbox))
        except (TypeError, ValueError, IndexError):
            continue
    return boxes or [bbox]


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
        editable_blocks = []

        for block in blocks:
            block_data = block if isinstance(block, dict) else {}
            text = str(block_data.get("text", "")) if isinstance(block, dict) else str(block)
            original_text = str(block_data.get("originalText", "")) if isinstance(block, dict) else ""
            if original_text and text == original_text:
                continue

            bbox = block_data.get("bbox")
            if not bbox:
                editable_blocks.append({
                    "text": text,
                    "bbox": None,
                    "text_region": None,
                    "erase_boxes": [],
                    "original_text": original_text,
                    "background": (255, 255, 255),
                    "text_color": (0, 0, 0),
                    "alignment": "left",
                    "line_count": _line_count_from_block(block_data, original_text, text),
                })
                continue

            x0, y0, x1, y1 = _bbox_bounds(bbox)
            background, text_color = _sample_block_colors(img, (x0, y0, x1, y1))
            text_region = _expanded_text_region(block_data, (x0, y0, x1, y1), img.size)
            editable_blocks.append({
                "text": text,
                "bbox": (x0, y0, x1, y1),
                "text_region": text_region,
                "erase_boxes": _erase_boxes_from_block(block_data, (x0, y0, x1, y1)),
                "original_text": original_text,
                "background": background,
                "text_color": text_color,
                "alignment": _block_alignment(block_data, (x0, y0, x1, y1), img.width),
                "line_count": _line_count_from_block(block_data, original_text, text),
            })

        for block in editable_blocks:
            for erase_box in block["erase_boxes"]:
                background, text_color = _sample_block_colors(img, erase_box)
                _inpaint_text_pixels(
                    img_copy,
                    img,
                    erase_box,
                    background,
                    text_color,
                )

        for block in editable_blocks:
            text = block["text"]
            original_text = block["original_text"]
            bbox = block["bbox"]
            text_region = block["text_region"]
            text_color = block["text_color"]
            alignment = block["alignment"]
            line_count = block["line_count"]

            if not bbox:
                font = _load_font(20)
                draw.text((10, 10), text, fill=text_color, font=font)
                continue

            x0, y0, x1, y1 = bbox
            region_x0, region_y0, region_x1, region_y1 = text_region or bbox
            box_width = max(1, x1 - x0)
            box_height = max(1, y1 - y0)
            text_padding = max(1, min(box_width, box_height) // 18)

            text_box = (
                max(0, region_x0 + text_padding),
                max(0, region_y0 + text_padding),
                min(img_copy.width, region_x1 - text_padding),
                min(img_copy.height, region_y1 - text_padding),
            )
            max_text_width = max(1, text_box[2] - text_box[0])
            max_text_height = max(1, text_box[3] - text_box[1])
            font = _original_font(
                original_text,
                text,
                bbox,
                line_count,
                draw,
            )
            lines = _replacement_lines(text, line_count)
            font_size = getattr(font, "size", max(10, box_height // max(1, line_count)))
            line_spacing = max(2, font_size // 5)

            line_bounds = [draw.textbbox((0, 0), line or " ", font=font) for line in lines]
            total_text_height = sum(bounds[3] - bounds[1] for bounds in line_bounds)
            total_text_height += max(0, len(lines) - 1) * line_spacing
            y = text_box[1] + max(0, (max_text_height - total_text_height) // 2)
            for line in lines:
                bounds = draw.textbbox((0, 0), line or " ", font=font)
                line_width = bounds[2] - bounds[0]
                if alignment == "center":
                    x = text_box[0] + max(0, (max_text_width - line_width) // 2)
                elif alignment == "right":
                    x = text_box[2] - line_width
                else:
                    x = text_box[0]
                draw.text((x - bounds[0], y - bounds[1]), line, fill=text_color, font=font)
                y += (bounds[3] - bounds[1]) + line_spacing
        
        output = io.BytesIO()
        save_format = "JPEG" if content_type in {"image/jpeg", "image/jpg"} else "PNG"
        img_copy.save(output, format=save_format, quality=95)
        
        return output.getvalue(), content_type
    except Exception as e:
        raise ValueError(f"Failed to update image: {str(e)}")

import base64
from typing import Tuple

import fitz  # PyMuPDF


def process_pdf(content: bytes) -> Tuple[list, list]:
    doc = fitz.open(stream=content, filetype="pdf")
    texts = []
    images = []

    for page_num, page in enumerate(doc):
        text = page.get_text()
        if text.strip():
            texts.append(f"Page {page_num + 1}:\n{text}")

        mat = fitz.Matrix(1.5, 1.5)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        img_b64 = base64.b64encode(img_bytes).decode()
        images.append({
            "base64": img_b64,
            "media_type": "image/png",
            "label": f"PDF Page {page_num + 1}",
            "source_type": "pdf_page",
            "page": page_num + 1,
        })

    doc.close()
    return texts, images

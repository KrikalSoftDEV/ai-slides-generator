from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from typing import List, Dict
import os
from dotenv import load_dotenv
import json
from urllib.parse import quote

# Load environment variables
load_dotenv()
if not os.environ.get("ANTHROPIC_API_KEY"):
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from processors.pdf_processor import process_pdf
from processors.image_processor import process_image
from processors.pptx_processor import process_pptx, update_pptx_text
from ai.claude_client import analyze_content_for_slides
from generators.editable_pptx_converter import (
    PPTX_MEDIA_TYPE,
    convert_file_to_editable_pptx,
    editable_pptx_filename,
    extract_file_for_editing,
)
from generators.pptx_generator import create_presentation

app = FastAPI(title="AI Slides Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


def is_supported_file_type(filename: str, content_type: str) -> bool:
    """Check if file type is supported (jpg, jpeg, png, pdf, pptx)."""
    filename_lower = filename.lower()
    
    # Check by extension
    if filename_lower.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.pdf', '.pptx')):
        return True
    
    # Check by content type
    if content_type in ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif', 'application/pdf']:
        return True
    
    if content_type in ['application/vnd.openxmlformats-officedocument.presentationml.presentation']:
        return True
    
    return False


def attachment_headers(filename: str) -> Dict[str, str]:
    """Build download headers that are safe for Unicode filenames."""
    basename = os.path.basename(filename) or "download"
    fallback = "".join(
        char if 32 <= ord(char) < 127 and char not in {'"', "\\", ";"} else "_"
        for char in basename
    ).strip() or "download"
    encoded = quote(basename, safe="")
    return {
        "Content-Disposition": f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'
    }


@app.post("/api/extract-text")
async def extract_text(files: List[UploadFile] = File(...)):
    """
    Extract editable text from uploaded files (jpg, jpeg, png, pdf, pptx).
    Returns JSON with text organized by file.
    """
    result = {}
    
    for file in files:
        content = await file.read()
        filename = file.filename or "Uploaded file"
        
        if not content:
            raise HTTPException(
                status_code=400,
                detail=f"Uploaded file '{filename}' is empty."
            )
        
        # Validate file type
        if not is_supported_file_type(filename, file.content_type or ""):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{filename}'. Only .jpg, .jpeg, .png, .pdf, and .pptx are supported."
            )
        
        # Process PPT files
        if filename.lower().endswith('.pptx') or \
           file.content_type in ['application/vnd.openxmlformats-officedocument.presentationml.presentation']:
            try:
                text_data, _ = process_pptx(content)
                result[filename] = {
                    "type": "pptx",
                    "slides": text_data
                }
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to process PPT file '{filename}': {str(e)}"
                )

        elif filename.lower().endswith('.pdf') or file.content_type == "application/pdf":
            try:
                texts, _ = process_pdf(content)
                result[filename] = {
                    "type": "pdf",
                    "pages": texts,
                }
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to process PDF file '{filename}': {str(e)}"
                )
        
        # Process image files
        elif file.content_type and file.content_type.startswith('image/'):
            try:
                # For images, we'll use OCR or note that images contain visual content
                result[filename] = {
                    "type": "image",
                    "note": "Image file uploaded. Text extraction from images would require OCR.",
                    "text": ""
                }
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to process image file '{filename}': {str(e)}"
                )
    
    return result


@app.post("/api/update-and-download")
async def update_and_download(
    ppt_file: UploadFile = File(...),
    updated_text: str = Form(...),
):
    """
    Update text in PPT file and return the modified file.
    
    updated_text format: JSON string with slide_number as key and new text as value
    Example: '{"1": "Updated slide 1 text", "2": "Updated slide 2 text"}'
    """
    content = await ppt_file.read()
    filename = ppt_file.filename or "document.pptx"
    
    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )
    
    # Validate file type
    if not (
        filename.lower().endswith('.pptx') or
        ppt_file.content_type == 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    ):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Only .pptx files can be edited by this legacy endpoint."
        )
    
    try:
        # Parse the updated text JSON
        updated_texts = json.loads(updated_text)
        
        # Convert string keys to integers
        updated_texts = {int(k): v for k, v in updated_texts.items()}
        
        # Process PPTX
        text_data, prs = process_pptx(content)
        
        # Update text
        updated_pptx = update_pptx_text(prs, updated_texts)
        
        # Return updated file
        return Response(
            content=updated_pptx,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers=attachment_headers(filename),
        )
    
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON format for updated_text parameter."
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to update PPT file: {str(e)}"
        )


@app.post("/api/extract-editable-content")
async def extract_editable_content(file: UploadFile = File(...)):
    """
    NEW WORKFLOW: Extract text from image, PDF, or PPTX for editable PPTX export.
    
    Returns:
        JSON with:
        - file_type: "image", "pdf", or "pptx"
        - content: extracted text or slides
        - filename: original filename
    """
    content = await file.read()
    filename = file.filename or "document"
    
    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )
    
    # Validate file type
    if not is_supported_file_type(filename, file.content_type or ""):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{filename}'. Only .jpg, .jpeg, .png, .pdf, and .pptx are supported."
        )
    
    try:
        return extract_file_for_editing(content, filename, file.content_type or "")
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to extract editable content from '{filename}': {str(e)}"
        )


@app.post("/api/save-edited-content")
async def save_edited_content(
    file: UploadFile = File(...),
    file_type: str = Form(...),  # "image" or "pptx"
    updated_content: str = Form(...),  # JSON string
):
    """
    NEW WORKFLOW: Save edited content as a reconstructed editable PPTX.
    
    Images and PDFs are rebuilt as PowerPoint slides with editable text boxes.
    Existing PPTX files keep editable text and convert OCR-detected picture text
    into real PowerPoint text boxes.
    """
    content = await file.read()
    filename = file.filename or "document"
    
    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )
    
    try:
        parsed_content = json.loads(updated_content)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON format for updated_content parameter."
        )
    
    try:
        pptx_bytes = convert_file_to_editable_pptx(
            content,
            filename,
            file.content_type or "",
            parsed_content,
        )
        return Response(
            content=pptx_bytes,
            media_type=PPTX_MEDIA_TYPE,
            headers=attachment_headers(editable_pptx_filename(filename)),
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to create editable PPTX: {str(e)}"
        )


@app.post("/api/convert-to-editable-pptx")
async def convert_to_editable_pptx(file: UploadFile = File(...)):
    """
    One-step workflow: upload JPG, PNG, PDF, or PPTX and download an editable PPTX.
    """
    content = await file.read()
    filename = file.filename or "document"

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )

    if not is_supported_file_type(filename, file.content_type or ""):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{filename}'. Only .jpg, .jpeg, .png, .pdf, and .pptx are supported."
        )

    try:
        pptx_bytes = convert_file_to_editable_pptx(
            content,
            filename,
            file.content_type or "",
        )
        return Response(
            content=pptx_bytes,
            media_type=PPTX_MEDIA_TYPE,
            headers=attachment_headers(editable_pptx_filename(filename)),
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to create editable PPTX: {str(e)}"
        )



@app.post("/api/generate-slides")
async def generate_slides(
    files: List[UploadFile] = File(...),
    num_slides: int = Form(default=8),
):
    texts = []
    analysis_images = []
    source_visuals = []

    for file in files:
        content = await file.read()
        filename = file.filename or "Uploaded file"
        if not content:
            raise HTTPException(
                status_code=400,
                detail=f"Uploaded file '{filename}' is empty. Use a real file upload, not a copied --data-raw curl body from browser devtools."
            )

        # Validate file type - accept jpg, jpeg, png, pdf, pptx
        if not is_supported_file_type(filename, file.content_type or ""):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{filename}'. Only .jpg, .jpeg, .png, .pdf, and .pptx are supported."
            )

        is_pdf = filename.lower().endswith('.pdf') or file.content_type == "application/pdf"

        if is_pdf:
            try:
                pdf_texts, pdf_images = process_pdf(content)
                texts.extend(pdf_texts)
                source_visuals.extend(pdf_images)
                analysis_images.extend(pdf_images)
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid or corrupted PDF file '{filename}': {str(e)}"
                )
            continue

        # Process PPT files
        is_ppt = filename.lower().endswith('.pptx') or \
                 file.content_type in ['application/vnd.openxmlformats-officedocument.presentationml.presentation']
        
        if is_ppt:
            try:
                text_data, _ = process_pptx(content)
                for item in text_data:
                    texts.append(item["full_text_with_label"])
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid or corrupted PPT file '{filename}': {str(e)}"
                )
        
        # Process image files
        elif file.content_type and file.content_type.startswith("image/"):
            try:
                img_data = process_image(content, file.content_type)
                img_data["filename"] = filename
                img_data["label"] = filename
                source_visuals.append(img_data)
                analysis_images.append(img_data)
                texts.append(f"Image: {filename}")
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid or corrupted image file '{filename}': {str(e)}"
                )

    if not texts and not source_visuals:
        raise HTTPException(status_code=400, detail="No content could be extracted from the uploaded files.")

    analysis_images = analysis_images[:8]

    # Truncate text to avoid token overload
    combined = "\n\n---PAGE BREAK---\n\n".join(texts)
    if len(combined) > 50000:
        combined = combined[:50000] + "\n\n[Content truncated for processing...]"
    texts = [combined] if combined else []

    try:
        slide_data = analyze_content_for_slides(texts, analysis_images, num_slides)
    except Exception as e:
        error_msg = str(e)
        # Check standard exception class names and text in error message
        exc_type = type(e).__name__
        if "AuthenticationError" in exc_type or "401" in error_msg:
            raise HTTPException(
                status_code=401,
                detail="Anthropic Authentication Failed: The API key provided is incorrect, expired, or invalid. Please check your .env file."
            )
        elif "PermissionDenied" in exc_type or "403" in error_msg:
            raise HTTPException(
                status_code=403,
                detail="Anthropic Permission Denied: Please verify your account balance, API permissions, or model access (e.g. claude-3-5-sonnet-latest)."
            )
        elif "RateLimit" in exc_type or "429" in error_msg:
            raise HTTPException(
                status_code=429,
                detail="Anthropic Rate Limit Exceeded: Too many requests or insufficient quota. Please check your Anthropic Console dashboard."
            )
        else:
            raise HTTPException(
                status_code=502,
                detail=f"Anthropic Service Error: {error_msg}"
            )

    pptx_bytes = create_presentation(slide_data, source_visuals=source_visuals)

    raw_title = slide_data.get("presentation_title", "presentation")
    filename = "".join(c for c in raw_title if c.isalnum() or c in " -_.").strip() or "presentation"
    filename = filename[:100] + ".pptx"

    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers=attachment_headers(filename),
    )

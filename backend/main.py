from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from typing import List, Dict
import os
from dotenv import load_dotenv
import json
import tempfile
from io import BytesIO
from urllib.parse import quote

# Load environment variables
load_dotenv()
if not os.environ.get("ANTHROPIC_API_KEY"):
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from processors.pdf_processor import process_pdf
from processors.image_processor import process_image, extract_text_from_image, update_image_with_text
from processors.pptx_processor import process_pptx, update_pptx_text
from ai.claude_client import analyze_content_for_slides
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
    """Check if file type is supported (jpg, jpeg, png, ppt)."""
    filename_lower = filename.lower()
    
    # Check by extension
    if filename_lower.endswith(('.jpg', '.jpeg', '.png', '.pptx', '.ppt')):
        return True
    
    # Check by content type
    if content_type in ['image/jpeg', 'image/jpg', 'image/png']:
        return True
    
    if content_type in ['application/vnd.ms-powerpoint', 
                        'application/vnd.openxmlformats-officedocument.presentationml.presentation']:
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
    Extract editable text from uploaded files (jpg, jpeg, ppt).
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
                detail=f"Unsupported file type '{filename}'. Only .jpg, .jpeg, .png, and .ppt are supported."
            )
        
        # Process PPT files
        if filename.lower().endswith(('.pptx', '.ppt')) or \
           file.content_type in ['application/vnd.ms-powerpoint',
                                 'application/vnd.openxmlformats-officedocument.presentationml.presentation']:
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
    if not is_supported_file_type(filename, ppt_file.content_type or ""):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Only .ppt files can be edited."
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
    NEW WORKFLOW: Extract text from image or PPT for editing.
    
    Returns:
        JSON with:
        - file_type: "image" or "pptx"
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
            detail=f"Unsupported file type '{filename}'. Only .jpg, .jpeg, .png, and .ppt are supported."
        )
    
    # Process PPT files
    if filename.lower().endswith(('.pptx', '.ppt')):
        try:
            text_data, _ = process_pptx(content)
            return {
                "file_type": "pptx",
                "filename": filename,
                "content": text_data,
                "success": True
            }
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to extract text from PPT: {str(e)}"
            )
    
    # Process image files
    elif file.content_type and file.content_type.startswith("image/"):
        try:
            ocr_result = extract_text_from_image(content)
            if not ocr_result["success"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to extract text from image: {ocr_result.get('error', 'Unknown error')}"
                )
            
            return {
                "file_type": "image",
                "filename": filename,
                "content_type": file.content_type,
                "content": {
                    "full_text": ocr_result["full_text"],
                    "text_blocks": ocr_result["text_blocks"],
                    "image_width": ocr_result.get("image_width"),
                    "image_height": ocr_result.get("image_height"),
                },
                "success": True
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to extract text from image: {str(e)}"
            )


@app.post("/api/save-edited-content")
async def save_edited_content(
    file: UploadFile = File(...),
    file_type: str = Form(...),  # "image" or "pptx"
    updated_content: str = Form(...),  # JSON string
):
    """
    NEW WORKFLOW: Save edited content back to file.
    
    For images: Overlay edited text on image
    For PPT: Update slide text
    
    Returns: Modified file in same format
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
    
    # Handle PPT files
    if file_type == "pptx":
        try:
            if not filename.lower().endswith(('.pptx', '.ppt')):
                raise HTTPException(
                    status_code=400,
                    detail="File type mismatch: expecting PPT file"
                )
            
            # Convert string keys to integers (slide numbers)
            updated_texts = {int(k): v for k, v in parsed_content.items()}
            
            # Process and update PPTX
            text_data, prs = process_pptx(content)
            updated_pptx = update_pptx_text(prs, updated_texts)
            
            return Response(
                content=updated_pptx,
                media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                headers=attachment_headers(filename),
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to update PPT file: {str(e)}"
            )
    
    # Handle image files
    elif file_type == "image":
        try:
            if not file.content_type or not file.content_type.startswith("image/"):
                raise HTTPException(
                    status_code=400,
                    detail="File type mismatch: expecting image file"
                )
            
            updated_image, content_type = update_image_with_text(
                content, 
                file.content_type,
                parsed_content
            )
            
            return Response(
                content=updated_image,
                media_type=content_type,
                headers=attachment_headers(filename),
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to update image file: {str(e)}"
            )
    
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown file type: {file_type}. Use 'image' or 'pptx'."
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

        # Validate file type - only accept jpg, jpeg, png, ppt
        if not is_supported_file_type(filename, file.content_type or ""):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{filename}'. Only .jpg, .jpeg, .png, and .ppt are supported."
            )

        # Process PPT files
        is_ppt = filename.lower().endswith(('.pptx', '.ppt')) or \
                 file.content_type in ['application/vnd.ms-powerpoint',
                                       'application/vnd.openxmlformats-officedocument.presentationml.presentation']
        
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

# API Endpoints Documentation

## Editable PPTX Reconstruction Workflow

The primary workflow converts uploaded visual content into a PowerPoint file where detected text is rebuilt as editable PPTX text boxes.

Supported inputs:
- Images: `.jpg`, `.jpeg`, `.png`
- Documents: `.pdf`
- Presentations: `.pptx`

Output:
- Always returns `.pptx`
- Text detected in images, PDF pages, and PPTX picture slides is placed as editable PowerPoint text
- Existing editable PPTX text remains editable

## Endpoints

### Health Check

`GET /api/health`

Response:

```json
{
  "status": "ok"
}
```

### Extract Editable Content

`POST /api/extract-editable-content`

Analyzes one uploaded file and returns detected editable text blocks for review before export.

Request:
- `file`: one `.jpg`, `.jpeg`, `.png`, `.pdf`, or `.pptx`

Response for images:

```json
{
  "file_type": "image",
  "filename": "slide.png",
  "success": true,
  "content": {
    "full_text": "Detected text",
    "text_blocks": [
      {
        "text": "Detected text",
        "originalText": "Detected text",
        "bbox": [[10, 20], [200, 20], [200, 60], [10, 60]],
        "image_width": 1280,
        "image_height": 720
      }
    ]
  }
}
```

Response for PDFs and PPTX files:

```json
{
  "file_type": "pdf",
  "filename": "deck.pdf",
  "success": true,
  "content": [
    {
      "slide_number": 1,
      "text": "Detected page text",
      "text_blocks": []
    }
  ]
}
```

### Save Edited Content As PPTX

`POST /api/save-edited-content`

Creates an editable PowerPoint from the original upload plus reviewed or edited text blocks.

Request:
- `file`: the original uploaded file
- `file_type`: `image`, `pdf`, or `pptx`
- `updated_content`: JSON string returned by the frontend editor

Response:
- Content-Type: `application/vnd.openxmlformats-officedocument.presentationml.presentation`
- Download filename: `<original-name>-editable.pptx`

### Convert Directly To Editable PPTX

`POST /api/convert-to-editable-pptx`

One-step conversion without review in the browser.

Request:
- `file`: one `.jpg`, `.jpeg`, `.png`, `.pdf`, or `.pptx`

Response:
- Editable `.pptx` download

### Generate AI Slides

`POST /api/generate-slides`

Generates a new AI-authored presentation from uploaded source material. This is separate from editable reconstruction.

Request:
- `files`: one or more images, PDFs, or PPTX files
- `num_slides`: target generated deck length

Response:
- Generated `.pptx` download

## Notes

- Image and scanned-PDF text editability depends on OCR detection quality.
- PDF files with selectable text preserve more font metadata than raster images.
- Legacy `.ppt` binary files are not supported; save them as `.pptx` first.

# API Endpoints Documentation

## NEW WORKFLOW: Edit & Download Content

The application now features a **new workflow** where users can:
1. Upload an image or PPT file
2. Extract and view all editable text
3. Edit the text directly
4. Save and download the modified file **in the same format**

---

## Two Main Workflows

### 1. **OLD WORKFLOW: AI-Powered Slide Generation**
Generate AI-powered PowerPoint presentations from images/PPT content.

### 2. **NEW WORKFLOW: Edit & Download** (Recommended)
Extract text from files → Edit text → Download modified file in same format.

---

## API Endpoints

### 1. Health Check
**Endpoint**: `GET /api/health`

**Response**:
```json
{
  "status": "ok"
}
```

---

### 2. Extract Editable Content (NEW WORKFLOW - Step 1)
**Endpoint**: `POST /api/extract-editable-content`

**Description**: Extract all text from an image or PPT file for editing.

**Request**:
- **Content-Type**: `multipart/form-data`
- **Parameter**: `file` (single file - jpg, jpeg, png, or ppt)

**Response** (PPT):
```json
{
  "file_type": "pptx",
  "filename": "presentation.pptx",
  "success": true,
  "content": [
    {
      "slide_number": 1,
      "text": "Slide title and content",
      "full_text_with_label": "Slide 1:\nSlide title and content"
    },
    {
      "slide_number": 2,
      "text": "More content",
      "full_text_with_label": "Slide 2:\nMore content"
    }
  ]
}
```

**Response** (Image - uses OCR):
```json
{
  "file_type": "image",
  "filename": "image.jpg",
  "content_type": "image/jpeg",
  "success": true,
  "content": {
    "full_text": "All extracted text from the image",
    "text_blocks": [
      {
        "text": "Text block 1",
        "confidence": 0.95,
        "bbox": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
      }
    ]
  }
}
```

---

### 3. Save Edited Content (NEW WORKFLOW - Step 2)
**Endpoint**: `POST /api/save-edited-content`

**Description**: Update text in file and return the modified version **in the same format**.

**Request**:
- **Content-Type**: `multipart/form-data`
- **Parameters**:
  - `file`: The original file (jpg, jpeg, png, or ppt)
  - `file_type`: Either `"image"` or `"pptx"`
  - `updated_content`: JSON string with updated text

**For PPT Files**, JSON format:
```json
{
  "1": "Updated slide 1 text",
  "2": "Updated slide 2 text",
  "3": "Updated slide 3 text"
}
```

**For Image Files**, JSON format:
```json
{
  "text": "Updated text to overlay on image"
}
```

**Response**:
- Returns the modified file as a download (same format as input)
- Content-Type: `image/jpeg`, `image/png`, or `application/vnd.openxmlformats-officedocument.presentationml.presentation`

---

### 4. Extract Text from Files (Legacy)
**Endpoint**: `POST /api/extract-text`

**Description**: Extract text from uploaded files (jpg, jpeg, png, or ppt).

**Response**: JSON with text organized by file

---

### 5. Update and Download (Legacy)
**Endpoint**: `POST /api/update-and-download`

**Description**: Update text in PPT file and return the modified file.

---

### 6. Generate AI Slides
**Endpoint**: `POST /api/generate-slides`

**Description**: Generate new AI-powered slides from content.

---

## Complete Workflow Example

### Step 1: Extract Text from Image
```bash
curl -X POST "http://localhost:8000/api/extract-editable-content" \
  -F "file=@my_image.jpg"
```

Response:
```json
{
  "file_type": "image",
  "filename": "my_image.jpg",
  "content_type": "image/jpeg",
  "success": true,
  "content": {
    "full_text": "Original text from image",
    "text_blocks": [...]
  }
}
```

### Step 2: Edit the Text (in Frontend)
User edits the text in the UI.

### Step 3: Save Modified File
```bash
curl -X POST "http://localhost:8000/api/save-edited-content" \
  -F "file=@my_image.jpg" \
  -F "file_type=image" \
  -F 'updated_content={"text": "New edited text for the image"}'
```

Response: Modified image file (jpg)

---

## PPT Workflow Example

### Step 1: Extract PPT Slides
```bash
curl -X POST "http://localhost:8000/api/extract-editable-content" \
  -F "file=@presentation.pptx"
```

### Step 2: Edit Slide Text (in Frontend)
User edits each slide's text.

### Step 3: Save Modified PPT
```bash
curl -X POST "http://localhost:8000/api/save-edited-content" \
  -F "file=@presentation.pptx" \
  -F "file_type=pptx" \
  -F 'updated_content={"1": "New slide 1 text", "2": "New slide 2 text"}'
```

Response: Modified presentation.pptx file

---

## Supported File Formats

- **Images**: `.jpg`, `.jpeg`, `.png`
  - Uses OCR (EasyOCR) to extract text
  - Text is overlaid on the modified image
  - Returns same image format as input

- **Presentations**: `.ppt`, `.pptx`
  - Extracts text from all slides
  - Updates slide text
  - Returns same PPT format

---

## Key Features

✅ **Same Format Return**: Upload JPG → Get JPG back; Upload PPT → Get PPT back
✅ **Full Text Editing**: All text is editable
✅ **OCR Support**: Automatically extracts text from images
✅ **No AI Required**: Fast local processing (no API calls for editing)
✅ **File Validation**: Only accepts jpg, jpeg, png, ppt formats

---

## Error Handling

All endpoints return appropriate HTTP status codes:
- `200`: Success
- `400`: Bad request / Invalid file format
- `401`: Authentication error
- `500`: Server error

Error response format:
```json
{
  "detail": "Error message describing what went wrong"
}
```

# ai-slides-generator

Convert uploaded JPG, PNG, PDF, or PPTX content into editable PowerPoint files.

The editable reconstruction workflow detects text in visual inputs, removes the detected text from the rendered background, and writes matching PowerPoint text boxes back into the same positions. Existing PPTX text remains editable, and text embedded inside PPTX images is rebuilt as editable PPTX text where OCR can detect it.

## Workflows

- **Editable PPTX**: Upload JPG, PNG, PDF, or PPTX, review detected text, then download `<filename>-editable.pptx`.
- **Generate PPTX**: Upload source material and generate a new AI-authored presentation.

## Backend

```bash
cd backend
uvicorn main:app --reload
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

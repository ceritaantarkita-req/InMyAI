# OCR

## Core behavior

- text PDFs: pypdf
- PNG/JPG/JPEG/WebP/BMP/TIFF: local Tesseract CLI

## Windows

Install Tesseract OCR and ensure `tesseract.exe` is on PATH. Restart the terminal after changing PATH.

## Linux

```bash
sudo apt install tesseract-ocr
```

## Limitations

OCR quality depends on scan resolution, language model, rotation, contrast, tables, and handwriting. P0 returns extracted text and names the engine; it does not fabricate confidence values.

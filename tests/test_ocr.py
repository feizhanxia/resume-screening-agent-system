from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from resume_agent.extraction.ocr import rapid_ocr_image


def test_bundled_rapidocr_reads_image_without_tesseract(tmp_path: Path):
    path = tmp_path / "ocr.png"
    image = Image.new("RGB", (900, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.text(
        (30, 45),
        "Python PyTorch 123",
        font=ImageFont.load_default(size=42),
        fill="black",
    )
    image.save(path)

    text, error = rapid_ocr_image(path)

    assert error is None
    assert "Python" in text

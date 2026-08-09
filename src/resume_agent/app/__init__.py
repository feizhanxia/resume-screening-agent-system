from __future__ import annotations

import os
import sys


def main() -> None:
    from PySide6.QtWidgets import QApplication

    from resume_agent.app.window import MainWindow

    application = QApplication(sys.argv)
    application.setApplicationName("简历筛选工作台")
    application.setOrganizationName("ResumeAgent")
    application.setStyle("Fusion")
    window = MainWindow()
    window.show()
    if os.getenv("RESUME_AGENT_SMOKE_TEST") == "1":
        import tempfile
        from pathlib import Path

        from PIL import Image, ImageDraw, ImageFont

        from resume_agent.extraction.ocr import (
            find_tessdata,
            find_tesseract,
            rapid_ocr_image,
        )

        application.processEvents()
        tessdata = find_tessdata()
        if not tessdata:
            raise RuntimeError("打包产物未找到 OCR 语言数据")
        from rapidocr import RapidOCR

        print(f"SMOKE_OK tessdata={tessdata} tesseract={find_tesseract() or 'not-found'}")
        print(f"SMOKE_OK rapidocr={RapidOCR.__name__}")
        with tempfile.TemporaryDirectory(prefix="resume-agent-smoke-") as temp_dir:
            image_path = Path(temp_dir) / "ocr.png"
            image = Image.new("RGB", (900, 180), "white")
            ImageDraw.Draw(image).text(
                (30, 45),
                "Python PyTorch 123",
                font=ImageFont.load_default(size=42),
                fill="black",
            )
            image.save(image_path)
            text, error = rapid_ocr_image(image_path)
            if error or "Python" not in text:
                raise RuntimeError(f"内置 OCR 自检失败：{error or text}")
            print(f"SMOKE_OK ocr={text}")
        window.close()
        return
    raise SystemExit(application.exec())


__all__ = ["main"]

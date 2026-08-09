# Third-party notices

The MIT License in this repository applies to the original Resume Screening Agent code only.
Bundled libraries, native binaries, OCR models, and other dependencies remain under their own
licenses. The Windows package includes the applicable license texts and this notice.

Key runtime components include:

| Component | License |
| --- | --- |
| Qt for Python / PySide6 / Shiboken6 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| pypdfium2 | Apache-2.0 OR BSD-3-Clause, plus PDFium third-party licenses |
| Pydantic | MIT |
| Pillow | MIT-CMU |
| python-docx | MIT |
| openpyxl | MIT |
| OpenAI Python SDK | Apache-2.0 |
| keyring | MIT |
| RapidOCR | Apache-2.0 |
| ONNX Runtime | MIT |
| NumPy | BSD-3-Clause and bundled third-party licenses |
| lxml | BSD-3-Clause |
| tqdm | MPL-2.0 and MIT |
| Tesseract language data | Apache-2.0 |
| PyInstaller bootloader | GPL-2.0-or-later with the PyInstaller bootloader exception |

The exact versions included in each Windows release are recorded in the accompanying
`windows-dependencies.txt`. Copyright and license files installed by individual packages are
preserved where the upstream package supplies them.

Qt for Python is used under the GNU Lesser General Public License version 3. The packaged
application uses replaceable Qt dynamic libraries and does not prevent reverse engineering for
the purpose of debugging modifications to those LGPL-covered libraries. Qt trademarks are not
licensed by this project.

Project pages and full terms:

- Qt for Python: <https://doc.qt.io/qtforpython-6/licenses.html>
- pypdfium2/PDFium: <https://github.com/pypdfium2-team/pypdfium2>
- RapidOCR: <https://github.com/RapidAI/RapidOCR>
- ONNX Runtime: <https://github.com/microsoft/onnxruntime>
- Tesseract tessdata: <https://github.com/tesseract-ocr/tessdata>
- PyInstaller: <https://pyinstaller.org/en/stable/license.html>

This file is a practical attribution index, not a substitute for the license texts distributed
with the corresponding components.

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    destination = Path(sys.argv[1])
    destination.parent.mkdir(parents=True, exist_ok=True)

    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((12, 12, 244, 244), radius=54, fill="#103C3A")
    draw.rounded_rectangle((59, 38, 191, 218), radius=16, fill="#F5F1E8")
    draw.polygon([(154, 38), (191, 75), (154, 75)], fill="#C9DDD9")
    for y, width in ((96, 66), (123, 88), (150, 58)):
        draw.rounded_rectangle((81, y, 81 + width, y + 9), radius=4, fill="#6E8581")
    draw.ellipse((130, 136, 218, 224), fill="#D99342")
    draw.line((151, 181, 169, 199, 201, 160), fill="white", width=13, joint="curve")
    icon_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    image.save(destination, format="ICO", sizes=icon_sizes)


if __name__ == "__main__":
    main()

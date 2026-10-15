"""Build setup/ahcode.ico: a green rounded square with a white "A-H" mark.

Uses the app's theme green (app/ui/common/theme.py GREEN). Run once and commit
the .ico; re-run only to change the design.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
GREEN = (0x13, 0x7A, 0x38, 255)
SIZE = 256

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=48, fill=GREEN)
font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 104)
text = "A-H"
left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
x = (SIZE - (right - left)) / 2 - left
y = (SIZE - (bottom - top)) / 2 - top
draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
img.save(ROOT / "setup" / "ahcode.ico",
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

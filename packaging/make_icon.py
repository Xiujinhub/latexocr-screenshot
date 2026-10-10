# -*- coding: utf-8 -*-
"""生成应用图标 packaging/latexocr.ico（浅绿圆角底 + 白色 x²）。

用法::

    D:\\Anaconda\\envs\\OCR\\python.exe packaging\\make_icon.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

SIZE = 256
HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, 'latexocr.ico')

GREEN_TOP = (74, 166, 120)      # #4aa678 主色
GREEN_BOTTOM = (58, 140, 100)   # 略深，做个很淡的渐变
FONT_CANDIDATES = (
    r'C:\Windows\Fonts\segoeuib.ttf',
    r'C:\Windows\Fonts\arialbd.ttf',
    r'C:\Windows\Fonts\msyhbd.ttc',
    r'C:\Windows\Fonts\consolab.ttf',
)


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def main() -> str:
    image = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))

    # 竖向淡渐变
    gradient = Image.new('RGBA', (1, SIZE))
    for y in range(SIZE):
        ratio = y / (SIZE - 1)
        color = tuple(int(GREEN_TOP[i] + (GREEN_BOTTOM[i] - GREEN_TOP[i]) * ratio)
                      for i in range(3)) + (255,)
        gradient.putpixel((0, y), color)
    gradient = gradient.resize((SIZE, SIZE))

    # 圆角遮罩
    mask = Image.new('L', (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=52, fill=255)
    image.paste(gradient, (0, 0), mask)

    # 白色 x²
    draw = ImageDraw.Draw(image)
    big = load_font(150)
    small = load_font(92)
    draw.text((46, 66), 'x', font=big, fill=(255, 255, 255, 255))
    draw.text((152, 30), '2', font=small, fill=(255, 255, 255, 255))

    image.save(TARGET, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                              (64, 64), (128, 128), (256, 256)])
    return TARGET


if __name__ == '__main__':
    path = main()
    print('图标已生成:', path, os.path.getsize(path), 'bytes')

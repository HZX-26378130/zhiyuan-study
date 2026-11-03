# -*- coding: utf-8 -*-
"""生成应用图标 packaging/icon.ico（构建 exe 时用）。

设计：深蓝圆角方块 + 白色「知」字，和侧栏品牌色一致。
需要 Pillow（构建环境里装，运行时不依赖）。
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon.ico')
SIZE = 256
BG = (44, 58, 99)          # 侧栏深蓝
FG = (255, 255, 255)

FONT_CANDIDATES = [
    r'C:\Windows\Fonts\msyhbd.ttc',
    r'C:\Windows\Fonts\msyh.ttc',
    r'C:\Windows\Fonts\simhei.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
]


def main():
    img = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 圆角背景
    r = 48
    d.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=r, fill=BG)
    # 顶部一条浅色高光，避免纯色显得死板
    d.rounded_rectangle([0, 0, SIZE - 1, int(SIZE * 0.42)], radius=r, fill=(58, 76, 128))

    ch = '知'
    font = None
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                font = ImageFont.truetype(p, int(SIZE * 0.58))
                break
            except OSError:
                continue
    if font is None:
        font = ImageFont.load_default()

    box = d.textbbox((0, 0), ch, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((SIZE - w) / 2 - box[0], (SIZE - h) / 2 - box[1] + SIZE * 0.02), ch, font=font, fill=FG)

    img.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print('图标已生成:', OUT, os.path.getsize(OUT), 'bytes')


if __name__ == '__main__':
    sys.exit(main())

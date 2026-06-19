# -*- coding: utf-8 -*-
"""生成应用图标 icon.ico：一个圆形按钮上印 ↵ 回车符号。"""
import math
from PIL import Image, ImageDraw, ImageFont


def draw(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 外圈阴影
    pad = max(1, size // 16)
    # 主体圆 (蓝紫渐变感的纯色)
    body = (88, 101, 242)  # Discord-ish 蓝
    d.ellipse([pad, pad, size - pad, size - pad], fill=body)

    # 高光
    hl = (255, 255, 255, 60)
    hp = size // 4
    d.ellipse([pad + hp // 2, pad + hp // 2, size - pad - hp, size - pad - hp], outline=hl, width=max(1, size // 64))

    # 回车符号 ↵ (用回车箭头近似)：画一条折线箭头
    cx, cy = size // 2, size // 2
    w = max(2, size // 16)          # 线宽
    L = size * 30 // 100            # 横线半长
    H = size * 22 // 100            # 竖线下落
    col = (255, 255, 255, 255)

    # 竖线 (从右上往下)
    x_right = cx + L
    d.line([(x_right, cy - H), (x_right, cy + H // 2)], fill=col, width=w)
    # 横线 (往左)
    d.line([(cx - L, cy + H // 2), (x_right, cy + H // 2)], fill=col, width=w)
    # 箭头 (左端三角)
    ax = cx - L
    ay = cy + H // 2
    al = size // 12
    d.polygon([
        (ax, ay),
        (ax + al, ay - al),
        (ax + al, ay + al),
    ], fill=col)

    return img


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw(s) for s in sizes]
    images[-1].save("icon.ico", format="ICO", sizes=[(s, s) for s in sizes], append_images=images[:-1])
    images[-1].save("icon.png")
    print("icon.ico / icon.png 已生成")


if __name__ == "__main__":
    main()

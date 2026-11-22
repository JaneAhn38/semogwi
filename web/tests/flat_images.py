"""test_flat_cutout.py용 그림 만들기·픽셀 읽기. 시스템 Python으로 실행합니다 (웹 가상환경에는 Pillow·numpy가 없음).

사용법: python flat_images.py <명령> <인자 JSON>
- character {"path", "gaps": [[cx, cy, gap]], "size"}: 흰 몸통 + 흰 배경 + 끊긴 외곽선 + 눈·분홍 볼
- photo {"path"}: 그라데이션 + 잡음 (사진처럼)
- product {"path"}: 흰 배경 위 선 없는 둥근 상자 (상품 사진처럼)
- noise {"path"}: 무작위 잡음
- erase {"src", "dst"}: 몸통을 지우고 외곽선만 남긴 결과 (AI 모델이 흰 몸통을 지운 경우)
- pixels {"path", "points": [[x, y]]}: RGBA 값 목록 출력
"""

import json
import sys

import numpy as np
from PIL import Image, ImageDraw

INK = (35, 30, 35)
PINK = (250, 170, 190)


def character(path, gaps=((150, 62, 3), (150, 238, 4)), size=300, outline=6, bg=(255, 255, 255)):
    s = 4
    big = Image.new("RGB", (size * s, size * s), bg)
    d = ImageDraw.Draw(big)
    d.ellipse([v * s for v in (60, 60, 240, 240)], fill=(255, 255, 255), outline=INK, width=outline * s)
    for cx, cy, gap in gaps:  # 외곽선 끊기 (몸통 쪽은 흰색 유지)
        d.rectangle([(cx - gap / 2) * s, (cy - outline) * s, (cx + gap / 2) * s, (cy + outline) * s], fill=bg)
        inner = (cy + 2, cy + outline) if cy < 150 else (cy - outline, cy - 2)
        d.rectangle([(cx - gap / 2) * s, inner[0] * s, (cx + gap / 2) * s, inner[1] * s], fill=(255, 255, 255))
    for x in (120, 180):
        d.ellipse([(x - 8) * s, 130 * s, (x + 8) * s, 148 * s], fill=INK)
        cheek = [(x - 22) * s, 160 * s, (x + 2) * s, 172 * s] if x < 150 else [(x - 2) * s, 160 * s, (x + 22) * s, 172 * s]
        d.ellipse(cheek, fill=PINK)
    big.resize((size, size), Image.LANCZOS).save(path)


command, args = sys.argv[1], json.loads(sys.argv[2])
if command == "character":
    character(args["path"], [tuple(g) for g in args.get("gaps", [(150, 62, 3), (150, 238, 4)])], args.get("size", 300))
elif command == "photo":
    rng = np.random.default_rng(1)
    y, x = np.mgrid[0:240, 0:240]
    photo = np.stack([120 + x * 0.4, 90 + y * 0.5, 160 - x * 0.2], axis=2) + rng.normal(0, 12, (240, 240, 3))
    Image.fromarray(np.clip(photo, 0, 255).astype("uint8")).save(args["path"])
elif command == "product":
    product = Image.new("RGB", (240, 240), (255, 255, 255))
    ImageDraw.Draw(product).rounded_rectangle([60, 60, 180, 180], 20, fill=(240, 200, 120))
    product.save(args["path"])
elif command == "noise":
    Image.fromarray(np.random.default_rng(2).integers(0, 255, (200, 200, 3), dtype=np.uint8)).save(args["path"])
elif command == "erase":
    with Image.open(args["src"]) as image:
        rgba = image.convert("RGBA")
    mask = Image.new("L", rgba.size, 0)
    ImageDraw.Draw(mask).ellipse([60, 60, 240, 240], outline=255, width=6)
    rgba.putalpha(mask)
    rgba.save(args["dst"])
elif command == "pixels":
    with Image.open(args["path"]) as image:
        rgba = image.convert("RGBA")
        print(json.dumps([list(rgba.getpixel(tuple(p))) for p in args["points"]]))

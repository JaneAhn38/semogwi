"""긴 상세페이지 이미지를 AI가 글자를 읽을 수 있는 크기의 조각으로 나눕니다. 시스템 Python으로 실행합니다 (웹 가상환경에 Pillow를 설치하지 않음).

사용법: python image_tiles.py <이미지> <출력 폴더> <최대 조각 수>
출력 JSON: {"width", "height", "tiles": [{"file", "top", "bottom"}], "truncated"}
- 쇼핑몰 상세 이미지는 폭 700~1000px, 높이 수천~수만 px인 경우가 많습니다. 그대로 보내면 모델 입력 크기에 맞춰 줄어 글자를 읽지 못합니다.
- 폭이 TILE_WIDTH보다 넓으면 비율대로 줄이고, 위에서부터 TILE_HEIGHT씩 OVERLAP만큼 겹쳐 자릅니다 (줄 경계의 글자가 잘리지 않게).
- 원본은 읽기만 합니다. 조각은 JPEG로 저장합니다.
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageOps

TILE_WIDTH = 1000
TILE_HEIGHT = 1400
OVERLAP = 80

source, out_dir, limit = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
out_dir.mkdir(parents=True, exist_ok=True)
with Image.open(source) as image:
    image = ImageOps.exif_transpose(image)
    width, height = image.size
    rgba = image.convert("RGBA")
rgb = Image.new("RGB", rgba.size, "white")  # 투명한 부분은 흰 바탕으로 (검게 바뀌어 글자가 안 보이는 것 방지)
rgb.paste(rgba, mask=rgba.getchannel("A"))
scale = min(1.0, TILE_WIDTH / width)
if scale < 1.0:
    rgb = rgb.resize((round(width * scale), max(1, round(height * scale))), Image.LANCZOS)
tiles, top, truncated = [], 0, False
while top < rgb.height:
    if len(tiles) >= limit:
        truncated = True
        break
    bottom = min(rgb.height, top + TILE_HEIGHT)
    name = f"{source.stem}-tile-{len(tiles) + 1:02d}.jpg"
    rgb.crop((0, top, rgb.width, bottom)).save(out_dir / name, format="JPEG", quality=88)
    tiles.append({"file": name, "top": round(top / scale), "bottom": round(bottom / scale)})
    if bottom >= rgb.height:
        break
    top = bottom - OVERLAP
print(json.dumps({"width": width, "height": height, "tiles": tiles, "truncated": truncated}))

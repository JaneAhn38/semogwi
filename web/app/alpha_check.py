"""누끼 결과 검사. 시스템 Python으로 실행합니다 (Pillow를 웹 가상환경에 설치하지 않음).

사용법: python alpha_check.py <PNG 경로>
출력 JSON: format, mode, width, height, transparent, opaque, bbox, holes
- transparent·opaque 기준값은 scripts/assign_images.py의 alpha_stats와 같습니다.
- bbox: 피사체(알파 32 이상)의 범위 [x0, y0, x1, y1]. 카드에 넣을 때 투명 여백을 빼고 크기를 맞추는 데 씁니다.
- holes: 피사체 안쪽에 갇힌 투명 영역의 비율 (피사체 범위 대비). 흰 몸통이나 얼굴이 배경과 함께 지워지면 커집니다.
  흰색 픽셀을 지우는 방식이 아니라 AI 모델 결과를 사후 검사만 합니다.
- translucent: 피사체(알파 32 이상) 중 반투명(알파 32~239)의 비율. 털이 많은 인형처럼 모델이 몸통을 반쯤만
  남기면 커지고, 카드 배경색이 피사체를 통해 비쳐 보입니다. 정상 결과는 가장자리만 반투명이라 작습니다.
"""

import json
import sys

from PIL import Image, ImageDraw

SOLID = 32  # 이 값 이상의 알파를 피사체로 봅니다
PROBE = 256  # 구멍 검사는 긴 변 256px로 줄여서 합니다


def holes_ratio(alpha: Image.Image) -> float:
    """테두리에서 이어지지 않는 투명 영역(피사체에 둘러싸인 구멍)의 비율."""
    scale = PROBE / max(alpha.size)
    small = alpha.resize((max(1, round(alpha.width * scale)), max(1, round(alpha.height * scale))))
    # 0: 투명, 255: 피사체. 1px 투명 테두리를 둘러 바깥 배경을 한 덩어리로 만듭니다
    mask = Image.new("L", (small.width + 2, small.height + 2), 0)
    mask.paste(small.point(lambda v: 255 if v >= SOLID else 0), (1, 1))
    ImageDraw.floodfill(mask, (0, 0), 128)  # 바깥 배경을 128로 칠함
    hist = mask.histogram()
    holes, subject = hist[0], hist[255]
    return round(holes / (holes + subject), 3) if subject else 0.0


with Image.open(sys.argv[1]) as image:
    fmt, mode, (width, height) = image.format, image.mode, image.size
    alpha = image.convert("RGBA").getchannel("A")

histogram = alpha.histogram()
total = sum(histogram)
bbox = alpha.point(lambda v: 255 if v >= SOLID else 0).getbbox()
print(json.dumps({
    "format": fmt,
    "mode": mode,
    "width": width,
    "height": height,
    "transparent": round(histogram[0] / total, 3),
    "opaque": round(sum(histogram[240:]) / total, 3),
    "bbox": list(bbox) if bbox else None,
    "holes": holes_ratio(alpha),
    "translucent": round(sum(histogram[SOLID:240]) / max(1, sum(histogram[SOLID:])), 3),
}))

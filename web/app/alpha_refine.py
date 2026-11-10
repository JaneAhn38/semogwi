"""누끼 결과의 알파 보정. 시스템 Python으로 실행합니다 (Pillow를 웹 가상환경에 설치하지 않음).

사용법: python alpha_refine.py <PNG 경로>   (같은 파일에 덮어씀. 웹이 새로 만든 누끼 파일에만 씁니다)

AI 모델은 흰 몸통·흰 얼굴처럼 배경과 비슷한 부분을 반투명(알파 200~250)으로 남기는 경우가 있습니다.
그러면 카드 배경색이 비쳐 보입니다. 알파 값만 곡선으로 조정해 거의 불투명한 부분을 완전히 불투명하게,
거의 투명한 잔여물을 완전히 투명하게 만들고 가장자리의 부드러운 단계는 남깁니다.
색(흰색 여부)은 보지 않으므로 흰 피사체가 지워지지 않습니다.
"""

import sys

from PIL import Image

LOW, HIGH = 16, 200  # LOW 이하 → 0, HIGH 이상 → 255, 사이는 비례


def curve(value: int) -> int:
    if value <= LOW:
        return 0
    if value >= HIGH:
        return 255
    return round((value - LOW) * 255 / (HIGH - LOW))


path = sys.argv[1]
with Image.open(path) as image:
    image = image.convert("RGBA")
    image.load()
r, g, b, a = image.split()
Image.merge("RGBA", (r, g, b, a.point(curve))).save(path, format="PNG")

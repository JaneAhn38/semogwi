"""카드뉴스 생성기.

CardNewsProvider가 웹과 AI 사이의 경계입니다. 지금은 DemoProvider만 있으며, 정해진 예시 문구와 미리 만든 레이아웃을 돌려줍니다.
실제 AI를 연결할 때는 같은 메서드를 구현한 클래스를 추가하고 get_provider만 바꿉니다. 웹 화면과 API는 고치지 않습니다.

DemoProvider는 사실 정보를 만들지 않습니다. 가격·일정·장소·캐릭터 설정을 쓰지 않고, 문구마다 데모임을 밝힙니다.
"""

import random
from typing import Protocol

THEMES = {
    "mellow-pink": {
        "label": "몽글 핑크", "bgFrom": "#FFE3EC", "bgTo": "#FFF4E8", "ink": "#4A2F40", "inkSoft": "#6B4A5E",
        "accent": "#FF9DB8", "accent2": "#BDE7DC", "accent3": "#FFE08A", "panel": "#FFFFFF",
    },
    "mint-soda": {
        "label": "민트 소다", "bgFrom": "#D5F4E9", "bgTo": "#F4FBEF", "ink": "#1F4640", "inkSoft": "#3D635C",
        "accent": "#7FD8C0", "accent2": "#FFD6A5", "accent3": "#BFD7FF", "panel": "#FFFFFF",
    },
    "lavender-cloud": {
        "label": "라벤더 구름", "bgFrom": "#E7E0FF", "bgTo": "#FCF2FF", "ink": "#3B2F5E", "inkSoft": "#5A4E7E",
        "accent": "#B9A5F5", "accent2": "#FFC7DE", "accent3": "#BDEBFF", "panel": "#FFFFFF",
    },
    "butter-cream": {
        "label": "버터 크림", "bgFrom": "#FFF1C4", "bgTo": "#FFF9EC", "ink": "#4D3A1F", "inkSoft": "#6E583A",
        "accent": "#FFCF70", "accent2": "#FFB9A3", "accent3": "#C9E8B8", "panel": "#FFFFFF",
    },
}

CONTENT_TYPES = {
    "character": "캐릭터 소개",
    "goods": "굿즈 판매",
    "popup": "팝업스토어",
    "collab": "콜라보",
}

FRAMES = ["card-01", "card-02", "card-03", "card-04", "card-05"]
IMAGE_LAYOUTS = ["image-top", "image-left", "text-top"]  # 이미지를 쓰는 카드
TEXT_LAYOUTS = ["text-focus", "text-note"]  # 이미지를 쓰지 않는 카드. card-01은 항상 cover
DEFAULT_THEME = "mellow-pink"  # 사용자가 고르지 않음. 나중에 AI가 정할 때까지 쓰는 기본값
LAYOUT_LABELS = {
    "cover": "표지",
    "image-top": "이미지 위",
    "image-left": "이미지 왼쪽",
    "text-top": "글 위",
    "text-focus": "글 중심",
    "text-note": "글 메모",
}

_CARD_TITLES = {
    "character": ["이런 친구예요", "성격 포인트", "함께하는 친구들", "더 알아보기"],
    "goods": ["어떤 상품일까요", "눈여겨볼 점", "구성 살펴보기", "구매 전 확인"],
    "popup": ["어떤 행사일까요", "언제 어디서", "즐길 거리", "방문 전 확인"],
    "collab": ["어떤 콜라보일까요", "만나는 두 세계", "콜라보 상품", "참여 방법"],
}
_CARD_ROLES = ["표지", "소개", "핵심 내용", "자세히 보기", "마무리"]
_BODY_VARIANTS = [
    "데모 문구예요. 실제 제작에서는 공식 자료로 확인한 내용이 이 자리에 들어가요.",
    "아직 AI가 쓴 글이 아니에요. 나중에 확인된 정보로 이 문구를 채울 거예요.",
    "레이아웃을 보여 주는 예시 문장이에요. 사실 정보가 아니니 게시하면 안 돼요.",
]
_COVER_BODIES = [
    "데모 미리보기예요. 내용은 아직 AI가 만들지 않았어요.",
    "예시 표지 문구예요. 실제 제작 전까지 게시하면 안 돼요.",
]
DEMO_SOURCE = "출처: 데모 (실제 출처 아님)"


class CardNewsProvider(Protocol):
    is_demo: bool

    def create_outline(self, job: dict) -> list[dict]:
        """카드 5장의 구성안을 돌려줍니다."""
        ...

    def create_outline_card(self, job: dict, frame: str, variant: int) -> dict:
        """선택한 카드 한 장의 구성안만 다시 만들어 돌려줍니다."""
        ...

    def create_layout(self, job: dict, frame: str, outline_card: dict, layout_name: str, seed: int, image: dict | None = None) -> dict:
        """카드 한 장의 Layout Spec(dict)을 돌려줍니다. image는 사용자가 고른 {assetId, variant} 또는 None입니다.

        문구는 outline_card의 값을 그대로 써야 합니다. 호출하는 쪽에서 validate_layout과 문구 일치를 검사합니다.
        """
        ...


def _text(role, text, box, font, size, color="ink", align="left", max_lines=2, valign="top"):
    x, y, w, h = box
    return {"type": "text", "role": role, "text": text, "box": {"x": x, "y": y, "w": w, "h": h},
            "font": font, "size": size, "color": color, "align": align, "valign": valign, "maxLines": max_lines}


def _image(image, box):
    x, y, w, h = box
    return {"type": "image", "assetId": image["assetId"] if image else None, "variant": image["variant"] if image else "original",
            "box": {"x": x, "y": y, "w": w, "h": h}, "fit": "contain", "radius": 40}


def _shape(kind, box, color, opacity=0.5, rotate=0):
    x, y, w, h = box
    return {"type": "shape", "kind": kind, "box": {"x": x, "y": y, "w": w, "h": h}, "color": color, "opacity": opacity, "rotate": rotate}


def _decorations(rng: random.Random) -> list[dict]:
    """카드마다 위치·모양만 조금 다른 장식. 색은 테마 토큰만 쓰므로 한 세트의 분위기가 유지됩니다."""
    corners = [(-60, -40), (880, -50), (-70, 1120), (900, 1130)]
    rng.shuffle(corners)
    shapes = []
    for (x, y), kind, color in zip(corners, rng.sample(["circle", "ring", "circle", "triangle"], 4), ["accent", "accent2", "accent3", "accent"]):
        size = rng.randint(170, 270)
        shapes.append(_shape(kind, (x, y, size, size), color, round(rng.uniform(0.4, 0.65), 2), rng.randint(-20, 20)))
    for x, y in [(rng.randint(60, 200), rng.randint(110, 150)), (rng.randint(880, 980), rng.randint(110, 150))]:
        size = rng.randint(34, 52)
        shapes.append(_shape(rng.choice(["star", "heart"]), (x, y, size, size), "accent", 0.85, rng.randint(-15, 15)))
    return shapes


class DemoProvider:
    is_demo = True

    def create_outline_card(self, job: dict, frame: str, variant: int) -> dict:
        index = FRAMES.index(frame)
        if index == 0:
            title, body = job["topic"], _COVER_BODIES[variant % len(_COVER_BODIES)]
        else:
            title = _CARD_TITLES[job["contentType"]][index - 1]
            body = _BODY_VARIANTS[(variant + index) % len(_BODY_VARIANTS)]
        return {"frame": frame, "role": _CARD_ROLES[index], "title": title, "body": body, "source": DEMO_SOURCE}

    def create_outline(self, job: dict) -> list[dict]:
        version = job["outline"]["version"] if job.get("outline") else 0
        return [self.create_outline_card(job, frame, version) for frame in FRAMES]

    def create_layout(self, job: dict, frame: str, outline_card: dict, layout_name: str, seed: int, image: dict | None = None) -> dict:
        rng = random.Random(f"{job['id']}:{frame}:{seed}")
        index = FRAMES.index(frame)
        title, body = outline_card["title"], outline_card["body"]

        elements = _decorations(rng)
        if outline_card.get("source"):
            elements.append(_text("source", outline_card["source"], (70, 56, 700, 44), "body", 28, "inkSoft"))
        elements.append(_text("page", f"{index + 1:02d}/05", (850, 56, 160, 44), "body", 28, "inkSoft", "right", 1))

        if layout_name == "cover":
            if image:
                elements += [_image(image, (140, 130, 800, 700)),
                             _text("title", title, (80, 860, 920, 230), "display", 88, "ink", "center", 3, "bottom"),
                             _text("body", body, (110, 1100, 860, 130), "body", 34, "inkSoft", "center", 3)]
            else:  # 이미지를 쓰지 않는 표지: 같은 가운데 정렬로 글만 크게
                elements += [_text("title", title, (80, 340, 920, 400), "display", 108, "ink", "center", 3, "bottom"),
                             _text("body", body, (110, 780, 860, 200), "body", 40, "inkSoft", "center", 4)]
        elif layout_name == "image-top":
            elements += [_image(image, (90, 130, 900, 680)),
                         _text("title", title, (80, 850, 920, 110), "display", 72, "ink", "left", 1),
                         _text("body", body, (80, 985, 920, 240), "body", 40, "inkSoft", "left", 4)]
        elif layout_name == "image-left":
            elements += [_image(image, (60, 170, 500, 960)),
                         _text("title", title, (590, 230, 430, 300), "display", 66, "ink", "left", 3, "bottom"),
                         _text("body", body, (590, 560, 430, 540), "body", 38, "inkSoft", "left", 9)]
        elif layout_name == "text-top":
            elements += [_text("title", title, (80, 140, 920, 110), "display", 72, "ink", "left", 1),
                         _text("body", body, (80, 265, 920, 180), "body", 40, "inkSoft", "left", 3),
                         _image(image, (140, 470, 800, 760))]
        elif layout_name == "text-focus":
            elements += [_shape("panel", (70, 290, 940, 720), "panel", 0.62),
                         _text("title", title, (130, 350, 820, 240), "display", 84, "ink", "center", 2, "bottom"),
                         _text("body", body, (130, 620, 820, 320), "body", 44, "inkSoft", "center", 5)]
        elif layout_name == "text-note":
            elements += [_text("title", title, (90, 300, 900, 300), "display", 96, "ink", "left", 3, "bottom"),
                         _text("body", body, (90, 640, 900, 420), "body", 48, "inkSoft", "left", 6)]
        else:
            raise ValueError(f"알 수 없는 레이아웃: {layout_name}")

        return {"version": 1, "frame": frame, "layoutName": layout_name, "themeId": job["style"], "elements": elements}


def get_provider() -> CardNewsProvider:
    """데모 흐름의 생성기. 실제 AI는 app/ai_provider.py입니다."""
    return DemoProvider()

"""카드 레이아웃 규격 (Layout Spec v1).

카드 한 장을 좌표와 디자인 토큰으로 설명하는 JSON입니다. 브라우저 렌더러(static/renderer.js)는 이 JSON만 그립니다.
나중에 AI가 레이아웃을 만들 때도 같은 규격을 출력하고, validate_layout을 통과한 것만 화면에 나갑니다.
규격 설명: docs/layout-spec.md
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

CANVAS_W = 1080
CANVAS_H = 1350
TEXT_MARGIN = 40  # 텍스트가 카드 가장자리에서 떨어져야 하는 최소 거리

ColorToken = Literal["ink", "inkSoft", "accent", "accent2", "accent3", "panel", "bgFrom", "bgTo"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Box(Strict):
    x: int
    y: int
    w: int = Field(gt=0)
    h: int = Field(gt=0)


class TextElement(Strict):
    type: Literal["text"] = "text"
    role: Literal["title", "body", "source", "page"]
    text: str = Field(min_length=1, max_length=200)
    box: Box
    font: Literal["display", "body"]
    size: int = Field(ge=20, le=160)
    color: Literal["ink", "inkSoft"]  # 대비가 확보된 색만 허용
    align: Literal["left", "center", "right"] = "left"
    valign: Literal["top", "middle", "bottom"] = "top"
    maxLines: int = Field(default=2, ge=1, le=12)


class ImageElement(Strict):
    type: Literal["image"] = "image"
    assetId: str | None  # None이면 "이미지 자리"로 표시
    variant: Literal["original", "cutout"] = "original"  # 원본 또는 배경을 제거한 이미지
    box: Box
    fit: Literal["contain"] = "contain"  # 잘라 내지 않음. 캐릭터·상품 이미지를 변형하지 않는 규칙
    radius: int = Field(default=36, ge=0, le=120)


class ShapeElement(Strict):
    type: Literal["shape"] = "shape"
    kind: Literal["circle", "ring", "star", "heart", "triangle", "panel", "blob", "dots", "wave", "sparkle", "pill"]
    box: Box  # 장식은 카드 밖으로 살짝 나가도 됨
    color: ColorToken
    opacity: float = Field(default=0.5, ge=0, le=1)
    rotate: int = Field(default=0, ge=-180, le=180)


Element = Annotated[TextElement | ImageElement | ShapeElement, Field(discriminator="type")]


class Background(Strict):
    start: ColorToken
    end: ColorToken
    angle: int = Field(default=135, ge=0, le=359)


class LayoutSpec(Strict):
    version: Literal[1, 2] = 1
    background: Background | None = None  # 없으면 테마 기본 배경. AI 명세는 항상 있음
    frame: Literal["card-01", "card-02", "card-03", "card-04", "card-05"]
    layoutName: str = Field(min_length=1, max_length=40)
    themeId: str
    elements: list[Element] = Field(min_length=1, max_length=30)


class LayoutError(ValueError):
    pass


def _overlaps(a: Box, b: Box) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def validate_layout(data: dict, known_themes: set[str], known_assets: set[str]) -> LayoutSpec:
    """규격·좌표·겹침을 검사합니다. 문제가 있으면 LayoutError를 냅니다 (AI 출력을 그대로 믿지 않기 위한 관문)."""
    spec = LayoutSpec.model_validate(data)
    if spec.themeId not in known_themes:
        raise LayoutError(f"알 수 없는 테마: {spec.themeId}")

    texts = [e for e in spec.elements if isinstance(e, TextElement)]
    images = [e for e in spec.elements if isinstance(e, ImageElement)]

    roles = [t.role for t in texts]
    for role in ("title", "body", "page"):
        if roles.count(role) != 1:
            raise LayoutError(f"{role} 텍스트는 정확히 1개여야 합니다 (현재 {roles.count(role)}개)")
    if roles.count("source") > 1:
        raise LayoutError("source 텍스트는 1개까지만 쓸 수 있습니다")

    for t in texts:
        b = t.box
        if b.x < TEXT_MARGIN or b.y < TEXT_MARGIN or b.x + b.w > CANVAS_W - TEXT_MARGIN or b.y + b.h > CANVAS_H - TEXT_MARGIN:
            raise LayoutError(f"{t.role} 텍스트가 안전 여백을 벗어납니다")
    for img in images:
        b = img.box
        if b.x < 0 or b.y < 0 or b.x + b.w > CANVAS_W or b.y + b.h > CANVAS_H:
            raise LayoutError("이미지가 카드 밖으로 나갑니다")
        if img.assetId is not None and img.assetId not in known_assets:
            raise LayoutError(f"이 작업에 없는 이미지입니다: {img.assetId}")

    boxes = [(t.role, t.box) for t in texts] + [("image", i.box) for i in images]
    for i, (name_a, a) in enumerate(boxes):
        for name_b, b in boxes[i + 1:]:
            if _overlaps(a, b):
                raise LayoutError(f"{name_a}와 {name_b}가 겹칩니다")
    return spec

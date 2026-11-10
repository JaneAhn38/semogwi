"""AI 디자인 명세의 검증과 안전한 자동 수정.

AI 출력을 그대로 믿지 않습니다. 문구는 서버가 승인된 구성안에서 넣고, 고칠 수 있는 문제(살짝 벗어난 박스, 작은 글자, 낮은 대비)는
자동으로 고치며, 고칠 수 없는 문제(겹침, 글자가 들어가지 않음)는 LayoutError로 돌려보내 다시 생성하게 합니다.
"""

import math
import re

from .layout import CANVAS_H, CANVAS_W, LayoutError, validate_layout

DISPLAY_FONTS = ["Jua", "Do Hyeon", "Black Han Sans", "Gaegu", "Sunflower", "Gowun Batang"]
BODY_FONTS = ["Gowun Dodum", "Noto Sans KR", "Gowun Batang", "Sunflower"]
PALETTE_KEYS = ("bgFrom", "bgTo", "ink", "inkSoft", "accent", "accent2", "accent3", "panel")
AI_THEME_ID = "ai"
MIN_TITLE = 56
MIN_BODY = 30
MIN_SMALL = 22
SAFE_MARGIN = 44  # layout.TEXT_MARGIN(40)보다 약간 안쪽
LINE_HEIGHT = 1.35
TEXT_CONTRAST = 4.5
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _rgb(hex_color: str) -> tuple[float, float, float]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def _hex(rgb) -> str:
    return "#" + "".join(f"{round(max(0, min(255, c))):02X}" for c in rgb)


def _mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _luminance(rgb) -> float:
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _fix_ink(ink: str, surfaces: list[str]) -> str:
    """대비가 부족하면 글자색을 검정 또는 흰색 쪽으로 옮깁니다."""
    rgb = _rgb(ink)
    colors = [_rgb(s) for s in surfaces]
    if all(contrast(rgb, c) >= TEXT_CONTRAST for c in colors):
        return ink.upper()
    average = sum(_luminance(c) for c in colors) / len(colors)
    target = (0, 0, 0) if average > 0.18 else (255, 255, 255)
    for step in range(1, 21):
        moved = _mix(rgb, target, step / 20)
        if all(contrast(moved, c) >= TEXT_CONTRAST for c in colors):
            return _hex(moved)
    raise LayoutError("글자색과 배경의 대비를 맞출 수 없어요")


def clean_theme(raw: dict) -> dict:
    palette = raw.get("palette") or {}
    for key in PALETTE_KEYS:
        if not HEX_RE.match(str(palette.get(key, ""))):
            raise LayoutError(f"팔레트 {key} 색상값이 올바르지 않아요")
    surfaces = [palette["bgFrom"], palette["bgTo"], palette["panel"]]
    fixed = {key: palette[key].upper() for key in PALETTE_KEYS}
    fixed["ink"] = _fix_ink(palette["ink"], surfaces)
    fixed["inkSoft"] = _fix_ink(palette["inkSoft"], surfaces)
    display = raw.get("displayFont")
    body = raw.get("bodyFont")
    return {
        "source": "ai",
        "themeId": AI_THEME_ID,
        "label": str(raw.get("name") or "AI 테마")[:30],
        "rationale": str(raw.get("rationale") or "")[:200],
        "palette": fixed,
        "fonts": {"display": display if display in DISPLAY_FONTS else DISPLAY_FONTS[0],
                  "body": body if body in BODY_FONTS else BODY_FONTS[0]},
    }


def _char_width(ch: str) -> float:
    if ch == " ":
        return 0.3
    if ord(ch) > 0x2E7F:
        return 1.0  # 한글·한자: 실제보다 약간 넉넉하게
    if ch in ".,:;!?'\"()[]{}|·":
        return 0.4
    return 0.62


def estimate_lines(text: str, size: int, width: int) -> int:
    """렌더러와 같은 방식(띄어쓰기 우선)으로 줄 수를 넉넉하게 추정합니다."""
    limit = width / size
    lines = 0
    for paragraph in text.split("\n"):
        current = 0.0
        count = 1
        for word in paragraph.split(" "):
            word_width = sum(_char_width(c) for c in word)
            needed = word_width if current == 0 else current + 0.3 + word_width
            if needed <= limit:
                current = needed
                continue
            if current > 0:
                count += 1
            current = 0.0
            for ch in word:
                w = _char_width(ch)
                if current + w > limit and current > 0:
                    count += 1
                    current = w
                else:
                    current += w
        lines += count
    return lines


def _box_tuple(box: dict) -> tuple[int, int, int, int]:
    return int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"])


def _overlaps(a: dict, b: dict) -> bool:
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]


def _clamp_box(box: dict, name: str, margin: int) -> dict:
    x, y, w, h = _box_tuple(box)
    max_w, max_h = CANVAS_W - 2 * margin, CANVAS_H - 2 * margin
    if w <= 0 or h <= 0:
        raise LayoutError(f"{name} 박스 크기가 잘못됐어요")
    w, h = min(w, max_w), min(h, max_h)
    x = min(max(x, margin), CANVAS_W - margin - w)
    y = min(max(y, margin), CANVAS_H - margin - h)
    return {"x": x, "y": y, "w": w, "h": h}


def _grow_downward(box: dict, needed: int, others: list[dict]) -> None:
    """글자가 조금 넘치면 아래쪽 빈 공간까지 박스를 늘립니다."""
    limit = CANVAS_H - SAFE_MARGIN
    for other in others:
        if other["x"] < box["x"] + box["w"] and box["x"] < other["x"] + other["w"] and other["y"] >= box["y"] + box["h"]:
            limit = min(limit, other["y"] - 12)
    box["h"] = max(box["h"], min(needed, limit - box["y"]))


def _fit_text(el: dict, minimum: int, others: list[dict]) -> None:
    box = el["box"]
    size = max(int(el.get("size", minimum)), minimum)
    while True:
        lines = estimate_lines(el["text"], size, box["w"])
        needed = math.ceil(lines * size * LINE_HEIGHT)
        if needed <= box["h"]:
            break
        _grow_downward(box, needed, others)
        if needed <= box["h"]:
            break
        if size <= minimum:
            raise LayoutError(f"{el['role']} 글자가 박스에 들어가지 않아요 ({lines}줄, 필요한 높이 {needed}, 박스 높이 {box['h']}). 박스를 키워 주세요")
        size = max(minimum, size - 4)
    el["size"] = min(size, 160)
    el["maxLines"] = max(lines, min(12, int(box["h"] // (size * LINE_HEIGHT))))


def _background_colors(spec: dict, palette: dict) -> tuple:
    bg = spec["background"]
    return _rgb(palette[bg["start"]]), _rgb(palette[bg["end"]])


def _check_background(spec: dict, palette: dict) -> None:
    """글자가 배경에서 읽히지 않는 조합이면 검증된 기본 배경으로 되돌립니다."""
    bg = spec.get("background") or {}
    if bg.get("start") not in PALETTE_KEYS or bg.get("end") not in PALETTE_KEYS or bg.get("start") in ("ink", "inkSoft") or bg.get("end") in ("ink", "inkSoft"):
        spec["background"] = {"start": "bgFrom", "end": "bgTo", "angle": int(bg.get("angle", 135) or 135) % 360}
        return
    spec["background"] = {"start": bg["start"], "end": bg["end"], "angle": int(bg.get("angle", 135) or 135) % 360}
    colors = _background_colors(spec, palette)
    if any(contrast(_rgb(palette[ink]), c) < TEXT_CONTRAST for ink in ("ink", "inkSoft") for c in colors):
        spec["background"].update(start="bgFrom", end="bgTo")


def _soften_shapes(spec: dict, texts: list[dict], palette: dict) -> None:
    """글자와 겹치는 장식은 글자가 읽힐 만큼 옅게 합니다. 없애지는 않습니다."""
    start, end = _background_colors(spec, palette)
    base = _mix(start, end, 0.5)
    for shape in (e for e in spec["elements"] if e["type"] == "shape"):
        for text in texts:
            if not _overlaps(shape["box"], text["box"]):
                continue
            ink = _rgb(palette[text["color"]])
            shape_color = _rgb(palette[shape["color"]])
            while shape["opacity"] > 0.05 and contrast(ink, _mix(base, shape_color, shape["opacity"])) < TEXT_CONTRAST:
                shape["opacity"] = round(shape["opacity"] - 0.05, 2)


def _image_element(el: dict, refs: dict, required: dict | None, locked: bool) -> dict | None:
    ref = el.get("imageRef")
    if ref is not None:
        image = refs.get(ref)
        if image is None:
            raise LayoutError(f"없는 이미지를 썼어요: {ref}")
    elif el.get("assetId"):
        image = {"assetId": el["assetId"], "variant": el.get("variant", "original")}
    else:
        return None  # 빈 이미지 자리는 만들지 않습니다
    if locked:
        if not required:
            return None
        image = required
    return {"type": "image", "assetId": image["assetId"], "variant": image["variant"],
            "box": _clamp_box(el["box"], "이미지", 0), "fit": "contain", "radius": max(0, min(120, int(el.get("radius", 36))))}


def finalize_card(raw: dict, card: dict, theme: dict, *, refs: dict | None = None, required_image: dict | None = None,
                  image_locked: bool = False, known_assets: set[str] = frozenset()) -> dict:
    """AI 카드 명세에 승인된 문구를 넣고 고친 뒤 검증합니다. 돌려준 spec은 그대로 그릴 수 있습니다."""
    frame = card["frame"]
    palette = theme["palette"]
    index = int(frame[-2:])
    texts_by_role = {"title": card["title"], "body": card["body"], "page": f"{index:02d}/05"}
    if card.get("source"):
        texts_by_role["source"] = card["source"]

    shapes, images, texts = [], [], []
    seen = set()
    for el in raw.get("elements", []):
        kind = el.get("type")
        if kind == "shape":
            if len(shapes) < 12:
                shapes.append({"type": "shape", "kind": el.get("kind", "circle"), "box": {k: int(el["box"][k]) for k in "xywh"},
                               "color": el.get("color", "accent"), "opacity": max(0.0, min(1.0, float(el.get("opacity", 0.5)))),
                               "rotate": ((int(el.get("rotate", 0)) + 180) % 360) - 180})
        elif kind == "image":
            image = _image_element(el, refs or {}, required_image, image_locked)
            if image:
                images.append(image)
        elif kind == "text":
            role = el.get("role")
            if role not in texts_by_role:
                continue  # 빈 출처처럼 쓸 문구가 없는 역할은 뺍니다
            if role in seen:
                raise LayoutError(f"{role} 텍스트가 2개예요")
            seen.add(role)
            texts.append({"type": "text", "role": role, "text": texts_by_role[role], "box": _clamp_box(el["box"], role, SAFE_MARGIN),
                          "font": el.get("font", "display" if role == "title" else "body"), "size": int(el.get("size", 40)),
                          "color": el.get("color", "ink") if el.get("color") in ("ink", "inkSoft") else "ink",
                          "align": el.get("align", "left"), "valign": el.get("valign", "top"), "maxLines": 2})
    missing = set(texts_by_role) - seen
    if missing:
        raise LayoutError(f"{sorted(missing)} 텍스트 박스가 없어요")
    if len(images) > 1:
        raise LayoutError("이미지는 카드당 1개만 쓸 수 있어요")
    if image_locked and required_image and not images:
        raise LayoutError("이 카드에는 지정된 이미지를 넣어야 해요")

    minimums = {"title": MIN_TITLE, "body": MIN_BODY, "source": MIN_SMALL, "page": MIN_SMALL}
    solid = [t["box"] for t in texts] + [i["box"] for i in images]
    for text in texts:
        others = [b for b in solid if b is not text["box"]]
        _fit_text(text, minimums[text["role"]], others)

    # 장식은 항상 맨 아래, 그 위에 이미지와 글자를 놓아 가려지지 않게 합니다
    spec = {"version": 2, "frame": frame, "layoutName": str(raw.get("layoutLabel") or raw.get("layoutName") or "AI 디자인")[:40],
            "themeId": AI_THEME_ID, "background": raw.get("background") or {}, "elements": shapes + images + texts}
    _check_background(spec, palette)
    _soften_shapes(spec, texts, palette)
    validated = validate_layout(spec, {AI_THEME_ID}, set(known_assets))
    return validated.model_dump()


def layout_signature(spec: dict) -> tuple:
    """카드 구성을 비교하기 위한 값. 주요 박스를 100px 단위로 묶습니다."""
    parts = []
    for el in spec["elements"]:
        if el["type"] == "image" or el.get("role") in ("title", "body"):
            box = el["box"]
            name = el.get("role", "image")
            parts.append((name, round(box["x"] / 100), round(box["y"] / 100), round(box["w"] / 100), round(box["h"] / 100)))
    return tuple(sorted(parts))

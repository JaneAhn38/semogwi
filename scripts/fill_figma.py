r"""
세모귀 카드뉴스 - fill-figma 보조 프로그램 (fill_figma.py)

fill-figma Skill이 Figma 작업 전후에 사용하는 로컬 검사·코드 생성 도구입니다.
Figma에 직접 접속하지 않으며, 표준 라이브러리만 사용합니다.

[사용법]
    py scripts/fill_figma.py validate   projects/날짜_주제/slides.json
    py scripts/fill_figma.py render     <단계> projects/날짜_주제/slides.json
    py scripts/fill_figma.py verify-png projects/날짜_주제/png

    validate   : slides.json 규격, 글자 수, 줄바꿈 위험, 이미지 파일·해상도·출처, 출력 폴더를 검사합니다.
                 오류가 있으면 종료 코드 1, 경고만 있으면 0을 반환합니다.
    render     : Figma MCP use_figma에 넘길 JavaScript를 출력합니다.
                 단계: preflight, clone, fill-text, verify, signature
                 slides.json 규격 오류가 있으면 코드를 만들지 않고 종료 코드 1을 반환합니다.
                 (png/ 폴더에 PNG가 이미 있는지는 보지 않습니다. 내보낸 뒤 signature 단계에서도 쓰기 때문입니다.)
    verify-png : card-01.png ~ card-05.png가 모두 있고 1080x1350 PNG인지 검사합니다.

    프로젝트 루트(semogwi)에서 실행합니다.
"""

import argparse
import json
import math
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIGMA_JS_DIR = Path(__file__).resolve().parent / "figma"

# --- 템플릿 규격 (templates/layers.md, templates/figma-config.md 기준) ---
SERIES = "세모귀"
TEMPLATE_PAGE = "Page 1"
FRAMES = [f"card-0{i}" for i in range(1, 6)]
LAYERS = {
    "title": "TEXT",
    "body": "TEXT",
    "main-image": "RECTANGLE",
    "page-number": "TEXT",
    "source": "TEXT",
    "bottom-overlay": "RECTANGLE",
}
FRAME_SIZE = (1080, 1350)
MAIN_IMAGE_SIZE = (908, 780)
IMAGE_FRAMES = {"card-01"}  # MVP: 표지만 이미지 사용

# --- 글자 수 규칙 (줄바꿈 문자 \n은 세지 않음) ---
TITLE_MAX = 20
BODY_MAX = 80
SOURCE_MAX = 30
SOURCE_PREFIX = "출처: "

# --- 레이아웃 기준 (2026-10-29 테스트 실측값 기반 추정치) ---
TITLE_ONE_LINE_SAFE = 16  # Jua 80px, 너비 960: 14자가 약 800px → 17자 이상은 2줄 위험
BODY_LINE_SAFE = 42       # Gowun Dodum 28px, 너비 960: 45자 한 줄 / 47자에서 줄바꿈 관찰
BODY_MAX_LINES = 2
LAYOUT = {
    "titleLineHeight": 100,  # title 한 줄 높이 실측값(px). 템플릿 자리표시 제목이 이 높이인지 preflight가 확인
    "minGap": 20,          # title 아래 끝과 body 위 끝 사이 최소 간격(px)
    "bottomMargin": 60,    # body 아래 끝과 프레임 아래 끝 사이 최소 여백(px)
    "sideGap": 20,         # source 오른쪽 끝과 page-number 왼쪽 끝 사이 최소 간격(px)
    "bodyLineHeight": 41,  # body 한 줄 높이 실측값(px)
    "bodyMaxLines": BODY_MAX_LINES,
}

# --- 이미지 ---
UPSCALE_WARN = 1.0    # FIT 배율이 1을 넘으면 확대(흐려짐) 경고
UPSCALE_STRONG = 1.25  # 이 배율을 넘으면 강한 경고
CUTOUT_SUGGEST_SIZE = 1024  # 누끼를 다시 만들 때 권장하는 --max-size (메모리 부담이 크지 않은 값)
FIGMA_FORMATS = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}

STEPS = ["preflight", "clone", "fill-text", "verify", "signature"]


# ---------------------------------------------------------------------------
# 이미지 헤더 읽기 (확장자가 아니라 파일 내용으로 형식 판별)
# ---------------------------------------------------------------------------
def image_info(path: Path):
    """(형식, 너비, 높이)를 반환합니다. 알 수 없으면 (None, None, None)."""
    data = path.read_bytes()[:64 * 1024]
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return "png", w, h
    if data[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10])
        return "gif", w, h
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X":
            w = int.from_bytes(data[24:27], "little") + 1
            h = int.from_bytes(data[27:30], "little") + 1
            return "webp", w, h
        if chunk == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return "webp", w & 0x3FFF, h & 0x3FFF
        if chunk == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return "webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        return "webp", None, None
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "jpeg", w, h
            seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + seg_len
        return "jpeg", None, None
    return None, None, None


EXT_FORMATS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp", ".gif": "gif"}


# ---------------------------------------------------------------------------
# sources.md 조회
# ---------------------------------------------------------------------------
def find_source_row(image_rel: str):
    """sources.md 이미지 목록에서 누끼 경로(또는 원본 경로)가 일치하는 행을 찾습니다."""
    sources = ROOT / "sources.md"
    if not sources.is_file():
        return None
    for line in sources.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) >= 6 and image_rel in (cells[1], cells[2]):
            return {
                "character": cells[0],
                "original": cells[1],
                "cutout": cells[2],
                "url": cells[3],
                "owner": cells[4],
                "permission": cells[5],
                "note": cells[6] if len(cells) > 6 else "",
            }
    return None


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------
def text_len(s: str) -> int:
    return len(s.replace("\r", "").replace("\n", ""))


def project_page_name(slides_path: Path):
    """projects/YYYY-MM-DD_주제/slides.json → 세모귀_YYYY-MM-DD_주제"""
    folder = slides_path.parent.name
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_.+", folder):
        return None
    return f"{SERIES}_{folder}"


def validate(slides_path: Path, check_output: bool = True):
    errors, warnings, rows = [], [], []

    if not slides_path.is_file():
        return {"errors": [f"slides.json을 찾을 수 없습니다: {slides_path}"], "warnings": [], "rows": []}
    try:
        data = json.loads(slides_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"errors": [f"JSON 형식 오류: {e}"], "warnings": [], "rows": []}

    page_name = project_page_name(slides_path)
    if page_name is None:
        errors.append(f"프로젝트 폴더 이름이 'YYYY-MM-DD_주제' 형식이 아닙니다: {slides_path.parent.name}")

    # 상위 필드
    for key in ("series", "topic", "character", "slides"):
        if key not in data:
            errors.append(f"상위 필드 '{key}'가 없습니다")
    if data.get("series") != SERIES:
        errors.append(f"series는 '{SERIES}'여야 합니다 (현재: {data.get('series')!r})")
    if not str(data.get("topic", "")).strip():
        errors.append("topic이 비어 있습니다")
    character = str(data.get("character", ""))
    if not character or not (ROOT / "assets" / "characters" / character).is_dir():
        errors.append(f"assets/characters/{character} 폴더가 없습니다")

    slides = data.get("slides", [])
    if not isinstance(slides, list) or len(slides) != 5:
        errors.append(f"slides는 5개여야 합니다 (현재: {len(slides) if isinstance(slides, list) else '목록 아님'})")
        slides = slides if isinstance(slides, list) else []
    if not all(isinstance(s, dict) for s in slides):
        errors.append("slides의 각 항목은 객체({...})여야 합니다")
        slides = [s for s in slides if isinstance(s, dict)]
    frames = [s.get("frame") for s in slides]
    if frames != FRAMES:
        errors.append(f"frame은 card-01 ~ card-05 순서로 중복 없이 있어야 합니다 (현재: {frames})")

    for s in slides:
        fr = s.get("frame", "?")
        for f in ("frame", "title", "body", "source", "image"):
            if f not in s:
                errors.append(f"{fr}: '{f}' 필드가 없습니다")
            elif not isinstance(s[f], str):
                errors.append(f"{fr}: '{f}'는 문자열이어야 합니다 (현재: {type(s[f]).__name__})")
        extra = set(s) - {"frame", "title", "body", "source", "image"}
        if extra:
            warnings.append(f"{fr}: 규격에 없는 필드는 무시됩니다: {sorted(extra)}")

        title = str(s.get("title", ""))
        body = str(s.get("body", ""))
        source = str(s.get("source", ""))
        image = str(s.get("image", "") or "")
        t, b, src = text_len(title), text_len(body), text_len(source)

        # title
        if t == 0:
            errors.append(f"{fr}: title이 비어 있습니다")
        if t > TITLE_MAX:
            errors.append(f"{fr}: title {t}자 > {TITLE_MAX}자")
        if "\n" in title:
            errors.append(f"{fr}: title에는 줄바꿈을 넣을 수 없습니다 (2줄이 되면 body와 겹침)")
        elif TITLE_ONE_LINE_SAFE < t <= TITLE_MAX:
            warnings.append(f"{fr}: title {t}자 — {TITLE_ONE_LINE_SAFE}자를 넘으면 2줄로 넘어가 body와 겹칠 수 있습니다 (fill-text 단계 레이아웃 검사로 최종 확인)")

        # body
        if b == 0:
            errors.append(f"{fr}: body가 비어 있습니다")
        if b > BODY_MAX:
            errors.append(f"{fr}: body {b}자 > {BODY_MAX}자")
        body_lines = body.replace("\r", "").split("\n")
        if len(body_lines) > BODY_MAX_LINES:
            warnings.append(f"{fr}: body가 {len(body_lines)}줄입니다 (권장 {BODY_MAX_LINES}줄 이하)")
        for i, line in enumerate(body_lines, 1):
            if line != line.strip():
                warnings.append(f"{fr}: body {i}번째 줄 앞뒤에 공백이 있습니다")
            if len(line) > BODY_LINE_SAFE:
                where = "줄바꿈(\\n) 없이" if len(body_lines) == 1 else f"{i}번째 줄이"
                warnings.append(f"{fr}: body {where} {len(line)}자 — 한 줄 {BODY_LINE_SAFE}자를 넘으면 Figma가 글자 단위로 줄을 바꿔 단어 중간이 끊길 수 있습니다. write-copy에서 띄어쓰기 위치에 \\n을 넣어 주세요")

        # source
        if src > SOURCE_MAX:
            errors.append(f"{fr}: source {src}자 > {SOURCE_MAX}자")
        if source and not source.startswith(SOURCE_PREFIX):
            errors.append(f"{fr}: source는 '{SOURCE_PREFIX}'로 시작해야 합니다")
        if "\n" in source:
            errors.append(f"{fr}: source에는 줄바꿈을 넣을 수 없습니다")

        # image
        img_state = "-"
        if image:
            img_state = check_image(fr, image, character, errors, warnings)
        rows.append({"frame": fr, "title": t, "body": b, "bodyLines": len(body_lines), "source": src,
                     "sourceHidden": src == 0, "image": image, "imageState": img_state})

    # 출력 폴더 덮어쓰기 방지
    png_dir = slides_path.parent / "png"
    existing = sorted(p.name for p in png_dir.glob("card-0*.png")) if check_output and png_dir.is_dir() else []
    if existing:
        errors.append(f"{png_dir.relative_to(ROOT) if png_dir.is_relative_to(ROOT) else png_dir}에 이미 PNG가 있습니다 {existing} — 덮어쓰지 않도록 중단합니다")

    return {"pageName": page_name, "errors": errors, "warnings": warnings, "rows": rows}


def check_image(fr, image, character, errors, warnings):
    if fr not in IMAGE_FRAMES:
        errors.append(f"{fr}: MVP에서는 {sorted(IMAGE_FRAMES)}에만 image를 넣습니다")
    if Path(image).is_absolute() or ".." in Path(image).parts:
        errors.append(f"{fr}: image는 프로젝트 루트 기준 상대 경로여야 합니다: {image}")
        return "INVALID"
    expected_prefix = f"assets/characters/{character}/cutout/"
    if not image.replace("\\", "/").startswith(expected_prefix):
        errors.append(f"{fr}: image는 {expected_prefix} 아래의 누끼 이미지여야 합니다")
    path = ROOT / image
    if not path.is_file():
        errors.append(f"{fr}: image 파일이 없습니다: {image}")
        return "MISSING"

    fmt, w, h = image_info(path)
    if fmt is None:
        errors.append(f"{fr}: 이미지 형식을 알 수 없습니다 (PNG/JPG/WebP/GIF만 지원): {image}")
        return "UNKNOWN"
    ext_fmt = EXT_FORMATS.get(path.suffix.lower())
    if ext_fmt != fmt:
        warnings.append(f"{fr}: 확장자({path.suffix})와 실제 형식({fmt})이 다릅니다. 업로드 Content-Type은 실제 형식({FIGMA_FORMATS[fmt]})으로 보냅니다")
    if fmt != "png":
        warnings.append(f"{fr}: 누끼 이미지는 투명 배경 PNG가 기준입니다 (현재: {fmt})")
    if path.stat().st_size > 10 * 1024 * 1024:
        errors.append(f"{fr}: 이미지가 10MB를 넘어 Figma에 업로드할 수 없습니다")

    state = f"{fmt} {w}x{h}"
    if w and h:
        scale = min(MAIN_IMAGE_SIZE[0] / w, MAIN_IMAGE_SIZE[1] / h)
        state += f", FIT x{scale:.2f}"
        if scale > UPSCALE_WARN:
            level = "많이 흐려질 수 있습니다" if scale > UPSCALE_STRONG else "조금 흐려질 수 있습니다"
            warnings.append(
                f"{fr}: 이미지 {w}x{h}가 main-image({MAIN_IMAGE_SIZE[0]}x{MAIN_IMAGE_SIZE[1]})보다 작아 FIT으로 {scale:.2f}배 확대되어 {level}. "
                f"확대 없이 넣으려면 {MAIN_IMAGE_SIZE[0]}x{MAIN_IMAGE_SIZE[1]} 안에 꽉 차는 크기(이 비율이면 {round(w * scale)}x{round(h * scale)}) 이상이 필요합니다"
            )
            hint = upscale_hint(image)
            if hint:
                warnings.append(f"{fr}: {hint}")

    row = find_source_row(image)
    if row is None:
        errors.append(f"{fr}: sources.md에 이 이미지의 출처가 없습니다: {image}")
    elif row["permission"] != "허가됨":
        warnings.append(f"{fr}: sources.md 사용 허가 여부가 '{row['permission']}'입니다 — 테스트 외 게시 금지")
    return state


def upscale_hint(image_rel):
    """원본 해상도를 보고 cutout.py를 더 큰 --max-size로 다시 돌리면 해결되는지 안내합니다."""
    row = find_source_row(image_rel)
    if not row or not row["original"] or row["original"] == "-":
        return "sources.md에서 원본 경로를 찾지 못했습니다. 원본을 확인해 주세요"
    original = ROOT / row["original"]
    if not original.is_file():
        return f"원본 파일이 없습니다: {row['original']}"
    fmt, w, h = image_info(original)
    if not (w and h):
        return f"원본 해상도를 읽지 못했습니다: {row['original']}"
    longest = max(w, h)
    original_scale = min(MAIN_IMAGE_SIZE[0] / w, MAIN_IMAGE_SIZE[1] / h)
    if original_scale > UPSCALE_WARN:
        need_w, need_h = math.ceil(w * original_scale), math.ceil(h * original_scale)
        return (f"원본({fmt} {w}x{h}) 자체가 작아 누끼를 다시 만들어도 FIT {original_scale:.2f}배 확대를 피할 수 없습니다. "
                f"이 비율이면 {need_w}x{need_h} 이상인 원본이 필요합니다. 원본을 임의로 확대하지 말고 더 큰 원본을 구해 주세요")
    # cutout.py는 긴 변을 max_size로 줄이기만 하므로, 확대 없이 넣을 수 있는 최소 긴 변 = 원본 긴 변 × FIT 배율
    need = math.ceil(longest * original_scale)
    size = min(longest, max(need, CUTOUT_SUGGEST_SIZE))
    cutout_dir = Path(image_rel).parent.as_posix()
    return (f"원본({fmt} {w}x{h})은 충분히 큽니다 (누끼 긴 변 {need}px 이상이면 확대 없음). "
            f"기존 누끼를 덮어쓰지 않도록 새 파일 이름으로 다시 만드세요: "
            f"py scripts/cutout.py {row['original']} {cutout_dir}/<새 이름>.png --max-size {size}")


def print_validation(result):
    print(f"대상 페이지 이름: {result.get('pageName')}")
    if result["rows"]:
        print(f"{'frame':8} {'title':>7} {'body':>7} {'줄':>3} {'source':>8}  image")
        for r in result["rows"]:
            src = "숨김" if r["sourceHidden"] else f"{r['source']}/{SOURCE_MAX}"
            img = f"{r['image']} [{r['imageState']}]" if r["image"] else "(없음)"
            print(f"{r['frame']:8} {r['title']:>3}/{TITLE_MAX} {r['body']:>3}/{BODY_MAX} {r['bodyLines']:>3} {src:>8}  {img}")
    for e in result["errors"]:
        print(f"[오류] {e}")
    for w in result["warnings"]:
        print(f"[경고] {w}")
    print("결과:", "실패" if result["errors"] else ("통과 (경고 있음)" if result["warnings"] else "통과"))


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------
def render(step: str, slides_path: Path) -> str:
    result = validate(slides_path, check_output=False)
    if result["errors"]:
        for e in result["errors"]:
            print(f"[오류] {e}", file=sys.stderr)
        raise SystemExit(1)
    data = json.loads(slides_path.read_text(encoding="utf-8"))
    page_name = result["pageName"]
    payload = {
        "templatePage": TEMPLATE_PAGE,
        "pageName": page_name,
        "frames": FRAMES,
        "layers": LAYERS,
        "frameSize": {"w": FRAME_SIZE[0], "h": FRAME_SIZE[1]},
        "imageFrames": sorted(IMAGE_FRAMES),
        "layout": LAYOUT,
        "slides": [
            {
                "frame": s["frame"],
                "title": s["title"],
                "body": s["body"].replace("\r", ""),
                "source": s.get("source", "") or "",
                "hasImage": bool(s.get("image")),
            }
            for s in data["slides"]
        ],
    }
    common = (FIGMA_JS_DIR / "_common.js").read_text(encoding="utf-8")
    body = (FIGMA_JS_DIR / f"{step}.js").read_text(encoding="utf-8")
    return f"const INPUT = {json.dumps(payload, ensure_ascii=False)};\n{common}\n{body}"


# ---------------------------------------------------------------------------
# verify-png
# ---------------------------------------------------------------------------
def verify_png(png_dir: Path) -> int:
    ok = True
    for name in FRAMES:
        p = png_dir / f"{name}.png"
        if not p.is_file():
            print(f"{p.name:12} 없음  FAIL")
            ok = False
            continue
        fmt, w, h = image_info(p)
        good = fmt == "png" and (w, h) == FRAME_SIZE
        ok &= good
        print(f"{p.name:12} {fmt} {w}x{h}  {p.stat().st_size:,} bytes  {'OK' if good else 'FAIL'}")
    print("결과:", "통과" if ok else "실패")
    return 0 if ok else 1


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="fill-figma 보조 프로그램")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="slides.json 검사")
    v.add_argument("slides")
    v.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    r = sub.add_parser("render", help="use_figma용 JavaScript 출력")
    r.add_argument("step", choices=STEPS)
    r.add_argument("slides")
    p = sub.add_parser("verify-png", help="PNG 출력물 검사")
    p.add_argument("png_dir")
    args = parser.parse_args()

    if args.cmd == "validate":
        result = validate(Path(args.slides).resolve())
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print_validation(result)
        return 1 if result["errors"] else 0
    if args.cmd == "render":
        print(render(args.step, Path(args.slides).resolve()))
        return 0
    return verify_png(Path(args.png_dir).resolve())


if __name__ == "__main__":
    sys.exit(main())

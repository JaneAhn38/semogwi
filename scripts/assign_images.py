r"""
세모귀 카드뉴스 - 카드별 이미지 지정 처리 (assign_images.py)

사용자가 card-01 ~ card-05에 지정한 이미지(card-images.json)를 읽어 Figma에 넣을 배치용 이미지를 만들고,
출처·사용 권한을 프로젝트 sources.md에, 카드별 결과를 cutout-check.md에 기록합니다.
write-copy는 cutout-check.md의 "결과 파일" 칸을 slides.json `image`에 그대로 쓰고, fill-figma가 FIT으로 배치합니다.

[사용법]
    py scripts/assign_images.py <프로젝트 폴더>

    예) py scripts/assign_images.py projects/2026-11-05_치이카와-코인-실린더

[입력] <프로젝트 폴더>/card-images.json  (규격: templates/card-images.md)
    {
      "character": "chiikawa",
      "cards": {
        "card-01": {"file": "input/cards/photo.jpg", "cutout": false,
                    "source": "사용자 촬영", "owner": "확인 필요", "permission": "허가됨"},
        "card-02": null
      }
    }

[출력]
    <프로젝트>/input/placed/img-NN.<확장자>   배치용 이미지 (input/ 아래라 Git 제외)
    <프로젝트>/sources.md                     이미지 출처·저작권자·사용 권한 (프로젝트별, 행 추가)
    <프로젝트>/cutout-check.md                카드별 결과 (write-copy가 image 값을 읽음)
    <프로젝트>/card-images-result.json        같은 결과 (버튼 프로그램용)

[규칙]
    - FIT이 기본입니다. 원본은 그대로 두고, EXIF 회전 정보가 있으면 회전을 보정한 사본을 만듭니다.
    - "cutout": true인 카드만 scripts/cutout.py로 배경을 제거합니다 (--max-size 1024).
    - 같은 파일·같은 처리 방식은 한 번만 만들고 여러 카드가 함께 씁니다.
    - 사용 권한이 "허가됨"이 아닌 이미지는 카드에 쓰지 않습니다 (그 카드의 image는 "" → main-image 숨김).
      업로드했다는 사실만으로 허가로 보지 않으며, permission을 적지 않으면 "확인 필요"입니다.
    - PNG, JPG, WebP만 받습니다. HEIC 등은 지원하지 않는다고 안내합니다.
    - 이미 처리 결과(input/placed/의 파일 또는 cutout-check.md)가 있으면 덮어쓰지 않고 종료합니다.

[종료 코드]
    0: 모든 지정 카드 처리 성공 (경고는 있을 수 있음)
    1: card-images.json 규격 오류 — 아무것도 저장하지 않음
    2: 이미 처리 결과가 있음 — 덮어쓰지 않음
    3: 결과는 저장했지만 일부 카드가 차단(권한 미확인)되었거나 처리에 실패함

    프로젝트 루트(semogwi)에서 실행합니다. Pillow가 필요합니다 (py -m pip install pillow).
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fill_figma import FRAMES, MAIN_IMAGE_SIZE, UPSCALE_STRONG, UPSCALE_WARN, image_info  # noqa: E402

try:
    from PIL import Image, ImageOps
except ImportError:
    print('[오류] Pillow가 필요합니다: py -m pip install pillow')
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
CUTOUT_PY = ROOT / "scripts" / "cutout.py"
CUTOUT_MAX_SIZE = 1024
CUTOUT_MODELS = {"isnet-anime", "u2net", "u2netp", "bria-rmbg"}
DEFAULT_MODEL = "isnet-anime"
PERMISSIONS = ("허가됨", "허가 안 됨", "확인 필요")
SUPPORTED = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # Figma 업로드 한도
HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif"}


class SpecError(Exception):
    """card-images.json 규격 오류 (아무것도 저장하지 않음)."""


# ---------------------------------------------------------------------------
# 규격 검사
# ---------------------------------------------------------------------------
def load_spec(project: Path):
    path = project / "card-images.json"
    if not path.is_file():
        raise SpecError(f"{path}가 없습니다")
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SpecError(f"card-images.json JSON 형식 오류: {e}")
    if not isinstance(spec, dict) or not isinstance(spec.get("cards"), dict):
        raise SpecError('card-images.json에는 "cards" 객체가 있어야 합니다')
    unknown = set(spec["cards"]) - set(FRAMES)
    if unknown:
        raise SpecError(f"알 수 없는 카드 이름: {sorted(unknown)} (card-01 ~ card-05만)")

    cards, warnings = {}, []
    for fr in FRAMES:
        item = spec["cards"].get(fr)
        if item is None:
            cards[fr] = None
            continue
        if not isinstance(item, dict):
            raise SpecError(f"{fr}: 값은 객체 또는 null이어야 합니다")
        file = item.get("file")
        if not isinstance(file, str) or not file.strip():
            raise SpecError(f'{fr}: "file"이 없습니다')
        rel = Path(file.replace("\\", "/"))
        if rel.is_absolute() or ".." in rel.parts or rel.parts[:2] != ("input", "cards"):
            raise SpecError(f"{fr}: file은 프로젝트 폴더 기준 input/cards/ 아래 경로여야 합니다: {file}")
        if not (project / rel).is_file():
            raise SpecError(f"{fr}: 파일이 없습니다: {file}")
        cutout = item.get("cutout", False)
        if not isinstance(cutout, bool):
            raise SpecError(f'{fr}: "cutout"은 true 또는 false여야 합니다')
        model = item.get("cutout_model", DEFAULT_MODEL)
        if model not in CUTOUT_MODELS:
            raise SpecError(f"{fr}: cutout_model은 {sorted(CUTOUT_MODELS)} 중 하나여야 합니다")
        permission = item.get("permission") or "확인 필요"
        if permission not in PERMISSIONS:
            raise SpecError(f"{fr}: permission은 {PERMISSIONS} 중 하나여야 합니다 (현재: {permission!r})")
        if "permission" not in item:
            warnings.append(f"{fr}: permission이 없어 '확인 필요'로 봅니다 (업로드만으로 허가로 보지 않음)")
        cards[fr] = {
            "file": rel.as_posix(),
            "cutout": cutout,
            "model": model,
            "source": (item.get("source") or "확인 필요").strip(),
            "owner": (item.get("owner") or "확인 필요").strip(),
            "permission": permission,
            "note": (item.get("note") or "").strip(),
        }
    return spec.get("character", ""), cards, warnings


# ---------------------------------------------------------------------------
# 이미지 처리
# ---------------------------------------------------------------------------
def detect_format(path: Path):
    """(형식, 안내 메시지). 지원하지 않으면 형식은 None."""
    head = path.read_bytes()[:32]
    if head[4:8] == b"ftyp" and head[8:12] in HEIF_BRANDS:
        return None, "HEIC/HEIF/AVIF 형식은 지원하지 않습니다. PNG, JPG, WebP로 변환해서 다시 지정해 주세요"
    fmt, w, h = image_info(path)
    if fmt not in SUPPORTED:
        return None, f"지원하지 않는 형식입니다 ({fmt or '알 수 없음'}). PNG, JPG, WebP만 지원합니다"
    if not (w and h):
        return None, "이미지 크기를 읽지 못했습니다 (파일이 손상되었을 수 있음)"
    return fmt, ""


def exif_orientation(path: Path) -> int:
    try:
        with Image.open(path) as im:
            return int(im.getexif().get(0x0112, 1) or 1)
    except Exception:
        return 1


def alpha_stats(path: Path):
    with Image.open(path) as im:
        a = im.convert("RGBA").getchannel("A")
        h = a.histogram()
    n = sum(h)
    return {"transparent": round(h[0] / n, 3), "opaque": round(sum(h[240:]) / n, 3), "edge": round(sum(h[1:10]) / n, 3)}


def make_fit_copy(src: Path, dst_stem: Path, fmt: str):
    """FIT 배치용 사본. 회전 정보가 없으면 원본 바이트 그대로, 있으면 회전을 보정해 다시 저장."""
    orientation = exif_orientation(src)
    if orientation == 1:
        dst = dst_stem.with_suffix(SUPPORTED[fmt])
        with open(src, "rb") as f_in, open(dst, "xb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        return dst, "원본 그대로 복사"
    dst = dst_stem.with_suffix(SUPPORTED[fmt])
    with Image.open(src) as im:
        fixed = ImageOps.exif_transpose(im)
        if fmt == "jpeg":
            fixed = fixed.convert("RGB")
            save = {"format": "JPEG", "quality": 95}
        elif fmt == "webp":
            save = {"format": "WEBP", "quality": 95}
        else:
            save = {"format": "PNG"}
        with open(dst, "xb") as f_out:
            fixed.save(f_out, **save)
    return dst, f"EXIF 회전 보정 사본 (orientation {orientation}, 원본은 보존)"


def make_cutout(src: Path, dst_stem: Path, model: str):
    dst = dst_stem.with_name(dst_stem.name + "-cutout").with_suffix(".png")
    if dst.exists():
        raise RuntimeError(f"출력 경로가 이미 있습니다: {dst}")
    r = subprocess.run([sys.executable, str(CUTOUT_PY), str(src), str(dst), "--max-size", str(CUTOUT_MAX_SIZE),
                        "--model", model], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not dst.is_file():
        last = (r.stdout + r.stderr).strip().splitlines()[-3:]
        raise RuntimeError("누끼 실패: " + " / ".join(last))
    stats = alpha_stats(dst)
    if not (0.05 <= stats["transparent"] <= 0.95) or stats["opaque"] < 0.05:
        raise RuntimeError(f"누끼 결과 검사 실패 (투명 {stats['transparent']}, 불투명 {stats['opaque']}) — 결과 파일은 남겨 둠: {dst.name}")
    return dst, f"누끼 ({model}, --max-size {CUTOUT_MAX_SIZE}, EXIF 회전 반영)", stats


def rel_root(p: Path) -> str:
    return p.resolve().relative_to(ROOT).as_posix()


# ---------------------------------------------------------------------------
# 기록
# ---------------------------------------------------------------------------
SOURCES_HEADER = """# 이미지 출처 (프로젝트별)

이 프로젝트의 카드 이미지 출처와 사용 권한을 기록합니다. `scripts/assign_images.py`가 행을 추가합니다.
사용 권한이 `허가됨`인 이미지만 카드에 쓰고, 업로드했다는 사실만으로 허가로 보지 않습니다.
원본(`input/cards/`)과 배치용 파일(`input/placed/`)은 Git에 올리지 않습니다.

## 이미지 목록

| 캐릭터명 | 원본 파일 경로 | 배치용 파일 경로 | 출처 | 저작권자 | 사용 허가 여부 | 비고 |
|---|---|---|---|---|---|---|
"""


def append_sources(project: Path, rows):
    rows = list(rows)
    if not rows:  # 지정된 이미지가 없으면 출처 파일을 만들지 않는다
        return
    path = project / "sources.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else SOURCES_HEADER
    if not text.endswith("\n"):
        text += "\n"
    for r in rows:
        cells = [r["character"] or "-", f"`{r['original']}`", f"`{r['placed']}`" if r["placed"] else "-",
                 r["source"], r["owner"], r["permission"], r["note"]]
        text += "| " + " | ".join(c.replace("|", "/") for c in cells) + " |\n"
    path.write_text(text, encoding="utf-8")


def write_check(project: Path, results, character):
    lines = [
        f"# 누끼 검사 — {project.name}",
        "",
        f"- 작업일: {date.today().isoformat()}",
        f"- 캐릭터: {character or '-'}",
        "- 근거: card-images.json (사용자가 카드별로 지정한 이미지), `scripts/assign_images.py`로 처리",
        "",
        "| 카드 | 원본 | 처리 | 결과 파일 (slides.json `image`) | 크기 | 투명 비율 | 불투명 비율 | 가장자리(알파 1~9, 참고) | FIT 배율 | 사용 허가 | 결과 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for fr in FRAMES:
        r = results[fr]
        image = f"`{r['image']}`" if r["image"] else '`""`'
        st = r.get("alpha") or {}
        lines.append("| " + " | ".join([
            fr, r.get("original_label", "-"), r["process"], image, r.get("size", "-"),
            str(st.get("transparent", "-")), str(st.get("opaque", "-")), str(st.get("edge", "-")),
            f"×{r['fit']:.2f}" if r.get("fit") else "-", r.get("permission", "-"), r["status"],
        ]) + " |")
    warns = [f"- {fr}: {w}" for fr in FRAMES for w in results[fr]["warnings"]]
    if warns:
        lines += ["", "## 경고", *warns]
    (project / "cutout-check.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="card-images.json의 카드별 이미지를 처리합니다")
    ap.add_argument("project")
    args = ap.parse_args()
    project = Path(args.project).resolve()
    if not project.is_relative_to(ROOT):
        print(f"[오류] 프로젝트 폴더가 semogwi 안에 있어야 합니다: {project}")
        return 1

    placed_dir = project / "input" / "placed"
    if (project / "cutout-check.md").exists() or (placed_dir.is_dir() and any(placed_dir.iterdir())):
        print(f"[중단] 이미 처리 결과가 있습니다 (cutout-check.md 또는 input/placed/). 덮어쓰지 않습니다.")
        return 2
    try:
        character, cards, spec_warnings = load_spec(project)
    except SpecError as e:
        print(f"[오류] {e}")
        print("아무것도 저장하지 않았습니다.")
        return 1

    placed_dir.mkdir(parents=True, exist_ok=True)
    cache = {}       # (원본 md5, 누끼 여부, 모델) → 처리 결과
    results = {}
    source_rows = {}  # (원본, 배치용) → 행
    problem = False
    for fr in FRAMES:
        c = cards[fr]
        if c is None:
            results[fr] = {"image": "", "process": "건너뜀 (이미지 없음)", "status": "-", "warnings": []}
            continue
        src = project / c["file"]
        res = {"original_label": c["file"], "permission": c["permission"], "warnings": []}
        orig_rel = rel_root(src)
        fmt, msg = detect_format(src)
        if fmt is None:
            res.update(image="", process="실패", status=f"실패 — {msg}")
            problem = True
        elif c["permission"] != "허가됨":
            res.update(image="", process="차단", status=f"차단 — 사용 권한 '{c['permission']}' (카드에 쓰지 않음)")
            problem = True
            source_rows.setdefault((orig_rel, ""), {"character": character, "original": orig_rel, "placed": "",
                                                    "source": c["source"], "owner": c["owner"],
                                                    "permission": c["permission"], "cards": [], "how": "사용 안 함 (권한 미확인)",
                                                    "note": c["note"]})["cards"].append(fr)
        else:
            md5 = hashlib.md5(src.read_bytes()).hexdigest()
            key = (md5, c["cutout"], c["model"] if c["cutout"] else "")
            try:
                if key not in cache:
                    stem = placed_dir / f"img-{len(cache) + 1:02d}"
                    if c["cutout"]:
                        dst, how, stats = make_cutout(src, stem, c["model"])
                    else:
                        dst, how = make_fit_copy(src, stem, fmt)
                        stats = None
                    dfmt, w, h = image_info(dst)
                    cache[key] = {"dst": dst, "how": how, "alpha": stats, "fmt": dfmt, "w": w, "h": h}
                    reused = False
                else:
                    reused = True
                info = cache[key]
                dst = info["dst"]
                if dst.stat().st_size > MAX_UPLOAD_BYTES:
                    raise RuntimeError("배치용 이미지가 10MB를 넘어 Figma에 업로드할 수 없습니다. 더 작은 이미지를 지정해 주세요")
                fit = min(MAIN_IMAGE_SIZE[0] / info["w"], MAIN_IMAGE_SIZE[1] / info["h"])
                if fit > UPSCALE_WARN:
                    level = "많이 흐려질 수 있음 (진행 전 확인 필요)" if fit > UPSCALE_STRONG else "조금 흐려질 수 있음"
                    res["warnings"].append(f"이미지 {info['w']}x{info['h']}가 작아 FIT으로 {fit:.2f}배 확대됨 — {level}. "
                                           f"확대 없이 넣으려면 {round(info['w'] * fit)}x{round(info['h'] * fit)} 이상 필요")
                res.update(image=rel_root(dst), process=("재사용 — " if reused else "") + ("누끼" if c["cutout"] else "FIT"),
                           status="통과", size=f"{info['w']}×{info['h']}", fit=fit, alpha=info["alpha"],
                           detail=info["how"])
                row = source_rows.setdefault((orig_rel, rel_root(dst)), {
                    "character": character, "original": orig_rel, "placed": rel_root(dst), "source": c["source"],
                    "owner": c["owner"], "permission": c["permission"], "cards": [], "how": info["how"], "note": c["note"]})
                row["cards"].append(fr)
            except (RuntimeError, OSError) as e:
                res.update(image="", process="실패", status=f"실패 — {e}")
                problem = True
        results[fr] = res

    today = date.today().isoformat()
    for r in source_rows.values():
        r["note"] = "; ".join(x for x in [f"{today} 추가", ", ".join(r["cards"]), r["how"], r["note"]] if x)
    append_sources(project, source_rows.values())
    write_check(project, results, character)
    (project / "card-images-result.json").write_text(json.dumps({
        "cards": {fr: {k: v for k, v in results[fr].items() if k in ("image", "process", "status", "fit", "warnings")}
                  for fr in FRAMES},
        "spec_warnings": spec_warnings,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for w in spec_warnings:
        print(f"[경고] {w}")
    for fr in FRAMES:
        r = results[fr]
        print(f"{fr}: {r['process']:<14} {r['status']}  {r['image'] or '(image \"\")'}")
        for w in r["warnings"]:
            print(f"    [경고] {w}")
    written = [project / "cutout-check.md", project / "card-images-result.json"] + ([project / "sources.md"] if source_rows else [])
    print("기록: " + ", ".join(str(p) for p in written))
    return 3 if problem else 0


if __name__ == "__main__":
    sys.exit(main())

"""단색 배경 일러스트의 배경 제거 (외곽선 기준). 시스템 Python으로 실행합니다 (numpy·scipy·Pillow, 웹 가상환경에 설치하지 않음).

사용법: python flat_cutout.py <입력> <출력 PNG> [--max-size 1024] [--classify-only]
출력(표준 출력 JSON): {"applicable": bool, "reason": str, "kind": "flat"|"photo", ...측정값}
- applicable이 false면 출력 파일을 만들지 않습니다 (사진이거나 배경이 단색이 아님 → AI 모델로 처리).

흰 몸통 캐릭터가 흰 배경에 있고 검은 외곽선이 군데군데 끊긴 그림을 위한 방법입니다.
- 흰색 픽셀을 지우지 않습니다. 이미지 가장자리와 **이어진** 배경색 영역만 투명하게 합니다.
  외곽선 안쪽의 흰 몸통은 가장자리와 이어져 있지 않으므로 남습니다.
- 외곽선이 끊긴 곳으로 배경 채우기가 몸통 안까지 번지지 않게, 먼저 어두운 선을 닫힘 연산(closing)으로 이어
  틈을 막습니다. 닫힘은 선을 두껍게 만들지 않고 짧은 틈만 메웁니다.
- 외곽선·눈·볼처럼 배경색이 아니거나 가장자리와 이어지지 않은 부분은 그대로 둡니다.
  배경과 닿은 가장자리 한 줄만 배경색과의 차이에 따라 부드럽게(반투명) 처리합니다.
"""

import argparse
import json
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.spatial import ConvexHull, QhullError

BORDER = 0.02          # 가장자리 띠 두께 (긴 변 대비)
BG_TOLERANCE = 28      # 배경색과의 RGB 거리. 이보다 가까우면 배경색으로 봅니다 (JPEG 잡음 포함)
UNIFORM_BORDER = 0.85  # 가장자리 띠의 이 비율 이상이 배경색이어야 단색 배경으로 봅니다
FLAT_RATIO = 0.55      # 이미지의 이 비율 이상이 평평한(색 변화가 적은) 영역이어야 일러스트로 봅니다
LINE_SHARE = 0.08      # 피사체 중 어두운 외곽선 비율이 이 이상이어야 '선으로 그린 일러스트'로 봅니다 (사진 구분)
DARK = 110             # 외곽선으로 볼 밝기 (0~255). 배경보다 충분히 어두운 선
GAP = 0.006            # 외곽선 틈을 메우는 닫힘 반경 (긴 변 대비, 1024px에서 약 6px → 12px 틈까지)
EDGE_SOFT = 60         # 가장자리 반투명 처리: 배경색과의 거리가 이만큼이면 완전 불투명


def _disk(radius: int) -> np.ndarray:
    y, x = np.ogrid[-radius:radius + 1, -radius:radius + 1]
    return x * x + y * y <= radius * radius


def analyze(rgb: np.ndarray) -> dict:
    """사진인지 단색 배경 일러스트인지 판별합니다."""
    h, w, _ = rgb.shape
    band = max(2, round(max(h, w) * BORDER))
    border = np.concatenate([rgb[:band].reshape(-1, 3), rgb[-band:].reshape(-1, 3),
                             rgb[:, :band].reshape(-1, 3), rgb[:, -band:].reshape(-1, 3)]).astype(np.float32)
    bg = np.median(border, axis=0)
    near = np.linalg.norm(border - bg, axis=1) <= BG_TOLERANCE
    uniform = float(near.mean())
    gray = rgb.astype(np.float32).mean(axis=2)
    local = ndimage.uniform_filter(gray, 3)
    local_sq = ndimage.uniform_filter(gray * gray, 3)
    std = np.sqrt(np.maximum(local_sq - local * local, 0))
    flat = float((std < 4).mean())
    noise = float(np.linalg.norm(border[near] - bg, axis=1).mean()) if near.any() else 99.0
    # 외곽선 비율: 배경이 아닌 부분 중 어두운 선의 비율. 선으로 그린 일러스트는 높고(실측 0.17~0.73),
    # 흰 배경 위 상품 사진은 낮습니다(실측 0.03~0.04). 사진은 AI 모델로 보냅니다
    dist = np.linalg.norm(rgb.astype(np.float32) - bg, axis=2)
    subject = dist > BG_TOLERANCE
    lum = rgb.astype(np.float32) @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    bg_lum = float(np.dot(bg, [0.299, 0.587, 0.114]))
    dark = subject & (lum < min(DARK, bg_lum - 60))
    line_share = float(dark.sum() / max(1, subject.sum()))
    kind = "flat" if uniform >= UNIFORM_BORDER and flat >= FLAT_RATIO and line_share >= LINE_SHARE else "photo"
    return {"kind": kind, "background": [round(float(v)) for v in bg], "uniformBorder": round(uniform, 3),
            "flatRatio": round(flat, 3), "lineShare": round(line_share, 3), "borderNoise": round(noise, 2)}


LEAK_JUMP = 0.03       # 닫힘 반경을 키웠을 때 피사체 비율이 이만큼 넘게 늘면 '틈으로 배경이 새던 것'으로 봅니다
RADIUS_STEPS = (1, 1.8, 2.8, 4.0)  # 기본 반경의 배수. 큰 틈은 반경을 키워 막습니다 (1024px에서 약 6·11·17·25px)


def _outside(dist: np.ndarray, dark: np.ndarray, radius: int) -> tuple[np.ndarray, np.ndarray]:
    """끊긴 선을 radius로 이은 뒤, 가장자리와 이어진 배경색 영역 (outside, closed)."""
    padded = np.pad(dark, radius)  # 가장자리 근처 선도 닫힘 연산에서 잘리지 않게
    closed = ndimage.binary_closing(padded, structure=_disk(radius))[radius:-radius, radius:-radius]
    passable = (dist <= BG_TOLERANCE) & ~closed                          # 배경색이고 선(이은 부분 포함)이 아닌 곳
    labels, _ = ndimage.label(passable)
    edge = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
    return np.isin(labels, np.unique(edge[edge > 0])), closed


def outline_hull(rgb: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """외곽선이 둘러싼 영역(틈을 이은 뒤). AI 모델 결과가 흰 몸통을 지웠는지 검사하는 데 씁니다."""
    dist, dark = _measure(rgb, bg)
    radius = _pick_radius(dist, dark, max(rgb.shape[:2]))[0]
    outside, _ = _outside(dist, dark, radius)
    return ~outside


def _measure(rgb: np.ndarray, bg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pixels = rgb.astype(np.float32)
    dist = np.linalg.norm(pixels - bg, axis=2)
    lum = pixels @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    bg_lum = float(np.dot(bg, [0.299, 0.587, 0.114]))
    dark = (lum < min(DARK, bg_lum - 60)) & (dist > BG_TOLERANCE)       # 외곽선·눈 등 어두운 선
    return dist, dark


def _pick_radius(dist: np.ndarray, dark: np.ndarray, size: int) -> tuple[int, list]:
    """틈을 막는 데 필요한 가장 작은 반경. 반경을 키울 때 피사체가 크게 늘면 그전에는 틈으로 배경 채우기가 새던 것입니다."""
    base = max(2, round(size * GAP))
    radii = sorted({max(2, round(base * k)) for k in RADIUS_STEPS})
    ratios = [float((~_outside(dist, dark, r)[0]).mean()) for r in radii]
    chosen = 0
    for i in range(1, len(radii)):
        if ratios[i] - ratios[i - 1] > LEAK_JUMP:
            chosen = i  # 이 반경에서야 새던 틈이 막힘
    return radii[chosen], [{"radius": r, "subject": round(s, 3)} for r, s in zip(radii, ratios)]


def cut(rgb: np.ndarray, bg: np.ndarray) -> tuple[np.ndarray, dict]:
    """가장자리와 이어진 배경색 영역만 투명하게 한 알파와 측정값."""
    h, w, _ = rgb.shape
    dist, dark = _measure(rgb, bg)
    radius, trials = _pick_radius(dist, dark, max(h, w))
    outside, closed = _outside(dist, dark, radius)
    subject = ~outside
    alpha = np.where(subject, 255, 0).astype(np.float32)
    # 배경과 닿은 가장자리 한 줄: 배경색과 비슷할수록 투명하게 (안티에일리어싱). 틈을 이은 자리는 불투명 유지
    ring = subject & ndimage.binary_dilation(outside, structure=np.ones((3, 3), bool)) & ~(closed & ~dark)
    alpha[ring] = np.clip(dist[ring] / EDGE_SOFT, 0, 1) * 255
    stats = {"radius": radius, "darkRatio": round(float(dark.mean()), 4), "bridged": int((closed & ~dark).sum()),
             "subjectRatio": round(float(subject.mean()), 3), "radiusTrials": trials,
             # 가장 큰 반경에서도 피사체가 계속 크게 늘었다면 더 큰 틈이 남아 있을 수 있습니다 → 믿지 않고 AI 모델로
             "unsealed": len(trials) > 1 and trials[-1]["subject"] - trials[-2]["subject"] > LEAK_JUMP}
    filled = hull_filled(subject, dark)
    stats["hullFilled"] = None if filled is None else round(filled, 3)
    if filled is not None and filled < HULL_FILLED:
        stats["unsealed"] = True  # 어느 반경으로도 틈이 막히지 않아 속이 지워짐
    return alpha.astype(np.uint8), stats


HULL_FILLED = 0.35  # 외곽선 볼록 껍질 중 피사체로 남은 비율이 이보다 적으면 몸통이 틈으로 지워진 것으로 봅니다


def hull_filled(subject: np.ndarray, dark: np.ndarray) -> float | None:
    """어두운 선 전체를 감싸는 볼록 껍질 중 피사체(불투명)로 남은 비율.

    틈이 어느 반경으로도 막히지 않으면 반경을 키워도 피사체 비율이 늘지 않아 '새는 것'을 알아챌 수 없습니다.
    그때는 선만 남고 속이 비므로 이 비율이 크게 낮아집니다 (막힌 몸통은 대개 0.6 이상).
    """
    ys, xs = np.nonzero(dark)
    if len(xs) < 3:
        return None
    points = np.column_stack([xs, ys])
    try:
        hull = ConvexHull(points)
    except QhullError:
        return None
    mask = Image.new("L", (subject.shape[1], subject.shape[0]), 0)
    ImageDraw.Draw(mask).polygon([tuple(map(int, points[i])) for i in hull.vertices], fill=1)
    area = np.asarray(mask, dtype=bool)
    return float(subject[area].mean()) if area.any() else None


BODY_KEPT = 0.9  # AI 모델 결과 검사: 외곽선이 둘러싼 영역 중 이 비율 이상이 남아 있어야 합니다


def check_model_result(rgb: np.ndarray, info: dict, result_path: str) -> dict:
    """AI 모델 결과가 외곽선 안쪽(흰 몸통 등)을 지웠는지 검사합니다.

    외곽선이 끊겨 있으면 지워진 몸통이 바깥 배경과 이어져 '안쪽 구멍' 검사에 걸리지 않으므로,
    끊긴 선을 이어 만든 외곽선 안쪽 영역과 비교합니다.
    """
    hull = outline_hull(rgb, np.array(info["background"], dtype=np.float32))
    inner = ndimage.binary_erosion(hull, iterations=max(2, round(max(rgb.shape[:2]) * 0.008)))
    if inner.mean() < 0.02:
        return {"checked": False, "bodyKept": None}  # 외곽선으로 둘러싼 영역이 거의 없음 → 판단하지 않음
    with Image.open(result_path) as result:
        alpha = np.asarray(result.convert("RGBA").getchannel("A").resize((rgb.shape[1], rgb.shape[0]), Image.NEAREST))
    kept = float((alpha[inner] >= 128).mean())
    return {"checked": True, "bodyKept": round(kept, 3), "ok": kept >= BODY_KEPT}


def _load(path: str, max_size: int) -> np.ndarray:
    with Image.open(path) as image:
        image = image.convert("RGB")
        if max(image.size) > max_size:
            scale = max_size / max(image.size)
            image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS)
        return np.asarray(image)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output", nargs="?")
    parser.add_argument("--max-size", type=int, default=1024)
    parser.add_argument("--classify-only", action="store_true")
    parser.add_argument("--check", help="AI 모델 결과 PNG: 외곽선 안쪽이 남았는지 검사만 합니다")
    args = parser.parse_args()
    rgb = _load(args.input, args.max_size)
    info = analyze(rgb)
    if info["kind"] != "flat":
        print(json.dumps({"applicable": False, "reason": "사진이거나 배경이 단색이 아니에요", **info}, ensure_ascii=False))
        return
    if args.check:
        print(json.dumps({"applicable": True, "reason": "", **info, **check_model_result(rgb, info, args.check)}, ensure_ascii=False))
        return
    if args.classify_only or not args.output:
        print(json.dumps({"applicable": True, "reason": "", **info}, ensure_ascii=False))
        return
    alpha, stats = cut(rgb, np.array(info["background"], dtype=np.float32))
    if stats["unsealed"]:
        # 가장 큰 반경으로도 틈이 막히지 않았을 수 있음 → 결과를 만들지 않고 AI 모델로 넘깁니다
        print(json.dumps({"applicable": False, "reason": "외곽선 틈이 너무 커서 이 방법으로는 몸통을 지킬 수 없어요", **info, **stats},
                         ensure_ascii=False))
        return
    Image.fromarray(np.dstack([rgb, alpha]), "RGBA").save(args.output, format="PNG")
    print(json.dumps({"applicable": True, "reason": "", **info, **stats}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # -I로 실행하면 PYTHONIOENCODING이 무시되므로 직접 UTF-8로
    try:
        main()
    except Exception as e:  # 실패 내용을 JSON으로 알려 호출한 쪽이 AI 모델로 넘어가게 합니다
        print(json.dumps({"applicable": False, "reason": f"외곽선 기준 처리 실패: {type(e).__name__}"}, ensure_ascii=False))
        sys.exit(2)

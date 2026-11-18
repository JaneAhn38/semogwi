"""단색 배경 일러스트의 외곽선 기준 배경 제거 (app/flat_cutout.py). 작은 그림을 만들어 실제로 실행합니다.

그림 만들기와 픽셀 읽기는 시스템 Python(tests/flat_images.py)으로 합니다. 웹 가상환경에는 Pillow·numpy를 설치하지 않기 때문입니다.
"""

import json
import subprocess
from pathlib import Path

import pytest

from app import cutout

pytestmark = pytest.mark.skipif(not cutout.flat_available(), reason="시스템 Python에 numpy·scipy·Pillow가 없어요")
HELPER = Path(__file__).resolve().parent / "flat_images.py"


def helper(command, **args):
    done = subprocess.run([cutout.PYTHON, "-I", str(HELPER), command, json.dumps({k: str(v) if isinstance(v, Path) else v for k, v in args.items()})],
                          capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout) if done.stdout.strip() else None


def run_flat(*args):
    done = subprocess.run([cutout.PYTHON, "-I", str(cutout.FLAT_CUTOUT), *map(str, args)], capture_output=True, text=True, encoding="utf-8")
    return json.loads(done.stdout)


def pixels(path, *points):
    return [tuple(p) for p in helper("pixels", path=path, points=[list(p) for p in points])]


def test_white_body_on_white_background_with_broken_outline(tmp_path):
    src, out = tmp_path / "white.png", tmp_path / "out.png"
    helper("character", path=src)
    info = run_flat(src, out)
    assert info["applicable"] and info["kind"] == "flat" and info["lineShare"] >= 0.08
    body, background, corner, eye, cheek = pixels(out, (150, 200), (20, 150), (2, 2), (120, 139), (112, 166))
    assert body == (255, 255, 255, 255)          # 흰 몸통은 그대로 (흰색을 지우지 않음)
    assert background[3] == 0 and corner[3] == 0  # 바깥 배경만 투명
    assert eye[3] == 255 and max(eye[:3]) < 80   # 눈(검은색) 유지
    assert cheek[3] == 255 and cheek[0] > 230 and cheek[1] < 200  # 분홍 볼 유지
    # 외곽선 틈 바로 안쪽도 불투명 → 끊긴 선으로 배경 채우기가 몸통 안까지 새지 않음
    inside_gap = pixels(out, (150, 72), (150, 228))
    assert all(p[3] == 255 for p in inside_gap)


def test_large_gaps_are_bridged_by_growing_radius(tmp_path):
    src, out = tmp_path / "gap.png", tmp_path / "out.png"
    helper("character", path=src, gaps=[[150, 62, 7]])
    info = run_flat(src, out)
    assert info["applicable"] and info["radius"] > info["radiusTrials"][0]["radius"]  # 첫 반경으로는 새서 반경을 키움
    assert pixels(out, (150, 150))[0][3] == 255


def test_gap_too_wide_is_not_trusted(tmp_path):
    src, out = tmp_path / "wide.png", tmp_path / "out.png"
    helper("character", path=src, gaps=[[150, 62, 80]])
    info = run_flat(src, out)
    assert not info["applicable"] and not out.exists()  # 몸통을 지킬 수 없으면 결과를 만들지 않고 AI 모델로 넘김


def test_photo_like_images_are_not_handled(tmp_path):
    helper("photo", path=tmp_path / "photo.png")
    info = run_flat(tmp_path / "photo.png", tmp_path / "out.png")
    assert not info["applicable"] and info["kind"] == "photo"
    # 흰 배경 위 선 없는 물체(상품 사진처럼): 외곽선이 없으면 선 일러스트로 보지 않음
    helper("product", path=tmp_path / "product.png")
    assert run_flat(tmp_path / "product.png", tmp_path / "out2.png")["kind"] == "photo"


def test_auto_uses_outline_method_for_flat_illustration_without_models(tmp_path, monkeypatch):
    src, out = tmp_path / "white.png", tmp_path / "out.png"
    helper("character", path=src)
    called = []
    monkeypatch.setattr(cutout, "_cutout_once", lambda *a: called.append(a))
    stats = cutout.run_cutout(src, out, "auto")
    assert stats["model"] == cutout.FLAT and stats["kind"] == "flat" and called == []
    assert stats["holes"] == 0 and stats["method"]["radius"] >= 2


def test_model_result_that_erased_white_body_is_rejected(tmp_path, monkeypatch):
    """끊긴 외곽선 때문에 지워진 몸통이 바깥과 이어져도, 외곽선 안쪽과 비교해 실패로 처리합니다."""
    src, out = tmp_path / "white.png", tmp_path / "out.png"
    helper("character", path=src)

    def erased(source, target, model):
        helper("erase", src=source, dst=target)  # AI 모델이 흰 몸통을 지우고 선만 남긴 결과 (실측: isnet-general-use)
        return {"transparent": 0.9, "opaque": 0.1, "holes": 0.0, "translucent": 0.0, "bbox": [60, 60, 240, 240]}

    monkeypatch.setattr(cutout, "_cutout_once", erased)
    with pytest.raises(cutout.CutoutError, match="흰 몸통"):
        cutout.run_cutout(src, out, "isnet-general-use")
    assert not out.exists()  # 실패한 결과는 남기지 않음 → 원본이 그대로 쓰임


def test_auto_falls_back_to_models_for_photos(tmp_path, monkeypatch):
    helper("noise", path=tmp_path / "noise.png")
    monkeypatch.setattr(cutout, "model_installed", lambda m: True)
    monkeypatch.setattr(cutout, "_cutout_once", lambda s, t, m: {"transparent": 0.5, "opaque": 0.5, "holes": 0, "translucent": 0})
    stats = cutout.run_cutout(tmp_path / "noise.png", tmp_path / "out.png", "auto")
    assert stats["model"] == "isnet-general-use" and stats["kind"] == "photo"


def test_status_lists_outline_method():
    assert cutout.FLAT in [m["id"] for m in cutout.status()["models"]]

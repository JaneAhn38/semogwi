"""배경 제거 연결. 기존 scripts/cutout.py를 별도 프로세스로 실행합니다 (그 파일은 수정하지 않음).

- rembg와 Pillow는 시스템 Python에 이미 있으므로 웹 가상환경에 설치하지 않습니다.
- cutout.py는 모델이 없으면 자동으로 내려받습니다. 웹에서는 모델 파일이 있을 때만 실행해 다운로드를 막습니다.
- 메모리를 많이 쓰므로 한 번에 한 장만 처리합니다.
- 결과는 alpha_refine.py로 알파만 보정하고 alpha_check.py로 검사합니다.
- "자동"은 먼저 사진인지 단색 배경 일러스트인지 판별합니다 (flat_cutout.py).
  - 단색 배경 일러스트: 외곽선 기준 방법을 먼저 씁니다. 가장자리와 이어진 배경색만 지우고, 끊긴 외곽선은 이어서
    흰 몸통이 지워지지 않게 합니다 (흰색 픽셀을 지우는 방식이 아님). 쓸 수 없거나 검사를 통과하지 못하면 AI 모델로 넘어갑니다.
  - AI 모델: 실물 사진용 → 그림용 → 가벼운 사진용 → 고품질 순서로 시도해 검사를 통과한 첫 결과를 씁니다.
    사진용 모델은 흰 몸통 일러스트의 속을 지우고, 그림용 모델은 실물 사진의 마스크를 반투명하게 만들어서
    한 모델로는 두 경우를 모두 처리하지 못합니다.
  - 일러스트에 AI 모델을 쓸 때는 외곽선이 둘러싼 영역이 남았는지 추가로 검사합니다. 외곽선이 끊겨 있으면 지워진 몸통이
    바깥과 이어져 '안쪽 구멍' 검사에 걸리지 않기 때문입니다.
- 모두 실패하면 원본을 그대로 둡니다 (화면에서 원본으로 쓰거나 다른 방법을 고를 수 있음).
"""

import json
import os
import subprocess
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CUTOUT_SCRIPT = REPO_ROOT / "scripts" / "cutout.py"
ALPHA_CHECK = Path(__file__).resolve().parent / "alpha_check.py"
ALPHA_REFINE = Path(__file__).resolve().parent / "alpha_refine.py"
FLAT_CUTOUT = Path(__file__).resolve().parent / "flat_cutout.py"
PYTHON = os.environ.get("SEMOGWI_CUTOUT_PYTHON", "py")

MAX_SIZE = 1024  # scripts/assign_images.py와 같은 값
TIMEOUT_SECONDS = 300
AUTO = "auto"
# 화면에 보일 순서. 설치된 모델만 선택지로 나갑니다
FLAT = "flat-outline"  # 모델 파일이 필요 없는 방법 (numpy·scipy·Pillow)
MODELS = {
    AUTO: "자동 (사진·그림 판별)",
    FLAT: "단색 배경 일러스트 (외곽선 기준)",
    "isnet-general-use": "실물 사진·굿즈",
    "isnet-anime": "캐릭터 그림",
    "u2net": "사진 (가벼운 모델)",
    "bria-rmbg": "고품질 (느림, 1~2분)",
}
AUTO_ORDER = ["isnet-general-use", "isnet-anime", "u2net", "bria-rmbg"]  # bria는 마지막 수단 (느리고 메모리를 많이 씀)
DEFAULT_MODEL = AUTO
MAX_HOLES = 0.12  # 피사체 안쪽 구멍 비율이 이보다 크면 흰 부분이 지워진 것으로 봅니다
MAX_TRANSLUCENT = 0.3  # 피사체의 반투명 비율이 이보다 크면 몸통이 비쳐 보이는 결과로 봅니다 (실측: 정상 0.02~0.07, 불량 0.6 이상)

_lock = threading.Lock()
_runtime_cache: bool | None = None


class CutoutError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 실패 이유."""


def _model_files(model: str) -> list[Path]:
    homes = [Path(os.environ[name]) for name in ("REMBG_HOME", "U2NET_HOME") if os.environ.get(name)]
    homes += [Path.home() / ".rembg", Path.home() / ".u2net"]
    files = []
    for home in homes:
        files += [home / "models" / model / f"{model}.onnx", home / f"{model}.onnx"]
    return files


def model_installed(model: str) -> bool:
    if model == AUTO:
        return flat_available() or any(model_installed(m) for m in AUTO_ORDER)
    if model == FLAT:
        return flat_available()
    return any(path.is_file() for path in _model_files(model))


_flat_cache: bool | None = None


def flat_available() -> bool:
    """외곽선 기준 방법을 쓸 수 있는지 (시스템 Python에 numpy·scipy·Pillow)."""
    global _flat_cache
    if _flat_cache is None:
        try:
            probe = "import importlib.util as u;import sys;sys.exit(0 if all(u.find_spec(m) for m in ('numpy','scipy','PIL')) else 1)"
            _flat_cache = FLAT_CUTOUT.is_file() and _run(["-I", "-c", probe], 30).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _flat_cache = False
    return _flat_cache


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [PYTHON, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, cwd=CUTOUT_SCRIPT.parent, env=env, stdin=subprocess.DEVNULL,
    )


def _runtime_available() -> bool:
    global _runtime_cache
    if _runtime_cache is None:
        try:
            probe = "import importlib.util as u;import sys;sys.exit(0 if u.find_spec('rembg') and u.find_spec('PIL') else 1)"
            _runtime_cache = _run(["-I", "-c", probe], 30).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _runtime_cache = False
    return _runtime_cache


def status() -> dict:
    """화면에 보여 줄 사용 가능 여부. 설치된 모델만 선택지로 내보냅니다."""
    models = [{"id": k, "label": v} for k, v in MODELS.items() if model_installed(k)]
    if not CUTOUT_SCRIPT.is_file() and not flat_available():
        return {"available": False, "models": [], "reason": "scripts/cutout.py를 찾지 못했어요."}
    if not _runtime_available():
        return {"available": False, "models": [], "reason": "시스템 Python에 rembg 또는 Pillow가 없어요."}
    if not models:
        return {"available": False, "models": [], "reason": "설치된 누끼 모델이 없어요. 모델을 자동으로 내려받지는 않아요."}
    return {"available": True, "models": models, "reason": ""}


def _failure_reason(result: subprocess.CompletedProcess) -> str:
    # cutout.py가 출력한 [오류] 줄만 보여 줍니다 (진단 전문에는 PC 경로가 포함될 수 있음)
    for line in result.stdout.splitlines():
        if line.startswith("[오류]"):
            return line.removeprefix("[오류]").strip()
    return "배경 제거 프로그램이 비정상적으로 끝났어요."


def run_cutout(input_path: Path, output_path: Path, model: str) -> dict:
    """배경을 제거해 output_path에 투명 PNG를 저장하고 검사 결과를 돌려줍니다. 원본은 읽기만 합니다.

    결과 stats에는 실제로 쓴 모델(model)과 자동 모드에서 시도한 모델별 실패 이유(tried)가 들어갑니다.
    """
    if model not in MODELS:
        raise CutoutError("알 수 없는 모델이에요.")
    if not model_installed(model):
        raise CutoutError(f"{model} 모델이 설치되어 있지 않아요. 자동으로 내려받지 않아요.")
    if model == FLAT:
        stats = _flat_cutout(input_path, output_path)
        if not stats.get("applicable"):
            raise CutoutError(f"{stats.get('reason') or '이 이미지에는 쓸 수 없어요'}. 다른 방법을 고르거나 원본을 사용해 주세요.")
        return {**stats["result"], "model": FLAT, "tried": [], "kind": "flat"}
    if model != AUTO:
        stats = _cutout_once(input_path, output_path, model)
        _check_outline_body(input_path, output_path, None)
        return {**stats, "model": model, "tried": []}
    tried = []
    kind = None
    if flat_available():
        # 1) 단색 배경 일러스트면 외곽선 기준 방법을 먼저 씁니다 (빠르고 흰 몸통을 지우지 않음)
        try:
            flat = _flat_cutout(input_path, output_path)
            kind = flat.get("kind")
            if flat.get("applicable"):
                return {**flat["result"], "model": FLAT, "tried": tried, "kind": "flat"}
            if kind == "flat":
                tried.append({"model": FLAT, "reason": flat.get("reason", "")})
        except CutoutError as e:
            tried.append({"model": FLAT, "reason": str(e)})
    # 2) AI 모델 (사진이거나 외곽선 기준 방법을 쓸 수 없을 때)
    for candidate in [m for m in AUTO_ORDER if model_installed(m)]:
        try:
            stats = _cutout_once(input_path, output_path, candidate)
            if kind == "flat":
                _check_outline_body(input_path, output_path, kind)
        except CutoutError as e:
            tried.append({"model": candidate, "reason": str(e)})
            continue
        return {**stats, "model": candidate, "tried": tried, "kind": kind or "photo"}
    raise CutoutError("자동으로 배경과 피사체를 구분하지 못했어요. 원본을 쓰거나 '고품질' 모델로 다시 해 보세요.")


def _flat_run(args: list[str]) -> dict:
    try:
        result = _run(["-I", str(FLAT_CUTOUT), *args], 120)
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        raise CutoutError("외곽선 기준 처리를 실행하지 못했어요.") from None


def _flat_cutout(input_path: Path, output_path: Path) -> dict:
    """외곽선 기준 방법. 쓸 수 있으면 결과를 검사해 {applicable: True, kind, result: 검사값}을 돌려줍니다."""
    with _lock:
        info = _flat_run([str(input_path), str(output_path), "--max-size", str(MAX_SIZE)])
    if not info.get("applicable"):
        output_path.unlink(missing_ok=True)
        return info
    if not output_path.is_file():
        return {**info, "applicable": False, "reason": "결과 파일을 만들지 못했어요"}
    try:
        checked = _check_result(output_path)  # 같은 기준으로 검사 (투명 비율·안쪽 구멍·반투명)
    except CutoutError as e:
        return {**info, "applicable": False, "reason": str(e).split(".")[0]}
    method = {k: info[k] for k in ("radius", "bridged", "background", "uniformBorder", "flatRatio") if k in info}
    return {**info, "result": {**checked, "method": method}}


def _check_outline_body(input_path: Path, output_path: Path, kind: str | None) -> None:
    """AI 모델 결과가 일러스트의 외곽선 안쪽(흰 몸통 등)을 지웠으면 실패로 처리합니다. 사진에는 하지 않습니다."""
    if kind == "photo" or not flat_available():
        return
    try:
        info = _flat_run([str(input_path), "--max-size", str(MAX_SIZE), "--check", str(output_path)])
    except CutoutError:
        return  # 검사를 못 하면 기존 검사 결과만 따릅니다
    if info.get("checked") and not info.get("ok"):
        output_path.unlink(missing_ok=True)
        raise CutoutError(f"외곽선 안쪽(흰 몸통 등)이 지워졌어요 (남은 비율 {round(info['bodyKept'] * 100)}%). 다른 방법을 쓰거나 원본을 사용해 주세요.")


def _cutout_once(input_path: Path, output_path: Path, model: str) -> dict:
    with _lock:
        try:
            result = _run(["-X", "utf8", str(CUTOUT_SCRIPT), str(input_path), str(output_path),
                           "--max-size", str(MAX_SIZE), "--model", model], TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            output_path.unlink(missing_ok=True)
            raise CutoutError("처리 시간이 너무 오래 걸려 중단했어요.") from None
        except OSError:
            raise CutoutError("시스템 Python을 실행하지 못했어요.") from None
    if result.returncode != 0 or not output_path.is_file():
        output_path.unlink(missing_ok=True)
        raise CutoutError(_failure_reason(result))
    _refine(output_path)
    return _check_result(output_path)


def _refine(output_path: Path) -> None:
    try:
        refined = _run(["-I", str(ALPHA_REFINE), str(output_path)], 60)
    except (OSError, subprocess.TimeoutExpired):
        refined = None
    if refined is None or refined.returncode != 0:
        output_path.unlink(missing_ok=True)
        raise CutoutError("결과 이미지의 투명도를 정리하지 못했어요.")


def _check_result(output_path: Path) -> dict:
    try:
        checked = _run(["-I", str(ALPHA_CHECK), str(output_path)], 60)
        stats = json.loads(checked.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        output_path.unlink(missing_ok=True)
        raise CutoutError("결과 이미지를 확인하지 못했어요.") from None
    if stats["format"] != "PNG" or stats["mode"] != "RGBA":
        output_path.unlink(missing_ok=True)
        raise CutoutError("결과가 투명 PNG가 아니에요.")
    # scripts/assign_images.py와 같은 기준
    if not 0.05 <= stats["transparent"] <= 0.95 or stats["opaque"] < 0.05:
        output_path.unlink(missing_ok=True)
        raise CutoutError("배경이 제대로 지워지지 않았어요. 다른 모델로 해 보거나 원본을 사용해 주세요.")
    if stats.get("holes", 0) > MAX_HOLES:
        output_path.unlink(missing_ok=True)
        raise CutoutError("피사체 안쪽(흰 몸통·얼굴 등)까지 지워졌어요. 다른 모델로 해 보거나 원본을 사용해 주세요.")
    if stats.get("translucent", 0) > MAX_TRANSLUCENT:
        output_path.unlink(missing_ok=True)
        raise CutoutError("피사체가 반투명하게 남아 배경이 비쳐 보여요. 다른 모델로 해 보거나 원본을 사용해 주세요.")
    return stats

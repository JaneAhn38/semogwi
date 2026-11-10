"""배경 제거 연결. 기존 scripts/cutout.py를 별도 프로세스로 실행합니다 (그 파일은 수정하지 않음).

- rembg와 Pillow는 시스템 Python에 이미 있으므로 웹 가상환경에 설치하지 않습니다.
- cutout.py는 모델이 없으면 자동으로 내려받습니다. 웹에서는 모델 파일이 있을 때만 실행해 다운로드를 막습니다.
- 메모리를 많이 쓰므로 한 번에 한 장만 처리합니다.
- 결과는 alpha_refine.py로 알파만 보정하고 alpha_check.py로 검사합니다.
- "자동"은 실물 사진용 → 그림용 → 가벼운 사진용 → 고품질 모델 순서로 시도해 검사를 통과한 첫 결과를 씁니다.
  사진용 모델은 흰 몸통 일러스트의 속을 지우고(구멍), 그림용 모델은 실물 사진의 마스크를 반투명하게 만들어서
  한 모델로는 두 경우를 모두 처리하지 못합니다.
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
PYTHON = os.environ.get("SEMOGWI_CUTOUT_PYTHON", "py")

MAX_SIZE = 1024  # scripts/assign_images.py와 같은 값
TIMEOUT_SECONDS = 300
AUTO = "auto"
# 화면에 보일 순서. 설치된 모델만 선택지로 나갑니다
MODELS = {
    AUTO: "자동 (사진·그림 판별)",
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
        return any(model_installed(m) for m in AUTO_ORDER)
    return any(path.is_file() for path in _model_files(model))


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
    if not CUTOUT_SCRIPT.is_file():
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
    if model != AUTO:
        return {**_cutout_once(input_path, output_path, model), "model": model, "tried": []}
    tried = []
    for candidate in [m for m in AUTO_ORDER if model_installed(m)]:
        try:
            stats = _cutout_once(input_path, output_path, candidate)
        except CutoutError as e:
            tried.append({"model": candidate, "reason": str(e)})
            continue
        return {**stats, "model": candidate, "tried": tried}
    raise CutoutError("자동으로 배경과 피사체를 구분하지 못했어요. 원본을 쓰거나 '고품질' 모델로 다시 해 보세요.")


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

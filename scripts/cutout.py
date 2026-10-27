r"""
세모귀 카드뉴스 - 이미지 배경 제거 프로그램 (cutout.py)

입력 이미지의 배경을 제거하고 투명 배경 PNG로 저장합니다.
메모리 사용량을 줄이기 위해 긴 변이 512px을 넘는 이미지는 비율을 유지한 채
512px로 축소한 뒤 배경을 제거합니다.

최신 rembg(2.0.86에서 확인)의 기본 모델은 'bria-rmbg'인데, 이 모델은 입력 이미지를 항상
1024x1024로 바꿔 처리하므로 메모리가 부족한 PC에서는 실패할 수 있습니다.
그래서 이 프로그램은 캐릭터 일러스트에 맞고 가벼운 'isnet-anime'을 기본으로 씁니다.

[설치]
    py -m pip install "rembg[cpu]" pillow

[사용법]
    py cutout.py 입력파일 [출력파일] [--max-size 픽셀] [--model 모델이름]

    출력파일을 생략하면 입력 파일과 같은 폴더에 "<이름>-cutout.png"로 저장됩니다.
    --max-size를 생략하면 긴 변 기준 최대 512px로 축소합니다.
    --model을 생략하면 isnet-anime 모델을 사용합니다.
        isnet-anime : 캐릭터·일러스트용 (기본값)
        u2net       : 일반 사진용, 가벼움
        u2netp      : 가장 가벼움, 품질은 낮음
        bria-rmbg   : rembg 기본값, 고품질이지만 메모리를 많이 씀

[예시]
    py cutout.py images\cat.jpg
    py cutout.py images\cat.jpg output\cat.png
    py cutout.py "C:\Users\me\사진\my cat.jpg" output\cat.png
    py cutout.py images\cat.jpg --max-size 384
    py cutout.py images\cat.jpg --model u2net
"""

import argparse
import platform
import struct
import sys
from pathlib import Path

try:
    from PIL import Image, ImageOps
    from rembg import new_session, remove
except ImportError:
    print("[오류] 필요한 라이브러리가 설치되어 있지 않습니다.")
    print('       다음 명령으로 설치해 주세요: py -m pip install "rembg[cpu]" pillow')
    sys.exit(1)

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
DEFAULT_MAX_SIZE = 512
DEFAULT_MODEL = "isnet-anime"

# Pillow 9.1 이상은 Image.Resampling.LANCZOS, 그 이전 버전은 Image.LANCZOS
try:
    LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    LANCZOS = Image.LANCZOS

# 메모리 부족 오류로 판단할 메시지 조각
MEMORY_ERROR_KEYWORDS = (
    "failed to allocate",
    "bfcarena",
    "out of memory",
    "memoryerror",
    "bad_alloc",
)


def default_output_path(input_path: Path) -> Path:
    """출력 경로를 지정하지 않았을 때 사용할 기본 경로를 만듭니다."""
    return input_path.with_name(f"{input_path.stem}-cutout.png")


def load_image(input_path: Path) -> Image.Image:
    """Pillow로 이미지를 읽어 메모리에 올립니다."""
    with Image.open(input_path) as image:
        # 휴대폰 사진의 EXIF 회전 정보를 실제 픽셀에 반영
        image = ImageOps.exif_transpose(image)
        # 팔레트(P), CMYK 등은 rembg가 다루기 쉬운 RGB/RGBA로 변환
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
        image.load()
        return image.copy()


def shrink_image(image: Image.Image, max_size: int) -> Image.Image:
    """긴 변이 max_size를 넘으면 비율을 유지하며 max_size로 축소합니다."""
    width, height = image.size
    longest = max(width, height)
    if longest <= max_size:
        return image

    scale = max_size / longest
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(new_size, LANCZOS)


def remove_background(input_path: Path, output_path: Path, max_size: int, model: str) -> None:
    """이미지 배경을 제거하고 투명 배경 PNG로 저장합니다."""
    image = load_image(input_path)
    original_size = image.size

    image = shrink_image(image, max_size)
    if image.size != original_size:
        print(f"이미지 크기 축소: {original_size[0]}x{original_size[1]} -> {image.size[0]}x{image.size[1]} (최대 {max_size}px)")
    else:
        print(f"이미지 크기: {original_size[0]}x{original_size[1]} (최대 {max_size}px 이하라 축소하지 않음)")

    print(f"사용 모델: {model}")
    result = remove(image, session=new_session(model))

    # 투명도를 유지하기 위해 RGBA로 맞춘 뒤 PNG로 저장
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.convert("RGBA").save(output_path, format="PNG")


def is_memory_error(error: BaseException) -> bool:
    """예외가 메모리 부족 때문인지 판단합니다."""
    if isinstance(error, MemoryError):
        return True
    message = f"{type(error).__name__} {error}".lower()
    return any(keyword in message for keyword in MEMORY_ERROR_KEYWORDS)


def model_folder() -> str:
    """rembg가 모델 파일을 저장하는 폴더를 찾습니다."""
    try:
        from rembg.sessions.base import BaseSession

        return str(BaseSession.u2net_home())
    except Exception:
        return r"%USERPROFILE%\.u2net 또는 %USERPROFILE%\.rembg"


def print_memory_diagnosis(max_size: int, model: str) -> None:
    """메모리 부족이 계속될 때 원인을 찾기 위한 안내를 출력합니다."""
    bits = struct.calcsize("P") * 8
    try:
        import onnxruntime

        ort_info = f"{onnxruntime.__version__} (장치: {onnxruntime.get_device()})"
    except Exception:
        ort_info = "확인 불가"

    print()
    print("[진단] 메모리 부족으로 배경 제거에 실패했습니다.")
    print(f"  - Python: {platform.python_version()} ({bits}비트)")
    print(f"  - ONNX Runtime: {ort_info}")
    print(f"  - 사용 모델: {model}")
    print()
    print("다음 순서로 원인을 확인해 보세요.")
    if bits == 32:
        print("  1. [중요] 32비트 Python은 프로세스당 약 2GB만 쓸 수 있습니다.")
        print("     64비트 Python을 설치한 뒤 rembg를 다시 설치해 주세요.")
    else:
        print("  1. 64비트 Python입니다. (32비트 메모리 한계 문제는 아님)")
    print("  2. 더 가벼운 모델로 바꿔 보세요: py cutout.py 입력파일 --model u2netp")
    print("     (bria-rmbg, birefnet-* 모델은 이미지 크기와 상관없이 1024x1024로 처리해")
    print("      수 GB의 메모리를 씁니다. 이미지를 줄여도 효과가 없습니다.)")
    print("  3. 작업 관리자(Ctrl+Shift+Esc) > 성능 > 메모리에서 남은 메모리를 확인하고,")
    print("     브라우저 등 메모리를 많이 쓰는 프로그램을 닫은 뒤 다시 실행해 보세요.")
    print(f"  4. 이미지를 더 작게 줄여 보세요: py cutout.py 입력파일 --max-size {max(128, max_size // 2)}")
    print("     (크기를 줄여도 같은 크기의 메모리 요청이 실패한다면 이미지가 아니라")
    print("      AI 모델 자체가 메모리를 쓰는 것이므로 2·5번을 확인해 주세요.)")
    print("  5. rembg 모델 파일이 손상되었을 수 있습니다.")
    print(f"     {model_folder()} 폴더의 .onnx 파일을 지우면 다음 실행 때 다시 내려받습니다.")
    print("  6. 설치된 버전을 확인해 보세요: py -m pip show rembg onnxruntime pillow")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="이미지의 배경을 제거하고 투명 배경 PNG로 저장합니다.",
        epilog="예시: py cutout.py images\\cat.jpg output\\cat.png",
    )
    parser.add_argument("input", help="배경을 제거할 입력 이미지 경로")
    parser.add_argument(
        "output",
        nargs="?",
        help="저장할 PNG 경로 (생략 시 '<입력파일명>-cutout.png')",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE,
        help=f"배경 제거 전 긴 변의 최대 픽셀 수 (기본값: {DEFAULT_MAX_SIZE})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"rembg 모델 이름 (기본값: {DEFAULT_MODEL}, 예: u2net, u2netp, bria-rmbg)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.max_size < 1:
        print(f"[오류] --max-size는 1 이상이어야 합니다: {args.max_size}")
        return 1

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"[오류] 입력 파일을 찾을 수 없습니다: {input_path}")
        return 1
    if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        print(f"[오류] 지원하지 않는 형식입니다: {input_path.suffix}")
        print(f"       지원 형식: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
        return 1

    output_path = Path(args.output) if args.output else default_output_path(input_path)
    if output_path.suffix.lower() != ".png":
        output_path = output_path.with_suffix(".png")
        print(f"[안내] 투명 배경을 유지하기 위해 PNG로 저장합니다: {output_path}")

    print(f"배경 제거 중... {input_path}")
    print("(처음 실행할 때는 AI 모델을 내려받느라 시간이 걸릴 수 있습니다)")
    try:
        remove_background(input_path, output_path, args.max_size, args.model)
    except Exception as error:
        print(f"[오류] 배경 제거에 실패했습니다: {error}")
        if is_memory_error(error):
            print_memory_diagnosis(args.max_size, args.model)
        return 1

    print(f"완료! 저장 위치: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

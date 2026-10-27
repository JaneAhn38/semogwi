r"""
세모귀 카드뉴스 - 이미지 배경 제거 프로그램 (cutout.py)

입력 이미지의 배경을 제거하고 투명 배경 PNG로 저장합니다.

[설치]
    py -m pip install "rembg[cpu]" pillow

[사용법]
    py cutout.py 입력파일 [출력파일]

    출력파일을 생략하면 입력 파일과 같은 폴더에 "<이름>-cutout.png"로 저장됩니다.

[예시]
    py cutout.py images\cat.jpg
    py cutout.py images\cat.jpg output\cat.png
    py cutout.py "C:\Users\me\사진\my cat.jpg" output\cat.png
"""

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
    from rembg import remove
except ImportError:
    print("[오류] 필요한 라이브러리가 설치되어 있지 않습니다.")
    print('       다음 명령으로 설치해 주세요: py -m pip install "rembg[cpu]" pillow')
    sys.exit(1)

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def default_output_path(input_path: Path) -> Path:
    """출력 경로를 지정하지 않았을 때 사용할 기본 경로를 만듭니다."""
    return input_path.with_name(f"{input_path.stem}-cutout.png")


def remove_background(input_path: Path, output_path: Path) -> None:
    """이미지 배경을 제거하고 투명 배경 PNG로 저장합니다."""
    with Image.open(input_path) as image:
        result = remove(image)

    # 투명도를 유지하기 위해 RGBA로 맞춘 뒤 PNG로 저장
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.convert("RGBA").save(output_path, format="PNG")


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
    return parser.parse_args()


def main() -> int:
    args = parse_args()

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
        remove_background(input_path, output_path)
    except Exception as error:
        print(f"[오류] 배경 제거에 실패했습니다: {error}")
        return 1

    print(f"완료! 저장 위치: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

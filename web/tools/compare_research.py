"""자료조사 결과 비교 (수정 전후, 보관함 버전끼리).

사용법 (web 폴더에서):
  .venv\\Scripts\\python tools\\compare_research.py <A> <B> [--data 데이터폴더]

A·B에는 작업 id, 조사 자료 보관함의 버전 id, 또는 job.json / 보관함 JSON 파일 경로를 줄 수 있습니다.
데이터 폴더를 주지 않으면 SEMOGWI_DATA_DIR 또는 web/data를 씁니다. 파일을 읽기만 하고 고치지 않습니다.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import research as research_items  # noqa: E402


def load(ref: str, data_dir: Path) -> tuple[str, str, dict]:
    """(이름, 유형, 조사 결과)"""
    path = Path(ref)
    if not path.is_file():
        for candidate in (data_dir / "jobs" / ref / "job.json", data_dir / "research" / f"{ref}.json"):
            if candidate.is_file():
                path = candidate
                break
        else:
            raise SystemExit(f"찾을 수 없어요: {ref}")
    record = json.loads(path.read_text(encoding="utf-8"))
    research = dict(record.get("research") or {})
    research.setdefault("researchedAt", record.get("researchedAt", ""))  # 보관함 파일은 조사일을 바깥에 둡니다
    name = f"{record.get('topic', '')} ({path.parent.name if path.name == 'job.json' else path.stem})"[:40]
    return name, record.get("contentType", ""), research


def main() -> None:
    parser = argparse.ArgumentParser(description="자료조사 결과 비교")
    parser.add_argument("a")
    parser.add_argument("b")
    parser.add_argument("--data", default=os.environ.get("SEMOGWI_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    data_dir = Path(args.data)
    (name_a, type_a, res_a), (name_b, type_b, res_b) = load(args.a, data_dir), load(args.b, data_dir)
    rep_a, rep_b = research_items.research_report(res_a, type_a), research_items.research_report(res_b, type_b)

    print(f"{'':22}{name_a:<42}{name_b}")
    for key in ("pipeline", "researchedAt", "queries", "pagesRead", "sourcesRead", "officialRead", "found", "items", "facts", "peopleWithTmi"):
        print(f"{key:<22}{str(rep_a[key]):<42}{rep_b[key]}")
    print(f"{'byImportance':<22}{json.dumps(rep_a['byImportance'], ensure_ascii=False):<42}{json.dumps(rep_b['byImportance'], ensure_ascii=False)}")
    print(f"{'core ready':<22}{str((rep_a['core'] or {}).get('ready')):<42}{(rep_b['core'] or {}).get('ready')}")
    print(f"{'states':<22}{json.dumps(rep_a['states'], ensure_ascii=False):<42}{json.dumps(rep_b['states'], ensure_ascii=False)}")
    print(f"{'review':<22}{', '.join(rep_a['review']) or '-':<42}{', '.join(rep_b['review']) or '-'}")

    print("\n항목별 상태 (값은 앞 30자)")
    items_a = {i["key"]: i for i in res_a.get("items") or []}
    items_b = {i["key"]: i for i in res_b.get("items") or []}
    labels = research_items.STATE_LABELS
    for key in dict.fromkeys(list(items_a) + list(items_b)):
        a, b = items_a.get(key, {}), items_b.get(key, {})
        cell = lambda i: f"{labels.get(i.get('state'), '-')} {i.get('value', '')[:30]}".strip() if i else "-"
        mark = "" if a.get("state") == b.get("state") else "  *"
        print(f"  {key:<20}{cell(a):<42}{cell(b)}{mark}")


if __name__ == "__main__":
    main()

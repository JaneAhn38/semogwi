"""고정 템플릿 (작업 형식 3). 규격: docs/template-spec.md

팀이 만든 디자인(templates/reference/*.png)을 템플릿 JSON(web/templates/*.json)으로 옮겼습니다.
- 유형마다 card-01 ~ card-05의 템플릿이 따로 있습니다 (<유형>-01.json ~ -05.json).
- 서버는 필드 정의로 구성안을 검사하고, AI 출력 형식과 규칙을 만듭니다.
- 브라우저(static/renderer.js)가 같은 JSON으로 카드를 그립니다. 미리보기와 PNG는 같은 그림입니다.
- AI는 좌표를 만들지 않습니다. 문구와 사실만 씁니다.

예전 형식 3 작업(표지 1종 + 본문 1종 반복)은 legacy 템플릿으로 그대로 엽니다.
"""

import json
import re
from pathlib import Path

from . import research
from .outline import ROLE_MAX, SOURCE_MAX, SOURCE_PREFIX
from .provider import FRAMES

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
FORMAT = 3
ENABLED_TYPES = {"character", "goods", "collab", "popup"}  # 템플릿을 쓰는 유형. 테스트에서 비워 기존 방식을 검사할 수 있습니다
FIELD_TYPES = {"text", "multiline", "list", "items", "pairs", "flag", "choice"}  # choice: 정해진 선택지 중 하나 (예: 친구/가족)
ITEM_FIELD_TYPES = {"text", "multiline"}
ELEMENT_TYPES = {"header", "footer", "rect", "circle", "line", "text", "image", "rows", "chips", "pill", "bullets", "check", "asset", "star", "stack", "columns",
                 "profile"}
FREE = "free"  # 자유 구성 카드 (<유형>-free.json). card-02 ~ card-05에서 확보된 자료에 맞춰 AI가 고릅니다
MULTILINE_MAX_LINES = 2
DEMO_SOURCE = "출처: 데모 (실제 출처 아님)"
LEGACY_SET = {"character": ["character-cover"] + ["character-body"] * 4}  # 예전 형식 3 작업
# 디자인을 바꾼 템플릿의 예전 판. 저장된 작업이 예전 필드(old_key)를 갖고 있으면 예전 판으로 엽니다 (내용을 옮기거나 버리지 않음)
OLD_VERSIONS = {"character-02": {"id": "character-02-v1", "old_key": "birthday"},  # 고정 4줄(이름·생일·좋아하는 것·작가) 프로필
                "character-04": {"id": "character-04-v1", "old_key": "tmi_items"},
                "character-05": {"id": "character-05-v1", "old_key": "recommend_for"}}

# PNG에 자리표시 문구가 남지 않게 합니다: [캐릭터 이름], MM월 DD일, YYYY.MM.DD 같은 틀.
# 한글이 바로 붙어도 잡히도록 \b 대신 영문자 경계를 씁니다 ("MM월"). 실제 시각일 수 있는 00:00은 대괄호 안일 때만 잡습니다.
PLACEHOLDER_RE = re.compile(r"\[[^\[\]\n]{1,40}\]|(?<![A-Za-z])(?:YYYY|MM|DD)(?![A-Za-z])")
_TOKEN_RE = re.compile(r"\{([\w.]+)\}")
_RESERVED_TOKENS = {"page", "total", "no", "source", "source_text"}


class TemplateError(ValueError):
    """템플릿 파일 자체가 잘못된 경우. 서버 시작 때 드러나도록 합니다."""


def has_source(tpl: dict) -> bool:
    """출처를 표시하는 카드인지. 표지와, 조사한 사실을 담지 않는 카드(showSource: false, 예: 다음 편 예고)에는 출처를 두지 않습니다."""
    return tpl["kind"] != "cover" and tpl.get("showSource", True)


def _path_ok(path: str, fields: dict[str, dict]) -> bool:
    """필드 경로(traits.0.keyword)가 정의와 맞는지 확인합니다."""
    parts = path.split(".")
    field = fields.get(parts[0])
    if not field:
        return False
    if len(parts) == 1:
        return True
    if field["type"] not in ("items", "list") or not parts[1].isdigit() or int(parts[1]) >= field["maxItems"]:
        return False
    if field["type"] == "list":
        return len(parts) == 2
    return len(parts) == 2 or (len(parts) == 3 and parts[2] in {f["key"] for f in field["fields"]})


def _conditions(expr) -> list[str]:
    """조건은 문자열 하나 또는 목록(모두 만족)입니다. 'friends.0'은 값이 있을 때, 'category=family'는 그 값일 때,
    '!next_name'은 값이 비어 있을 때."""
    if not expr:
        return []
    return [expr] if isinstance(expr, str) else list(expr)


def _condition_ok(expr, fields: dict[str, dict]) -> bool:
    for cond in _conditions(expr):
        negate = cond.startswith("!")
        path, eq, value = cond.removeprefix("!").partition("=")
        if not _path_ok(path, fields) or (negate and eq):
            return False
        field = fields[path.split(".")[0]]
        if eq and (field["type"] != "choice" or value not in {o["value"] for o in field["options"]}):
            return False
    return True


def condition_met(tpl: dict, values: dict, expr) -> bool:
    """카드 값에서 조건이 맞는지. 저장된 값이 없으면 필드 기본값으로 봅니다 (예: 예전 카드의 카테고리는 '친구')."""
    defaults = {f["key"]: f.get("default") for f in tpl["fields"]}
    for cond in _conditions(expr):
        negate = cond.startswith("!")
        path, eq, expected = cond.removeprefix("!").partition("=")
        value = _get_path(values or {}, path)
        if value in (None, "") and "." not in path:
            value = defaults.get(path)
        if eq:
            if str(value or "") != expected:
                return False
        elif bool(value) == negate:
            return False
    return True


def field_active(tpl: dict, field: dict, values: dict) -> bool:
    """카드에 보이는 필드인지 (예: 카테고리가 가족이면 친구 목록은 보관만 하고 그리지 않음)."""
    return condition_met(tpl, values, field.get("if"))


def _check_template(tpl: dict, name: str) -> None:
    for key in ("id", "contentType", "kind", "label", "fonts", "palette", "fields", "images", "elements"):
        if key not in tpl:
            raise TemplateError(f"{name}: '{key}'가 없어요")
    if tpl["kind"] not in ("cover", "body"):
        raise TemplateError(f"{name}: kind는 cover 또는 body예요")
    fields = {}
    for field in tpl["fields"]:
        if field.get("type") not in FIELD_TYPES:
            raise TemplateError(f"{name}: 알 수 없는 필드 형식 {field.get('type')}")
        if field["key"] in fields or field["key"] in _RESERVED_TOKENS:
            raise TemplateError(f"{name}: 필드 이름이 겹쳐요 ({field['key']})")
        if field.get("item") and field["item"] not in research.keys_of(tpl["contentType"]):
            raise TemplateError(f"{name}: {field['key']}의 조사 항목 {field['item']}이 없어요")
        if field["type"] == "items" and not all(f.get("type") in ITEM_FIELD_TYPES for f in field.get("fields", [])):
            raise TemplateError(f"{name}: {field['key']} 항목의 하위 필드는 text, multiline만 쓸 수 있어요")
        if field.get("minItems") and not (field["type"] == "items" and 1 <= field["minItems"] <= field.get("defaultItems", field["minItems"]) <= field["maxItems"]):
            raise TemplateError(f"{name}: {field['key']}의 minItems·defaultItems·maxItems가 맞지 않아요")
        if field["type"] == "choice" and (not field.get("options") or field.get("default") not in {o["value"] for o in field["options"]}):
            raise TemplateError(f"{name}: {field['key']} 선택지와 기본값이 맞지 않아요")
        # editor: list → 구성안에서 항목을 추가·삭제하는 편집기 (0개부터). verifyItems → 줄마다 조사 값과 대조할 조사 항목
        if field.get("editor") == "list" and not (field["type"] == "items" and field.get("maxItems", 0) >= 1):
            raise TemplateError(f"{name}: {field['key']}의 목록 편집기는 items 필드에만 쓸 수 있어요")
        if field.get("verifyItems") and (field["type"] != "items" or {f["key"] for f in field.get("fields", [])} != {"label", "value"}
                                         or not set(field["verifyItems"]) <= set(research.keys_of(tpl["contentType"]))):
            raise TemplateError(f"{name}: {field['key']}의 verifyItems는 label·value 항목과 있는 조사 항목만 쓸 수 있어요")
        fields[field["key"]] = field
    for field in tpl["fields"]:
        if field.get("if") and not _condition_ok(field["if"], fields):
            raise TemplateError(f"{name}: {field['key']}의 조건이 잘못됐어요 ({field['if']})")
    # nextTeaser: 다음 캐릭터 예고 카드. 이름·힌트·공개 문구 칸은 사용자 입력 칸이고, 힌트·공개 문구에는 기본 문구가 있어야 합니다
    teaser = tpl.get("nextTeaser")
    if teaser and not (all(fields.get(teaser.get(k), {}).get("userOnly") for k in ("name", "hint", "reveal"))
                       and all(fields[teaser[k]].get("placeholder") for k in ("hint", "reveal"))):
        raise TemplateError(f"{name}: nextTeaser의 칸은 사용자 입력 칸이어야 하고 힌트·공개 문구에 기본 문구가 있어야 해요")
    # inherit: 표지(card-01)의 값을 그대로 보여 주는 필드 (예: 브랜드명). 이 카드에서는 고치지 않습니다
    for key in tpl.get("inherit", []):
        if key in fields:
            raise TemplateError(f"{name}: {key}는 물려받는 필드라 직접 정의할 수 없어요")
        fields[key] = {"key": key, "type": "text"}
    slots = {image["key"] for image in tpl["images"]}
    for image in tpl["images"]:
        if image.get("if") and not _condition_ok(image["if"], fields):
            raise TemplateError(f"{name}: 이미지 자리 {image['key']}의 조건 필드가 없어요 ({image['if']})")
    for el in tpl["elements"]:
        kind = el.get("type")
        if kind not in ELEMENT_TYPES:
            raise TemplateError(f"{name}: 알 수 없는 요소 {kind}")
        paths = [el.get("field")] + [item["field"] for item in el.get("items", [])]
        for path in filter(None, paths):
            if not _path_ok(path, fields):
                raise TemplateError(f"{name}: 없는 필드를 써요 ({path})")
        if el.get("if") and not _condition_ok(el["if"], fields):
            raise TemplateError(f"{name}: 없는 필드를 써요 ({el['if']})")
        if kind == "image" and el.get("slot") not in slots:
            raise TemplateError(f"{name}: 없는 이미지 자리를 그려요 ({el.get('slot')})")
        # ifNoImage: 그 이미지 자리가 비어 있을 때만 그립니다 (예: 다음 캐릭터 이미지가 없으면 '?')
        if el.get("ifNoImage") and el["ifNoImage"] not in slots:
            raise TemplateError(f"{name}: 없는 이미지 자리를 조건으로 써요 ({el['ifNoImage']})")
        if kind == "stack":
            # 내용 양에 맞춰 높이가 바뀌는 묶음: 소개 문장(multiline) · 정보 줄(pairs) · 참고 사항(list) · 이미지 자리
            expected = {"lead": "multiline", "rows": "pairs", "notes": "list"}
            for part, field_type in expected.items():
                if el.get(part) and (fields.get(el[part]) or {}).get("type") != field_type:
                    raise TemplateError(f"{name}: stack의 {part}는 {field_type} 필드여야 해요")
            if el.get("slot") and el["slot"] not in slots:
                raise TemplateError(f"{name}: 없는 이미지 자리를 그려요 ({el['slot']})")
        if kind == "columns":
            # 캐릭터 묶음을 가로로 나열: 항목(items)마다 원형 이미지 · 이름 · 관계 · 개별 TMI
            field = fields.get(el.get("field"), {})
            if field.get("type") != "items" or not {"name", "relation", "tmi"} <= {f["key"] for f in field["fields"]}:
                raise TemplateError(f"{name}: columns는 name·relation·tmi가 있는 items 필드여야 해요")
            if any(f"{el.get('slotPrefix')}{i}" not in slots for i in range(1, field["maxItems"] + 1)):
                raise TemplateError(f"{name}: columns의 이미지 자리가 인원 수만큼 있어야 해요")
        if kind == "profile":
            # 프로필: 이름(필수) + 프로필 줄 0~3개 + 소개 문장. 줄 수와 이미지 유무에 따라 이미지 크기·줄 간격·배치를 정합니다
            expected = {"name": "text", "rows": "items", "intro": "multiline", "tags": "list"}
            for part, field_type in expected.items():
                if el.get(part) and (fields.get(el[part]) or {}).get("type") != field_type:
                    raise TemplateError(f"{name}: profile의 {part}는 {field_type} 필드여야 해요")
            if not el.get("name") or not el.get("rows") or el.get("slot") not in slots:
                raise TemplateError(f"{name}: profile에는 name·rows 필드와 이미지 자리가 있어야 해요")
        if (el.get("fallback") or el.get("prefix")) and not el.get("field"):
            raise TemplateError(f"{name}: fallback·prefix는 field가 있는 글자 요소에만 쓸 수 있어요")
        # fallback: 값이 비었을 때 보여 줄 기본 안내 문구. 고정 문구처럼 자리표시를 쓰면 안 됩니다
        for text in [el.get("text"), el.get("left"), el.get("tag"), el.get("fallback"), el.get("prefix")] + el.get("parts", []):
            if not text:
                continue
            for token in _TOKEN_RE.findall(text):
                if token not in _RESERVED_TOKENS and not _path_ok(token, fields):
                    raise TemplateError(f"{name}: 알 수 없는 치환 {{{token}}}")
            if PLACEHOLDER_RE.search(_TOKEN_RE.sub("", text)):
                raise TemplateError(f"{name}: 고정 문구에 자리표시가 있어요 ({text})")


def _check_set(content_type: str, ids: list[str], templates: dict) -> None:
    """한 세트 안에서 같은 이름의 필드는 같은 형식이어야 합니다 (AI 출력 형식을 하나로 만들기 때문)."""
    seen = {}
    for tid in ids:
        for field in templates[tid]["fields"]:
            shape = json.dumps({k: field.get(k) for k in ("type", "fields")}, sort_keys=True)
            if seen.setdefault(field["key"], shape) != shape:
                raise TemplateError(f"{content_type}: {field['key']} 필드 형식이 카드마다 달라요")


def load_all(directory: Path = TEMPLATE_DIR) -> dict[str, dict]:
    templates = {}
    for path in sorted(directory.glob("*.json")):
        tpl = json.loads(path.read_text(encoding="utf-8"))
        _check_template(tpl, path.name)
        templates[tpl["id"]] = tpl
    for content_type in {t["contentType"] for t in templates.values()}:
        ids = [f"{content_type}-0{i}" for i in range(1, 6)]
        if all(i in templates for i in ids):
            _check_set(content_type, ids + ([f"{content_type}-{FREE}"] if f"{content_type}-{FREE}" in templates else []), templates)
            cover_keys = {f["key"] for f in templates[ids[0]]["fields"]}
            for tid in ids[1:]:
                missing = set(templates[tid].get("inherit", [])) - cover_keys
                if missing:
                    raise TemplateError(f"{tid}: 표지에 없는 필드를 물려받아요 ({', '.join(sorted(missing))})")
    return templates


TEMPLATES = load_all()
CHOICE_KEYS = {f["key"] for t in TEMPLATES.values() for f in t["fields"] if f["type"] == "choice"}  # 내용이 아니라 표시 방식을 고르는 필드
USER_ONLY_KEYS = {f["key"] for t in TEMPLATES.values() for f in t["fields"] if f.get("userOnly")}  # 사용자만 입력하는 필드 (AI는 쓰지 않음)


def template_set(content_type: str) -> list[str] | None:
    """card-01 ~ card-05에 쓸 템플릿 id. 다섯 장이 모두 있어야 씁니다."""
    ids = [f"{content_type}-0{i}" for i in range(1, 6)]
    return ids if all(i in TEMPLATES for i in ids) else None


def body_choices(content_type: str) -> list[str]:
    """card-02 ~ card-05에 쓸 수 있는 템플릿. 유형의 본문 템플릿 4종과 자유 구성입니다 (같은 유형이라 디자인이 통일됩니다)."""
    ids = [f"{content_type}-0{i}" for i in range(2, 6)] + [f"{content_type}-{FREE}"]
    return [i for i in ids if i in TEMPLATES]


def is_flexible(job: dict) -> bool:
    """카드마다 템플릿을 고르는 작업인지. 예전 형식 3 작업(templateSet 없음)은 그대로 둡니다."""
    return bool(job.get("templateSet")) and f"{job['contentType']}-{FREE}" in TEMPLATES


def free_id(content_type: str) -> str:
    return f"{content_type}-{FREE}"


def enabled(content_type: str) -> bool:
    return content_type in ENABLED_TYPES and template_set(content_type) is not None


def is_template_job(job: dict) -> bool:
    return job.get("format") == FORMAT


def set_of(job: dict) -> list[str]:
    return job.get("templateSet") or LEGACY_SET[job["contentType"]]


def template_for(job: dict, frame: str) -> dict:
    return TEMPLATES[set_of(job)[FRAMES.index(frame)]]


# ---------- 필드 정리와 검사 ----------
def _text(value) -> str:
    return str(value or "").replace("\r", "").strip()


def _clean_value(field: dict, value):
    kind = field["type"]
    if kind == "flag":
        return value is True
    if kind == "choice":
        return value if value in {o["value"] for o in field["options"]} else field["default"]
    if kind == "text":
        return " ".join(_text(value).split())
    if kind == "multiline":
        lines = [" ".join(line.split()) for line in _text(value).split("\n")]
        return "\n".join(line for line in lines if line)
    if kind == "list":
        items = value if isinstance(value, list) else []
        return [t for t in (" ".join(_text(i).lstrip("#").split()) for i in items) if t]
    if kind == "items":
        cleaned = []
        for item in value if isinstance(value, list) else []:
            if not isinstance(item, dict):
                continue
            entry = {sub["key"]: _clean_value(sub, item.get(sub["key"])) for sub in field["fields"]}
            if any(entry.values()):
                cleaned.append(entry)
        return cleaned
    cleaned = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            label, val = " ".join(_text(item.get("label")).split()), " ".join(_text(item.get("value")).split())
            if label or val:
                cleaned.append({"label": label, "value": val})
    return cleaned


def clean_fields(tpl: dict, raw: dict | None, *, strict: bool = False) -> dict:
    """필드 값을 정해진 형식으로 정리합니다. strict이면 정의에 없는 필드를 거부합니다(사용자 수정)."""
    raw = raw if isinstance(raw, dict) else {}
    unknown = set(raw) - {f["key"] for f in tpl["fields"]}
    if strict and unknown:
        raise ValueError(f"알 수 없는 항목이에요: {', '.join(sorted(unknown))}")
    return {field["key"]: _clean_value(field, raw.get(field["key"])) for field in tpl["fields"]}


def _placeholders(text: str) -> list[str]:
    return [m.group(0) for m in PLACEHOLDER_RE.finditer(text)]


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    return []


def card_text(card: dict) -> str:
    """숫자 대조와 검색에 쓰는 카드의 모든 문구 (출처 제외)."""
    return " ".join(_strings(card.get("fields") or {}))


def _check_text(field: dict, value: str, label: str) -> list[str]:
    errors = []
    length = len(value.replace("\n", ""))
    if length > field["max"]:
        errors.append(f"{label}: {field['max']}자 이내로 줄여 주세요 (현재 {length}자)")
    if field["type"] == "multiline" and value.count("\n") >= MULTILINE_MAX_LINES:
        errors.append(f"{label}: {MULTILINE_MAX_LINES}줄 이하로 써 주세요")
    return errors


def check_fields(tpl: dict, fields: dict) -> dict:
    errors, warnings = [], []
    for field in tpl["fields"]:
        key, label, kind = field["key"], field["label"], field["type"]
        value = fields.get(key)
        active = field_active(tpl, field, fields)  # 카드에 보이지 않는 목록(다른 카테고리)은 필수·최소 인원을 따지지 않습니다
        if field.get("required") and active and not value:
            errors.append(f"{label}: 꼭 필요한 항목이에요. 확인된 내용을 입력해 주세요")
            continue
        if not value or kind in ("flag", "choice"):
            continue
        if kind in ("text", "multiline"):
            errors += _check_text(field, value, label)
        elif kind == "list":
            if len(value) > field["maxItems"]:
                errors.append(f"{label}: {field['maxItems']}개까지 넣을 수 있어요")
            for item in value:
                if len(item) > field["itemMax"]:
                    errors.append(f"{label}: '{item}'은 {field['itemMax']}자 이내로 줄여 주세요")
        elif kind == "items":
            if len(value) > field["maxItems"]:
                errors.append(f"{label}: {field['maxItems']}개까지 넣을 수 있어요")
            if active and len(value) < field.get("minItems", 0):
                errors.append(f"{label}: {field['minItems']}개 이상 필요해요 (현재 {len(value)}개). 확인된 항목이 부족하면 카드 구성을 '자유 구성'으로 바꿔 주세요")
            for n, item in enumerate(value, 1):
                for sub in field["fields"]:
                    name = f"{label} {n} {sub['label']}"
                    if sub.get("required") and not item.get(sub["key"]):
                        errors.append(f"{name}: 꼭 필요한 항목이에요. 확인된 내용을 입력하거나 이 항목을 지워 주세요")
                    elif item.get(sub["key"]):
                        errors += _check_text(sub, item[sub["key"]], name)
        elif kind == "pairs":
            if len(value) > field["maxItems"]:
                errors.append(f"{label}: {field['maxItems']}줄까지 넣을 수 있어요")
            for item in value:
                if not item["label"] or not item["value"]:
                    errors.append(f"{label}: 항목 이름과 내용을 함께 적어 주세요")
                elif len(item["label"]) > field["labelMax"]:
                    errors.append(f"{label}: 항목 이름 '{item['label']}'은 {field['labelMax']}자 이내로 줄여 주세요")
                elif len(item["value"]) > field["valueMax"]:
                    errors.append(f"{label}: '{item['label']}' 내용은 {field['valueMax']}자 이내로 줄여 주세요")
    found = [p for s in _strings(fields) for p in _placeholders(s)]
    if found:
        errors.append(f"자리표시 문구가 남아 있어요: {', '.join(dict.fromkeys(found))}. 실제 내용으로 바꾸거나 지워 주세요")
    return {"errors": errors, "warnings": warnings}


def check_card(card: dict, tpl: dict) -> dict:
    """구성안 카드 한 장의 {errors, warnings}. errors가 있으면 승인할 수 없습니다."""
    result = check_fields(tpl, card.get("fields") or {})
    errors, warnings = result["errors"], result["warnings"]
    role = card.get("role", "")
    if not role:
        errors.insert(0, "역할을 입력해 주세요")
    elif len(role) > ROLE_MAX:
        errors.insert(0, f"역할은 {ROLE_MAX}자 이내로 입력해 주세요 (현재 {len(role)}자)")
    source = card.get("source", "")
    if has_source(tpl):
        if not source:
            warnings.append("출처가 비어 있어요. 카드에 표시할 출처를 적어 주세요")
        elif "\n" in source:
            errors.append("출처에는 줄바꿈을 넣을 수 없어요")
        elif len(source) > SOURCE_MAX:
            errors.append(f"출처는 {SOURCE_MAX}자 이내로 입력해 주세요 (현재 {len(source)}자)")
        elif not source.startswith(SOURCE_PREFIX):
            errors.append(f"출처는 '{SOURCE_PREFIX}'로 시작해 주세요")
        elif _placeholders(source):
            errors.append("출처에 자리표시 문구가 남아 있어요")
    return {"errors": errors, "warnings": warnings}


def issues_of(job: dict, cards: list[dict]) -> dict:
    issues = {c["frame"]: check_card(c, template_for(job, c["frame"])) for c in cards}
    if not is_flexible(job):
        return issues
    # 유연한 구성: 비거나 겹치는 카드는 알리기만 하고 승인을 막지 않습니다 (사실 확인 문제가 아니기 때문)
    repeated = repeated_values(cards)
    # 캐릭터 소개(AI): 친구·가족 가로형 카드가 없으면 이유와 바꾸는 방법을 알리고, 친구와 가족이 섞였으면 알립니다
    friends_id = PEOPLE_TEMPLATE
    people = research.people_of((job.get("research") or {}).get("items")) if job["contentType"] == "character" else {}
    if (job["contentType"] == "character" and job.get("mode") == "ai" and friends_id in TEMPLATES
            and not any(c.get("template") in (friends_id, OLD_VERSIONS[friends_id]["id"]) for c in cards)):
        target = next((c for c in cards[1:] if c.get("template") == free_id(job["contentType"])), None)
        enough = [(CATEGORY_LABELS[k], v) for k, v in people.items() if len(v) >= 2]
        if target is not None:
            issues[target["frame"]]["warnings"].append(
                (f"조사에서 {enough[0][0]} 캐릭터 {len(enough[0][1])}명({', '.join(p['name'] for p in enough[0][1])})이 확인됐어요. " if enough else
                 "출처로 확인된 친구·가족 캐릭터가 각각 2명 미만이라 캐릭터별 사진·TMI 가로형 카드 대신 자유 구성으로 만들었어요. 캐릭터를 지어내지 않았어요. ")
                + "'카드 구성'에서 '친구와 TMI'를 고르면 친구 또는 가족 캐릭터 2~4명의 이름·관계·TMI를 직접 입력할 수 있어요")
    for card in cards[1:]:
        if card.get("template") == friends_id:
            mixed = mixed_people(card, people)
            if mixed:
                issues[card["frame"]]["warnings"].append(mixed)
            issues[card["frame"]]["warnings"] += tmi_notes(card, job.get("mode") == "ai")
    for card in cards[1:]:
        notes = issues[card["frame"]]["warnings"]
        if card.get("convertedFrom"):
            original = TEMPLATES[card["convertedFrom"]]
            lacking = [f["label"] for f in original["fields"] if f.get("required")]
            notes.append(f"{', '.join(lacking)} 정보가 확인되지 않아 '{original['label']}' 대신 자유 구성 카드로 만들었어요. 확인된 정보만 담았어요")
        if is_empty_card(card):
            notes.append("이 카드에 담을 확인된 정보가 없어요. 내용을 직접 입력하거나 다른 카드와 겹치지 않는 확인된 정보로 바꿔 주세요")
        if repeated.get(card["frame"]):
            notes.append(f"앞 카드와 같은 내용이 반복돼요: {', '.join(repeated[card['frame']][:2])}")
    return issues


PEOPLE_TEMPLATE = "character-04"  # 친구·가족 가로형 카드
CATEGORY_LABELS = {"friends": "친구", "family": "가족"}


def mixed_people(card: dict, people: dict) -> str:
    """카드에 보이는 목록에 다른 카테고리(친구↔가족)로 조사된 캐릭터가 섞였으면 안내 문구를 돌려줍니다."""
    tpl = TEMPLATES.get(card.get("template"))
    if not tpl or not people:
        return ""
    for field in tpl["fields"]:
        if field.get("type") != "items" or field["key"] not in CATEGORY_LABELS or not field_active(tpl, field, card["fields"]):
            continue
        other = "family" if field["key"] == "friends" else "friends"
        names = {p["name"] for p in people.get(other, [])}
        wrong = [i["name"] for i in card["fields"].get(field["key"]) or [] if i.get("name") in names]
        if wrong:
            return (f"{CATEGORY_LABELS[other]} 캐릭터로 조사된 {', '.join(wrong)}이(가) {CATEGORY_LABELS[field['key']]} 카드에 들어 있어요. "
                    f"친구와 가족은 한 카드에 섞지 않아요. 카테고리를 바꾸거나 해당 캐릭터를 지워 주세요")
    return ""


def tmi_notes(card: dict, ai: bool) -> list[str]:
    """카드에 보이는 친구·가족 목록의 TMI 안내: 비어 있는 캐릭터, 관계만 반복했거나 다른 캐릭터와 같은 TMI (승인은 막지 않음)."""
    tpl = TEMPLATES.get(card.get("template"))
    notes = []
    for field in (tpl or {}).get("fields", []):
        if field.get("type") != "items" or field["key"] not in CATEGORY_LABELS or not field_active(tpl, field, card["fields"]):
            continue
        items = card["fields"].get(field["key"]) or []
        empty = [i["name"] for i in items if i.get("name") and not i.get("tmi")]
        seen: set[str] = set()
        weak = []
        for item in items:
            if item.get("tmi"):
                problem = research.tmi_problem(item["name"], item.get("relation", ""), item["tmi"], seen)
                if problem:
                    weak.append(f"{item['name']}({problem})")
                seen.add(research._norm(item["tmi"]))
        if empty and ai:
            notes.append(f"출처에서 TMI를 확인하지 못한 캐릭터: {', '.join(empty)}. 확인한 내용이 있으면 직접 입력해 주세요 (없는 내용은 만들지 않았어요)")
        if weak:
            notes.append(f"TMI로 보기 어려운 내용이 있어요: {', '.join(weak)}. 관계 대신 그 캐릭터만의 성격·취미·특징을 써 주세요")
    return notes


def _missing_required(tpl: dict, fields: dict) -> list[dict]:
    """카드에 보이는 필수 필드 중 비었거나 최소 개수가 모자란 것."""
    return [f for f in tpl["fields"] if f.get("required") and field_active(tpl, f, fields)
            and len(fields.get(f["key"]) or []) < max(1, f.get("minItems", 0))]


def _fit_choice(tpl: dict, fields: dict) -> dict | None:
    """선택 필드(예: 친구/가족)를 다른 값으로 바꾸면 필수 항목이 채워지는 경우 그 값으로 바꾼 필드를 돌려줍니다."""
    for field in tpl["fields"]:
        if field["type"] != "choice":
            continue
        for option in field["options"]:
            candidate = {**fields, field["key"]: option["value"]}
            if option["value"] != fields.get(field["key"]) and not _missing_required(tpl, candidate):
                return candidate
    return None


def move_fields(job: dict, card: dict, template_id: str) -> dict:
    """카드 구성을 바꿀 때 값을 옮깁니다. {"fields", "missing"(새 구성의 비는 필수 항목 이름)}

    자유 구성으로 바꾸면 기존 값을 정보 줄로 옮기고, 전용 템플릿으로 바꾸면 같은 이름의 필드와
    이름이 같은 정보 줄(예: '가격')만 옮깁니다. 새 값은 만들지 않습니다.
    """
    current = TEMPLATES[card["template"]]
    target = TEMPLATES[template_id]
    if template_id.endswith(f"-{FREE}"):
        # 카드에 보이던 값만 옮깁니다 (다른 카테고리로 보관 중인 목록은 섞지 않음)
        rows = [row for field in current["fields"] if card["fields"].get(field["key"]) and field["key"] not in ("heading", "page_title")
                and field_active(current, field, card["fields"]) for row in _rows_of(field, card["fields"][field["key"]])]
        heading = card["fields"].get("heading") or card["fields"].get("page_title")  # 페이지 제목은 자유 구성의 카드 제목으로
        fields = _free_fields(target, heading or (card.get("role") or current["label"])[:16], rows,
                              card["fields"].get("lead", ""), card["fields"].get("notes", []))
        return {"fields": fields, "missing": []}
    by_label = {r["label"]: r["value"] for r in card["fields"].get("points") or []}
    raw = {}
    if card.get("convertedFrom") == template_id:
        raw.update(_items_from_rows(target, card["fields"]))
    for field in target["fields"]:
        if card["fields"].get(field["key"]):
            raw[field["key"]] = card["fields"][field["key"]]
        elif field["type"] in ("text", "multiline") and field["label"][:8] in by_label:
            raw[field["key"]] = by_label[field["label"][:8]]
    fields = clean_fields(target, raw)
    fields = fields if not _missing_required(target, fields) else (_fit_choice(target, fields) or fields)
    missing = [f["label"] + (f" {f['minItems']}개 이상" if f.get("minItems") else "") for f in _missing_required(target, fields)]
    if target.get("pickWithoutData"):
        missing = []  # 사용자가 직접 입력할 카드: 빈 칸으로 열고, 필수 항목을 채우기 전에는 승인할 수 없습니다
    return {"fields": fields, "missing": missing}


def _items_from_rows(target: dict, free_fields: dict) -> dict:
    """자유 구성으로 바뀌었던 친구 카드를 되돌릴 때: 정보 줄(이름 · 관계)과 소개 문장(TMI)을 친구 항목으로 다시 옮깁니다."""
    result = {}
    for field in target["fields"]:
        if field.get("type") != "items" or not field.get("slotPrefix") or not field_active(target, field, {}):
            continue  # 기본 카테고리(친구) 목록으로만 되돌립니다
        rows = [r for r in free_fields.get("points") or [] if r.get("label")]
        items = [{"name": r["label"], "relation": r["value"] if r["value"] != r["label"] else "", "tmi": ""} for r in rows[: field["maxItems"]]]
        if len(items) == 1 and free_fields.get("lead"):
            items[0]["tmi"] = free_fields["lead"]
        result[field["key"]] = items
    return result


def clean_card(job: dict, raw: dict, source_ids: set[str]) -> dict:
    frame = raw["frame"]
    tpl = template_for(job, frame)
    if is_flexible(job) and frame != FRAMES[0] and raw.get("template") in body_choices(job["contentType"]):
        tpl = TEMPLATES[raw["template"]]  # card-01(표지)은 고정, card-02 ~ card-05는 AI가 자료에 맞춰 고른 템플릿
    card = {
        "frame": frame, "template": tpl["id"], "role": _text(raw.get("role")),
        # 사용자만 입력하는 칸(userOnly, 예: 다음 편 캐릭터)은 AI가 쓴 값을 받지 않습니다 (조사로 알 수 없는 계획이라 지어내지 않게)
        "fields": clean_fields(tpl, {k: v for k, v in (raw.get("fields") or {}).items() if k not in USER_ONLY_KEYS}),
        "source": _text(raw.get("source")) if has_source(tpl) else "",
        "sourceIds": [i for i in raw.get("sourceIds", []) if i in source_ids],
    }
    return fit_template(job, card) if is_flexible(job) and frame != FRAMES[0] else card


def _rows_of(field: dict, value) -> list[dict]:
    """전용 템플릿 필드 값을 자유 구성의 정보 줄로 옮깁니다. 값을 새로 만들지 않고 있는 값만 옮깁니다."""
    label = field["label"][:8]
    if field["type"] in ("text", "multiline"):
        return [{"label": label, "value": " ".join(value.split())}]
    if field["type"] == "list":
        return [{"label": label, "value": " · ".join(value)}]
    if field["type"] == "pairs":
        return [{"label": p["label"][:8], "value": p["value"]} for p in value]
    if field["type"] == "items" and {f["key"] for f in field["fields"]} == {"label", "value"}:
        return [{"label": p["label"][:8], "value": p["value"]} for p in value if p.get("label") and p.get("value")]  # 프로필 줄은 그대로
    if field["type"] == "items":
        rows = []
        for item in value:
            # 짧은 값(이름·관계 등)은 한 줄로 잇고, 여러 줄 글(TMI·설명)은 같은 이름으로 따로 둡니다 (긴 글은 _free_fields가 소개 문장으로 옮김)
            short = [item.get(sub["key"], "") for sub in field["fields"] if sub["type"] == "text" and item.get(sub["key"])]
            long = [item.get(sub["key"], "") for sub in field["fields"] if sub["type"] == "multiline" and item.get(sub["key"])]
            if not short and not long:
                continue
            name = (short or long)[0][:8]
            rest = short[1:] if short else []
            if rest or not long:
                rows.append({"label": name, "value": " · ".join(rest) or name})
            rows += [{"label": name, "value": " ".join(text.split())} for text in long]
        return rows
    return []


def _free_fields(free: dict, heading: str, rows: list[dict], lead: str = "", notes: list | None = None) -> dict:
    """자유 구성 카드 값을 만듭니다. 정보 줄 칸보다 긴 글(예: 60자 TMI)은 비어 있는 소개 문장으로 옮기고, 자르거나 지어내지 않습니다."""
    points = next(f for f in free["fields"] if f["key"] == "points")
    lead_max = next((f["max"] for f in free["fields"] if f["key"] == "lead"), 0)
    rows = [r for r in rows if r["label"] and r["value"]]
    kept = []
    for row in rows:
        if len(row["value"]) > points["valueMax"] and not lead and len(row["value"]) <= lead_max:
            lead = row["value"]
        else:
            kept.append(row)
    return clean_fields(free, {"heading": heading, "lead": lead, "points": kept[:points["maxItems"]], "notes": notes or []})


def fit_template(job: dict, card: dict) -> dict:
    """본문 카드의 전용 템플릿에서 필수 칸이 비면 자유 구성 카드로 바꿉니다.

    빈 필수 칸 때문에 제작이 멈추거나, 빈 칸·자리표시가 카드에 남지 않게 합니다. 있는 값만 정보 줄로 옮기고 새 사실은 만들지 않습니다.
    """
    tpl = TEMPLATES[card["template"]]
    if tpl["id"].endswith(f"-{FREE}"):
        if not card["fields"].get("heading"):
            card["fields"]["heading"] = (card.get("role") or "한눈에 보기")[:16]
        return card
    if not _missing_required(tpl, card["fields"]):
        return card
    # 고른 카테고리의 인원이 부족해도 다른 카테고리(예: 가족)가 채워져 있으면 그쪽으로 바꿉니다 (자료를 섞지 않음)
    switched = _fit_choice(tpl, card["fields"])
    if switched is not None:
        return {**card, "fields": switched}
    free = TEMPLATES[free_id(job["contentType"])]
    rows = [row for field in tpl["fields"] if card["fields"].get(field["key"]) and field_active(tpl, field, card["fields"])
            for row in _rows_of(field, card["fields"][field["key"]])]
    fields = _free_fields(free, (card.get("role") or tpl["label"])[:16], rows)
    return {**card, "template": free["id"], "fields": fields, "convertedFrom": tpl["id"]}


def is_empty_card(card: dict) -> bool:
    """제목 말고는 내용이 없는 카드. 비어도 기본 안내 문구로 완성되는 카드(allowEmpty, 예: 다음 편 예고)는 빈 카드가 아닙니다."""
    if (TEMPLATES.get(card.get("template")) or {}).get("allowEmpty"):
        return False
    return not any(v for k, v in (card.get("fields") or {}).items() if k != "heading" and k not in CHOICE_KEYS and not isinstance(v, bool))


def _values_of(fields: dict) -> list[str]:
    """카드가 전하는 값들. 제목과 정보 줄의 항목 이름(가격, 판매처 등)은 빼고 값만 봅니다."""
    values = []
    for key, value in fields.items():
        if key == "heading" or key in CHOICE_KEYS or isinstance(value, bool):
            continue
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict):
                    values += [entry["value"]] if set(entry) == {"label", "value"} else [v for v in entry.values() if v]
                elif entry:
                    values.append(entry)
        elif value:
            values.append(value)
    return [v for v in values if len(re.sub(r"\s+", "", v)) >= 2]


def repeated_values(cards: list[dict]) -> dict[str, list[str]]:
    """본문 카드가 앞 카드의 정보를 되풀이하는지. 카드 값의 절반이 넘게 앞 카드에 이미 나온 값이면 표시합니다. {frame: [반복된 값]}

    상품명처럼 여러 카드에 자연스럽게 나오는 값 하나로는 표시하지 않고, 새 정보 없이 같은 정보만 다시 담은 카드를 찾습니다.
    """
    seen: set[str] = set()
    result: dict[str, list[str]] = {}
    for card in cards[1:]:
        values = _values_of(card.get("fields") or {})
        keys = [re.sub(r"\s+", "", v) for v in values]
        repeated = [v for v, k in zip(values, keys) if k in seen]
        if values and len(repeated) * 2 > len(values):
            result[card["frame"]] = repeated
        seen.update(keys)
    return result


# ---------- 이미지 자리 ----------
def slots_of(job: dict, frame: str) -> list[dict]:
    return template_for(job, frame)["images"]


def _get_path(fields: dict, path: str):
    value = fields
    for part in path.split("."):
        if isinstance(value, list) and part.isdigit():
            value = value[int(part)] if int(part) < len(value) else None
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def active_slots(job: dict, frame: str) -> list[dict]:
    """카드에 실제로 그려지는 이미지 자리. 친구가 2명이면 친구 3·4 이미지 자리는 빼서 추천이나 기본 배치에 쓰지 않습니다."""
    card = next((c for c in (job.get("outline") or {}).get("cards", []) if c.get("frame") == frame), None)
    tpl = template_for(job, frame)
    if card is None:
        return tpl["images"]
    return [s for s in tpl["images"] if condition_met(tpl, card.get("fields") or {}, s.get("if"))]


def remap_item_slots(tpl: dict, slots: dict, orders: dict) -> dict:
    """항목을 지우거나 순서를 바꿨을 때 항목별 이미지(친구 1 이미지 …)가 그 항목을 따라가게 합니다.

    orders: {필드 이름: [저장 전 항목 번호(0부터) 또는 -1(새 항목)]}
    """
    result = dict(slots)
    for field in tpl["fields"]:
        prefix, order = field.get("slotPrefix"), orders.get(field["key"])
        if not prefix or order is None:
            continue
        old = {i: slots.get(f"{prefix}{i + 1}") for i in range(field["maxItems"])}
        for j in range(field["maxItems"]):
            source = order[j] if j < len(order) else -1
            result[f"{prefix}{j + 1}"] = old.get(source) if source >= 0 else None
    return result


def default_slot_images(job: dict, permitted: list[dict]) -> dict:
    """이미지를 앞 카드부터 이미지 자리마다 한 장씩 넣습니다. 같은 이미지를 반복하지 않습니다."""
    images = {frame: {slot["key"]: None for slot in slots_of(job, frame)} for frame in FRAMES}
    queue = list(permitted)
    for frame in FRAMES:
        for slot in active_slots(job, frame):
            if queue and not slot.get("userOnly"):  # 사용자만 넣는 자리(예: 다음 캐릭터 이미지)는 채우지 않습니다
                images[frame][slot["key"]] = queue.pop(0)
    return images


def keep_user_fields(old: dict | None, new: dict) -> dict:
    """AI나 데모가 카드를 다시 써도 사용자만 입력하는 칸(userOnly, 예: 다음 캐릭터 이름·힌트·회차)은 그대로 둡니다."""
    if not old or old.get("template") != new.get("template") or new.get("template") not in TEMPLATES:
        return new
    keys = [f["key"] for f in TEMPLATES[new["template"]]["fields"] if f.get("userOnly")]
    if not keys:
        return new
    kept = {k: (old.get("fields") or {}).get(k, (new.get("fields") or {}).get(k)) for k in keys}
    return {**new, "fields": {**(new.get("fields") or {}), **kept}}


def next_teaser(tpl: dict) -> dict | None:
    """다음 캐릭터 예고 카드의 칸 이름과 기본 문구. {"name", "hint", "reveal", "hintDefault", "revealDefault"}"""
    spec = tpl.get("nextTeaser")
    if not spec:
        return None
    fields = {f["key"]: f for f in tpl["fields"]}
    return {**spec, "hintDefault": fields[spec["hint"]]["placeholder"], "revealDefault": fields[spec["reveal"]]["placeholder"]}


def upgrade_card(card: dict) -> str | None:
    """예전 판으로 열어야 하는 카드면 그 템플릿 id를 돌려줍니다 (예: 공통 TMI가 있는 친구와 TMI 카드)."""
    old = OLD_VERSIONS.get(card.get("template"))
    if old and old["old_key"] in (card.get("fields") or {}) and old["id"] in TEMPLATES:
        return old["id"]
    return None


def build_spec(job: dict, card: dict, images: dict | None) -> dict:
    """렌더러에 넘길 카드 명세. 디자인은 템플릿이 정하고, 바뀌는 것은 문구와 이미지뿐입니다."""
    index = FRAMES.index(card["frame"])
    tpl = template_for(job, card["frame"])
    legacy = tpl.get("legacy", False)
    cover = next((c for c in (job.get("outline") or {}).get("cards", []) if c["frame"] == FRAMES[0]), None)
    inherited = {key: ((cover or {}).get("fields") or {}).get(key, "") for key in tpl.get("inherit", [])}
    return {
        "version": FORMAT, "frame": card["frame"], "template": tpl["id"], "page": index + 1, "total": len(FRAMES),
        "no": f"{index:02d}" if legacy and tpl["kind"] == "body" else "",
        "fields": {**inherited, **card["fields"]}, "source": card.get("source", ""),
        "images": {slot["key"]: (images or {}).get(slot["key"]) for slot in tpl["images"]},
    }


def missing_required_images(job: dict) -> list[str]:
    missing = []
    for frame in FRAMES:
        for slot in slots_of(job, frame):
            if slot.get("required") and not ((job.get("slotImages") or {}).get(frame) or {}).get(slot["key"]):
                missing.append(f"{frame} {slot['label']}")
    return missing


# ---------- AI 출력 형식과 규칙 ----------
def _field_schema(field: dict) -> dict:
    if field["type"] == "flag":
        return {"type": "boolean"}
    if field["type"] == "choice":
        return {"type": "string", "enum": [o["value"] for o in field["options"]]}
    if field["type"] in ("text", "multiline"):
        return {"type": "string"}
    if field["type"] == "list":
        return {"type": "array", "items": {"type": "string"}}
    if field["type"] == "items":
        props = {sub["key"]: {"type": "string"} for sub in field["fields"]}
        return {"type": "array", "items": {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}}
    return {"type": "array", "items": {"type": "object", "properties": {"label": {"type": "string"}, "value": {"type": "string"}},
                                       "required": ["label", "value"], "additionalProperties": False}}


def _set_templates(content_type: str, ids: list[str] | None = None) -> list[dict]:
    return [TEMPLATES[i] for i in (ids or template_set(content_type) or LEGACY_SET[content_type])]


def ai_card_schema(content_type: str, ids: list[str] | None = None) -> dict:
    props = {}
    chosen = [TEMPLATES[f"{content_type}-01"]] + [TEMPLATES[i] for i in body_choices(content_type)] if _flexible_ids(content_type, ids) else _set_templates(content_type, ids)
    for tpl in chosen:
        for field in tpl["fields"]:
            if not field.get("userOnly"):
                props.setdefault(field["key"], _field_schema(field))
    return {
        "type": "object",
        "properties": {
            "frame": {"type": "string", "enum": FRAMES}, "role": {"type": "string"}, "template": {"type": "string"},
            "fields": {"type": "object", "properties": props, "additionalProperties": False},
            "source": {"type": "string"}, "sourceIds": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["frame", "role", "template", "fields", "source", "sourceIds"],
        "additionalProperties": False,
    }


def _describe(field: dict) -> str:
    kind = field["type"]
    if kind == "flag":
        return f"  - {field['key']} ({field['label']}): true 또는 false. 출처로 확인된 경우에만 true{'. ' + field['hint'] if field.get('hint') else ''}"
    if kind == "choice":
        options = ", ".join(f"{o['value']}({o['label']})" for o in field["options"])
        return f"  - {field['key']} ({field['label']}): {options} 중 하나. 기본값 {field['default']}{'. ' + field['hint'] if field.get('hint') else ''}"
    when = ""
    if field.get("if"):
        when = " 카드에는 " + " 그리고 ".join(_conditions(field["if"])) + "일 때만 보인다."
    if kind == "text":
        rule = f"문자열, {field['max']}자 이내, 줄바꿈 없음"
    elif kind == "multiline":
        rule = f"문자열, {field['max']}자 이내, 최대 {MULTILINE_MAX_LINES}줄"
    elif kind == "list":
        rule = f"문자열 배열, 최대 {field['maxItems']}개, 각 {field['itemMax']}자 이내"
    elif kind == "items":
        subs = ", ".join(f"{s['key']}({s['label']}, {s['max']}자{', 필수' if s.get('required') else ''}"
                         f"{', 기본값 ' + s['default'] if s.get('default') else ''})" for s in field["fields"])
        count = f"{field['minItems']}~{field['maxItems']}개" if field.get("minItems") else f"최대 {field['maxItems']}개"
        rule = f"객체 배열, {count}: {subs}"
    else:
        labels = ", ".join(field.get("defaultLabels", []))
        rule = (f"[{{label, value}}] 최대 {field['maxItems']}개, label {field['labelMax']}자·value {field['valueMax']}자 이내"
                + (f". 기본 label: {labels}" if labels else ""))
    need = "필수" if field.get("required") else "선택, 확인되지 않으면 비운다"
    default = f". 기본값: {field['default']}" if field.get("default") else ""
    hint = f". {field['hint']}" if field.get("hint") else ""
    return f"  - {field['key']} ({field['label']}): {rule}. {need}{default}{hint}{when}"


def _flexible_ids(content_type: str, ids: list[str] | None) -> bool:
    """새 형식(유형별 5장) 작업이면 카드마다 템플릿을 고릅니다. 예전 형식 3(표지 + 본문 반복)은 그대로입니다."""
    return bool(ids) and ids[0] == f"{content_type}-01" and free_id(content_type) in TEMPLATES


def ai_flexible_rules(content_type: str) -> str:
    """card-01은 표지로 고정하고, card-02 ~ card-05는 확보된 자료에 맞춰 템플릿과 주제를 고르게 합니다."""
    cover = TEMPLATES[f"{content_type}-01"]
    lines = ["[카드 형식: 고정 디자인, 유연한 구성]",
             "디자인은 템플릿이 정한다. 카드마다 template에 템플릿 id를 적고 그 템플릿의 fields만 채운다. 글자 수는 공백 포함이며 직접 세어 확인한다.",
             f"card-01 (표지, template은 {cover['id']}로 고정) fields, source는 빈 문자열:"]
    lines += [_describe(f) for f in cover["fields"]]
    lines.append("card-02 ~ card-05: 아래 템플릿 중 확인된 자료에 가장 맞는 것을 고른다. source는 30자 이내, 반드시 '출처: '로 시작.")
    for tid in body_choices(content_type):
        tpl = TEMPLATES[tid]
        required = [f["label"] for f in tpl["fields"] if f.get("required")]
        purpose = tpl.get("purpose") or f"{tpl['label']} 카드"
        need = f" 필수: {', '.join(required)}가 확인될 때만 고른다." if required and not tid.endswith(f"-{FREE}") else ""
        minimum = [f"{f['label']} {f['minItems']}개" for f in tpl["fields"] if f.get("minItems")]
        if minimum and not tid.endswith(f"-{FREE}"):
            # 카테고리별 목록(친구/가족)은 그중 하나만 채워져도 됩니다
            joined = " 또는 ".join(minimum) if all(f.get("if") for f in tpl["fields"] if f.get("minItems")) else ", ".join(minimum)
            need += f" 확인된 {joined} 이상일 때만 고르고, 부족하면 자유 구성을 쓴다."
        lines.append(f"- {tid} ({tpl['label']}): {purpose}{need}")
        lines += ["  " + _describe(f) for f in tpl["fields"] if not f.get("userOnly")]
        if any(f.get("userOnly") for f in tpl["fields"]):
            lines.append("    (이 카드의 다음 편 정보는 사용자가 구성안에서 직접 입력한다. fields는 빈 객체로 두고 role과 template만 쓴다)")
    lines += [
        "- 확보된 자료에 따라 카드별 주제를 정한다. 예: 굿즈라면 라인업, 상품별 특징과 구성, 가격과 구매 방법, 구매 전 참고 사항.",
        "- 출시일, 판매 시작 시각, 크기, 소재 같은 선택 정보가 없다는 이유로 status를 insufficient로 하지 않는다. 그 칸은 비우거나 다른 확인된 정보로 카드를 구성한다.",
        "- 전용 템플릿의 필수 정보가 없으면 그 템플릿 대신 자유 구성(free)을 쓴다. 자유 구성은 여러 장에 써도 된다.",
        "- 같은 정보를 표현만 바꿔 여러 카드에 반복하지 않는다. 카드마다 다른 확인된 정보를 담는다.",
        "- 확인되지 않은 가격, 날짜, 판매 기간, 특징을 만들지 않는다. 채울 정보가 없는 칸은 빈 문자열이나 빈 배열로 둔다.",
        "- 대괄호 자리표시([이름] 등), MM·DD·YYYY 같은 틀 문자는 쓰지 않는다.",
        "- role: 10자 이내로 그 카드의 주제를 적는다 (예: 표지, 라인업, 가격·구매).",
    ]
    return "\n".join(lines)


def ai_field_rules(content_type: str, ids: list[str] | None = None) -> str:
    if _flexible_ids(content_type, ids):
        return ai_flexible_rules(content_type)
    lines = ["[카드 형식: 고정 템플릿]", "디자인은 정해져 있다. 각 카드의 fields만 채운다. 글자 수는 공백 포함이며 직접 세어 확인한다."]
    for frame, tpl in zip(FRAMES, _set_templates(content_type, ids)):
        source = "source는 빈 문자열" if not has_source(tpl) else "source는 30자 이내, 반드시 '출처: '로 시작"
        lines.append(f"{frame} ({tpl['label']}) fields, {source}:")
        lines += [_describe(f) for f in tpl["fields"] if not f.get("userOnly")] or ["  - 채울 필드 없음 (사용자가 구성안에서 입력하는 카드)"]
    lines += ["- 대괄호 자리표시([이름] 등), MM·DD·YYYY 같은 틀 문자는 쓰지 않는다. 모르는 값은 빈 문자열이나 빈 배열로 둔다.",
              "- role: 10자 이내 (예: 표지, 프로필, 마무리)."]
    return "\n".join(lines)


# ---------- 데모 ----------
def _demo_text(field: dict, variant: int) -> str:
    """예시임을 밝히는 문구. 사실 정보(이름, 날짜, 가격 등)를 만들지 않습니다."""
    if "demo" in field:
        return field["demo"]
    if field.get("default"):
        return field["default"]
    options = [f"예시 {field['label']}", "데모 문구예요", "실제 정보 아님"]
    text = options[variant % len(options)]
    return text[: field["max"]] if len(text) > field["max"] else text


def _demo_value(field: dict, variant: int):
    kind = field["type"]
    if field.get("userOnly"):
        return ""  # 사용자가 입력하는 칸: 비워 두면 카드에 기본 안내 문구가 나옵니다
    if kind == "flag":
        return False  # 데모는 신상품 같은 사실을 주장하지 않습니다
    if kind == "choice":
        return field["default"]
    if kind in ("text", "multiline"):
        return _demo_text(field, variant)
    if kind == "list":
        return ["예시", "데모"][: field["maxItems"]]
    if kind == "items":
        count = field.get("defaultItems") or min(field["maxItems"], 2 + variant % 2)
        return [{sub["key"]: _demo_text(sub, variant + n) for sub in field["fields"]} for n in range(count)]
    return [{"label": label, "value": "예시 값"} for label in field.get("defaultLabels", [])[:2]]


def demo_card(job: dict, frame: str, variant: int) -> dict:
    tpl = template_for(job, frame)
    fields = {f["key"]: _demo_value(f, variant) for f in tpl["fields"]}
    # 카드에 보이지 않는 목록(다른 카테고리)은 예시로 채우지 않습니다
    fields = {k: (v if field_active(tpl, f, fields) else ([] if isinstance(v, list) else v)) for f in tpl["fields"] for k, v in [(f["key"], fields[f["key"]])]}
    return {"frame": frame, "template": tpl["id"], "role": tpl["label"][:10], "fields": clean_fields(tpl, fields),
            "source": DEMO_SOURCE if has_source(tpl) else "", "sourceIds": []}


def public_templates() -> dict:
    """화면에 보내는 템플릿 정의 (참고 이미지 경로와 비교용 예시 제외)."""
    return {tid: {k: v for k, v in tpl.items() if k not in ("reference", "sample")} for tid, tpl in TEMPLATES.items()}

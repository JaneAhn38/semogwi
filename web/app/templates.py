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
FIELD_TYPES = {"text", "multiline", "list", "items", "pairs", "flag"}
ITEM_FIELD_TYPES = {"text", "multiline"}
ELEMENT_TYPES = {"header", "footer", "rect", "circle", "line", "text", "image", "rows", "chips", "pill", "bullets", "check", "asset", "star"}
MULTILINE_MAX_LINES = 2
DEMO_SOURCE = "출처: 데모 (실제 출처 아님)"
LEGACY_SET = {"character": ["character-cover"] + ["character-body"] * 4}  # 예전 형식 3 작업

# PNG에 자리표시 문구가 남지 않게 합니다: [캐릭터 이름], MM월 DD일, YYYY.MM.DD 같은 틀.
# 한글이 바로 붙어도 잡히도록 \b 대신 영문자 경계를 씁니다 ("MM월"). 실제 시각일 수 있는 00:00은 대괄호 안일 때만 잡습니다.
PLACEHOLDER_RE = re.compile(r"\[[^\[\]\n]{1,40}\]|(?<![A-Za-z])(?:YYYY|MM|DD)(?![A-Za-z])")
_TOKEN_RE = re.compile(r"\{([\w.]+)\}")
_RESERVED_TOKENS = {"page", "total", "no", "source", "source_text"}


class TemplateError(ValueError):
    """템플릿 파일 자체가 잘못된 경우. 서버 시작 때 드러나도록 합니다."""


def has_source(tpl: dict) -> bool:
    """출처를 표시하는 카드인지. 표지에는 출처를 두지 않습니다."""
    return tpl["kind"] != "cover"


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
        fields[field["key"]] = field
    # inherit: 표지(card-01)의 값을 그대로 보여 주는 필드 (예: 브랜드명). 이 카드에서는 고치지 않습니다
    for key in tpl.get("inherit", []):
        if key in fields:
            raise TemplateError(f"{name}: {key}는 물려받는 필드라 직접 정의할 수 없어요")
        fields[key] = {"key": key, "type": "text"}
    slots = {image["key"] for image in tpl["images"]}
    for el in tpl["elements"]:
        kind = el.get("type")
        if kind not in ELEMENT_TYPES:
            raise TemplateError(f"{name}: 알 수 없는 요소 {kind}")
        paths = [el.get("field"), el.get("if")] + [item["field"] for item in el.get("items", [])]
        for path in filter(None, paths):
            if not _path_ok(path, fields):
                raise TemplateError(f"{name}: 없는 필드를 써요 ({path})")
        if kind == "image" and el.get("slot") not in slots:
            raise TemplateError(f"{name}: 없는 이미지 자리를 그려요 ({el.get('slot')})")
        for text in [el.get("text"), el.get("left"), el.get("tag")] + el.get("parts", []):
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
            _check_set(content_type, ids, templates)
            cover_keys = {f["key"] for f in templates[ids[0]]["fields"]}
            for tid in ids[1:]:
                missing = set(templates[tid].get("inherit", [])) - cover_keys
                if missing:
                    raise TemplateError(f"{tid}: 표지에 없는 필드를 물려받아요 ({', '.join(sorted(missing))})")
    return templates


TEMPLATES = load_all()


def template_set(content_type: str) -> list[str] | None:
    """card-01 ~ card-05에 쓸 템플릿 id. 다섯 장이 모두 있어야 씁니다."""
    ids = [f"{content_type}-0{i}" for i in range(1, 6)]
    return ids if all(i in TEMPLATES for i in ids) else None


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
        if field.get("required") and not value:
            errors.append(f"{label}: 꼭 필요한 항목이에요. 확인된 내용을 입력해 주세요")
            continue
        if not value or kind == "flag":
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
    return {c["frame"]: check_card(c, template_for(job, c["frame"])) for c in cards}


def clean_card(job: dict, raw: dict, source_ids: set[str]) -> dict:
    frame = raw["frame"]
    tpl = template_for(job, frame)
    return {
        "frame": frame, "template": tpl["id"], "role": _text(raw.get("role")),
        "fields": clean_fields(tpl, raw.get("fields")),
        "source": _text(raw.get("source")) if has_source(tpl) else "",
        "sourceIds": [i for i in raw.get("sourceIds", []) if i in source_ids],
    }


# ---------- 이미지 자리 ----------
def slots_of(job: dict, frame: str) -> list[dict]:
    return template_for(job, frame)["images"]


def default_slot_images(job: dict, permitted: list[dict]) -> dict:
    """허가된 이미지를 앞 카드부터 이미지 자리마다 한 장씩 넣습니다. 같은 이미지를 반복하지 않습니다."""
    images = {frame: {slot["key"]: None for slot in slots_of(job, frame)} for frame in FRAMES}
    queue = list(permitted)
    for frame in FRAMES:
        for slot in slots_of(job, frame):
            if queue:
                images[frame][slot["key"]] = queue.pop(0)
    return images


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
    for tpl in _set_templates(content_type, ids):
        for field in tpl["fields"]:
            props.setdefault(field["key"], _field_schema(field))
    return {
        "type": "object",
        "properties": {
            "frame": {"type": "string", "enum": FRAMES}, "role": {"type": "string"},
            "fields": {"type": "object", "properties": props, "additionalProperties": False},
            "source": {"type": "string"}, "sourceIds": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["frame", "role", "fields", "source", "sourceIds"],
        "additionalProperties": False,
    }


def _describe(field: dict) -> str:
    kind = field["type"]
    if kind == "flag":
        return f"  - {field['key']} ({field['label']}): true 또는 false. 출처로 확인된 경우에만 true{'. ' + field['hint'] if field.get('hint') else ''}"
    if kind == "text":
        rule = f"문자열, {field['max']}자 이내, 줄바꿈 없음"
    elif kind == "multiline":
        rule = f"문자열, {field['max']}자 이내, 최대 {MULTILINE_MAX_LINES}줄"
    elif kind == "list":
        rule = f"문자열 배열, 최대 {field['maxItems']}개, 각 {field['itemMax']}자 이내"
    elif kind == "items":
        subs = ", ".join(f"{s['key']}({s['label']}, {s['max']}자{', 필수' if s.get('required') else ''}"
                         f"{', 기본값 ' + s['default'] if s.get('default') else ''})" for s in field["fields"])
        rule = f"객체 배열, 최대 {field['maxItems']}개: {subs}"
    else:
        labels = ", ".join(field.get("defaultLabels", []))
        rule = (f"[{{label, value}}] 최대 {field['maxItems']}개, label {field['labelMax']}자·value {field['valueMax']}자 이내"
                + (f". 기본 label: {labels}" if labels else ""))
    need = "필수" if field.get("required") else "선택, 확인되지 않으면 비운다"
    default = f". 기본값: {field['default']}" if field.get("default") else ""
    hint = f". {field['hint']}" if field.get("hint") else ""
    return f"  - {field['key']} ({field['label']}): {rule}. {need}{default}{hint}"


def ai_field_rules(content_type: str, ids: list[str] | None = None) -> str:
    lines = ["[카드 형식: 고정 템플릿]", "디자인은 정해져 있다. 각 카드의 fields만 채운다. 글자 수는 공백 포함이며 직접 세어 확인한다."]
    for frame, tpl in zip(FRAMES, _set_templates(content_type, ids)):
        source = "source는 빈 문자열" if not has_source(tpl) else "source는 30자 이내, 반드시 '출처: '로 시작"
        lines.append(f"{frame} ({tpl['label']}) fields, {source}:")
        lines += [_describe(f) for f in tpl["fields"]] or ["  - 채울 필드 없음"]
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
    if kind == "flag":
        return False  # 데모는 신상품 같은 사실을 주장하지 않습니다
    if kind in ("text", "multiline"):
        return _demo_text(field, variant)
    if kind == "list":
        return ["예시", "데모"][: field["maxItems"]]
    if kind == "items":
        count = min(field["maxItems"], 2 + variant % 2)
        return [{sub["key"]: _demo_text(sub, variant + n) for sub in field["fields"]} for n in range(count)]
    return [{"label": label, "value": "예시 값"} for label in field.get("defaultLabels", [])[:2]]


def demo_card(job: dict, frame: str, variant: int) -> dict:
    tpl = template_for(job, frame)
    fields = {f["key"]: _demo_value(f, variant) for f in tpl["fields"]}
    return {"frame": frame, "template": tpl["id"], "role": tpl["label"][:10], "fields": clean_fields(tpl, fields),
            "source": DEMO_SOURCE if has_source(tpl) else "", "sourceIds": []}


def public_templates() -> dict:
    """화면에 보내는 템플릿 정의 (참고 이미지 경로와 비교용 예시 제외)."""
    return {tid: {k: v for k, v in tpl.items() if k not in ("reference", "sample")} for tid, tpl in TEMPLATES.items()}

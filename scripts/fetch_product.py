r"""
세모귀 카드뉴스 - 공식 상품 URL 가져오기 (fetch_product.py)

공식 쇼핑몰 상품 URL에서 상품 정보와 상품 이미지를 가져와 analyze-image가 읽을 수 있게 저장합니다.
표준 라이브러리만 사용합니다 (이미지 크기 판별은 fill_figma.py의 image_info를 재사용).

[사용법]
    py scripts/fetch_product.py <공식 상품 URL> <프로젝트 폴더>

    예) py scripts/fetch_product.py https://chiikawamarket.jp/ko/products/4595559353951 projects/2026-11-03_코인실린더

[저장하는 것]
    <프로젝트 폴더>/product.json     상품 정보·이미지 목록·가격 확인 결과·사용 허가 상태 (기계용)
    <프로젝트 폴더>/product-info.md  같은 내용을 사람이 읽기 좋게 정리 (analyze-image가 읽음)
    <프로젝트 폴더>/input/NN_*.jpg   상품 이미지 (중복 제거). projects/*/input/은 .gitignore로 제외됩니다.

[동작]
    - 공식 도메인(OFFICIAL_HOSTS)의 /products/<상품> 주소만 받습니다. 다른 주소는 요청하지 않고 종료합니다.
    - 요청은 상품 JSON 1회, 상품 페이지 1회, 이미지마다 1회만 보냅니다. 429(요청 과다)는 Retry-After(최대 60초)만큼
      기다렸다가 한 번만 다시 시도합니다.
    - 가격은 JSON 값과 페이지에 표시된 문구(예: "¥440 (세금 포함)")가 일치할 때만 '확인됨'으로 기록합니다.
    - 같은 내용의 이미지(md5 동일)는 한 장만 저장하고 나머지는 중복으로 기록합니다.
    - 이미 product.json이 있거나 input/에 파일이 있으면 덮어쓰지 않고 종료합니다.
    - 상품 이미지는 '분석용'으로만 허가된 상태로 기록합니다. 카드뉴스 이미지로 쓰려면 사용자 승인이 따로 필요합니다.

[종료 코드]
    0: 성공 (일부 이미지 실패는 경고로 기록)  1: 입력·접근 오류로 아무것도 저장하지 않음  2: 이미 저장된 결과가 있음
    3: 상품 정보는 저장했지만 이미지를 한 장도 받지 못함

    프로젝트 루트(semogwi)에서 실행합니다.
"""

import argparse
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fill_figma import image_info  # noqa: E402

# --- 허용 범위 ---
OFFICIAL_HOSTS = {"chiikawamarket.jp"}           # 공식 상품 페이지로 인정하는 쇼핑몰
IMAGE_HOSTS = {"cdn.shopify.com", "chiikawamarket.jp"}  # 상품 이미지를 받을 수 있는 주소
PRODUCT_PATH = re.compile(r"(/[a-z]{2}(?:-[a-z]{2,4})?)?/products/([A-Za-z0-9._%-]+)/?")

USER_AGENT = "Mozilla/5.0 (semogwi fetch_product)"
TIMEOUT = 20
MAX_RETRY_AFTER = 60
MAX_IMAGES = 20
KST = timezone(timedelta(hours=9))

USAGE = {
    "analysis": "허가됨 — 공식 상품 페이지 이미지를 상품 확인·분석용으로만 사용",
    "card_image": "미승인 — 카드뉴스 이미지로 쓰려면 사용자 승인 후 cutout-image가 sources.md에 기록",
}


class FetchError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 접근 오류."""


# ---------------------------------------------------------------------------
# URL 확인
# ---------------------------------------------------------------------------
def parse_product_url(url: str):
    """공식 상품 URL이면 (기준 주소, 언어 경로, 상품 핸들)을 반환합니다."""
    u = urllib.parse.urlparse(url.strip())
    if u.scheme != "https":
        raise FetchError(f"https 주소가 아닙니다: {url}")
    host = (u.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in OFFICIAL_HOSTS:
        raise FetchError(f"공식 쇼핑몰 주소가 아닙니다 ({host}). 허용: {', '.join(sorted(OFFICIAL_HOSTS))}")
    m = PRODUCT_PATH.fullmatch(u.path)
    if not m:
        raise FetchError(f"상품 페이지 주소(/products/<상품>)가 아닙니다: {u.path}")
    return f"https://{host}", m.group(1) or "", m.group(2)


# ---------------------------------------------------------------------------
# 요청
# ---------------------------------------------------------------------------
def http_get(url: str, what: str, allowed_hosts):
    """한 번 요청합니다. 429면 Retry-After만큼 기다렸다가 한 번만 다시 시도합니다."""
    for attempt in (1, 2):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
                final_host = (urllib.parse.urlparse(res.geturl()).hostname or "").lower().removeprefix("www.")
                if final_host not in allowed_hosts:
                    raise FetchError(f"{what}: 허용되지 않은 주소로 이동했습니다 ({final_host})")
                return res.read(), res.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 1:
                wait = e.headers.get("Retry-After", "")
                wait = int(wait) if wait.isdigit() else MAX_RETRY_AFTER
                if wait > MAX_RETRY_AFTER:
                    raise FetchError(f"{what}: 요청이 너무 많다고 합니다 (429). {wait}초 뒤에 다시 실행해 주세요")
                print(f"[안내] {what}: 429(요청 과다) — {wait}초 기다렸다가 한 번 다시 시도합니다")
                time.sleep(wait)
                continue
            reason = {404: "페이지가 없습니다 (판매 종료·주소 오류)", 403: "접근이 거부되었습니다",
                      429: "요청이 너무 많습니다. 잠시 뒤 다시 실행해 주세요"}.get(e.code, "서버 오류")
            raise FetchError(f"{what}: HTTP {e.code} — {reason}")
        except urllib.error.URLError as e:
            raise FetchError(f"{what}: 연결하지 못했습니다 — {e.reason}")
        except TimeoutError:
            raise FetchError(f"{what}: {TIMEOUT}초 안에 응답이 없습니다")
    raise FetchError(f"{what}: 다시 시도했지만 실패했습니다")


# ---------------------------------------------------------------------------
# 페이지에서 표시 가격·저작권 찾기
# ---------------------------------------------------------------------------
def displayed_prices(page: str):
    """가격 칸(price-item)에 표시된 '¥440 (세금 포함)' 형태의 문구를 모읍니다."""
    found = []
    # 예: <span class="price-item ...">¥440<span class="tax">(세금 포함)</span>
    for m in re.finditer(r'class="price-item[^"]*"[^>]*>\s*([¥￥]\s?[\d,]+)\s*(?:<span[^>]*>)?\s*(\([^)<]*\))?', page):
        text = " ".join(x for x in (m.group(1).replace(" ", ""), (m.group(2) or "").strip()) if x)
        if text not in found:
            found.append(text)
    return found


def yen_value(text: str):
    m = re.search(r"[¥￥]\s?([\d,]+)", text)
    return int(m.group(1).replace(",", "")) if m else None


def copyright_text(page: str):
    m = re.search(r"(©[^<]{2,120})", page)
    return re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else ""


def plain_text(desc_html: str) -> str:
    t = re.sub(r"<br\s*/?>|</p>|</li>", "\n", desc_html or "", flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    lines = [ln.strip().replace("　", " ").strip() for ln in t.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# ---------------------------------------------------------------------------
# 저장
# ---------------------------------------------------------------------------
def write_markdown(path: Path, info: dict):
    o = info["official"]
    price = info["price"]
    rows = [
        ("O1", "상품명", o["title"], "상품 JSON `title`"),
        ("O2", "가격", price["display"] if price["status"] == "확인됨" else f"확인 필요 ({price['status']})",
         "상품 페이지 표시 문구 + JSON 일치" if price["status"] == "확인됨" else "-"),
        ("O3", "설명", o["description"].replace("\n", " / ") or "없음", "상품 JSON `description`"),
        ("O4", "상품 종류", o["type"] or "없음", "상품 JSON `type`"),
        ("O5", "브랜드·제조", o["vendor"] or "없음", "상품 JSON `vendor`"),
        ("O6", "쇼핑몰 태그", ", ".join(o["tags"]) or "없음", "상품 JSON `tags` (내부 분류)"),
        ("O7", "구매 가능 여부", f"{'구매 가능' if o['available'] else '구매 불가'} (확인 시각 기준)", "상품 JSON `available`"),
        ("O8", "저작권 표기", o["copyright"] or "없음", "상품 페이지"),
    ]
    lines = [
        f"# 공식 상품 정보: {o['title']}",
        "",
        f"- 상품 URL: {info['url']}",
        f"- 가져온 시각: {info['fetched_at']}",
        f"- 상품 JSON: {info['json_url']}",
        "- 이 파일은 `scripts/fetch_product.py`가 만들었다. 아래 O 항목은 공식 상품 페이지에서 그대로 가져온 `[공식]` 정보다.",
        "",
        "## 공식 상품 정보 [공식]",
        "| ID | 항목 | 값 | 출처 |",
        "| --- | --- | --- | --- |",
        *[f"| {a} | {b} | {c} | {d} |" for a, b, c, d in rows],
        "",
        "- 페이지 공개 시각(`published_at`)은 판매 시작일이 아니다. 판매 시작일 문구가 없으면 `[추정]`으로만 다룬다.",
        f"- 페이지 공개 시각: {o['published_at'] or '없음'}",
        "",
        "## 가격 확인",
        f"- 상태: **{price['status']}**",
        f"- 페이지 표시 문구: {', '.join(price['displayed']) or '없음'}",
        f"- JSON 값: {price['json_raw']} (Shopify 최소 단위 → {price['json_yen']}엔)",
        "",
        "## 상품 이미지 (input/)",
        "| 파일 | 형식·크기 | md5 | 원본 URL |",
        "| --- | --- | --- | --- |",
        *[f"| {i['file']} | {i['format']} {i['width']}×{i['height']} | {i['md5']} | {i['url']} |" for i in info["images"]],
    ]
    if info["duplicates"]:
        lines += ["", "### 중복으로 저장하지 않은 이미지",
                  *[f"- {d['url']} → {d['duplicate_of']}와 같음 (md5 {d['md5']})" for d in info["duplicates"]]]
    if info["failed_images"]:
        lines += ["", "### 받지 못한 이미지", *[f"- {f['url']}: {f['error']}" for f in info["failed_images"]]]
    lines += [
        "",
        "## 이미지 사용 허가",
        f"- 분석용: {info['usage']['analysis']}",
        f"- 카드뉴스 이미지: {info['usage']['card_image']}",
        "",
        "## 다음 단계",
        "- analyze-image가 이 파일과 input/ 이미지를 읽어 image-analysis.md를 만든다.",
        "- 이미지에 상품 정보로 명확하게 인쇄된 문구는 해당 이미지 URL을 출처로 `[공식]`, 그림을 보고 추론한 내용은 `[이미지]`·`[추정]`으로 나눈다.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="공식 상품 URL에서 상품 정보와 이미지를 가져옵니다")
    ap.add_argument("url")
    ap.add_argument("project")
    args = ap.parse_args()

    out = Path(args.project)
    input_dir = out / "input"
    if (out / "product.json").exists() or (input_dir.is_dir() and any(input_dir.iterdir())):
        print(f"[중단] {out}에 이미 가져온 결과가 있습니다 (product.json 또는 input/). 덮어쓰지 않습니다.")
        return 2

    try:
        base, lang, handle = parse_product_url(args.url)
        product_url = f"{base}{lang}/products/{handle}"
        json_url = product_url + ".js"
        raw, _ = http_get(json_url, "상품 JSON", OFFICIAL_HOSTS)
        try:
            p = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise FetchError("상품 JSON을 읽지 못했습니다 (상품 페이지 형식이 다릅니다)")
        if not p.get("title"):
            raise FetchError("상품 JSON에 상품명이 없습니다")
        page_bytes, _ = http_get(product_url, "상품 페이지", OFFICIAL_HOSTS)
        page = page_bytes.decode("utf-8", errors="replace")
    except FetchError as e:
        print(f"[오류] {e}")
        print("아무것도 저장하지 않았습니다.")
        return 1

    # 가격: JSON(최소 단위)과 페이지 표시 문구가 같을 때만 확인됨
    json_raw = p.get("price")
    json_yen = json_raw / 100 if isinstance(json_raw, (int, float)) else None
    shown = displayed_prices(page)
    match = [s for s in shown if json_yen is not None and yen_value(s) == json_yen]
    if match:
        price = {"status": "확인됨", "display": match[0]}
    elif shown:
        price = {"status": "불일치 (표시 문구와 JSON 값이 다름)", "display": ""}
    else:
        price = {"status": "표시 문구 없음", "display": ""}
    price.update({"displayed": shown, "json_raw": json_raw,
                  "json_yen": int(json_yen) if json_yen is not None and json_yen == int(json_yen) else json_yen})

    # 이미지: 주소 중복 → 내용(md5) 중복 순서로 거른다
    urls, seen_url = [], set()
    for u in p.get("images", []):
        full = "https:" + u if u.startswith("//") else u
        key = full.split("?")[0]
        if key not in seen_url:
            seen_url.add(key)
            urls.append(full)
    warnings = []
    if len(urls) > MAX_IMAGES:
        warnings.append(f"이미지가 {len(urls)}장이라 앞의 {MAX_IMAGES}장만 받습니다")
        urls = urls[:MAX_IMAGES]

    input_dir.mkdir(parents=True, exist_ok=True)
    images, duplicates, failed, by_md5 = [], [], [], {}
    for u in urls:
        name_part = Path(urllib.parse.urlparse(u).path).name
        try:
            data, ctype = http_get(u, f"이미지 {name_part}", IMAGE_HOSTS)
            if not ctype.startswith("image/"):
                raise FetchError(f"이미지가 아닙니다 ({ctype})")
        except FetchError as e:
            failed.append({"url": u, "error": str(e)})
            continue
        md5 = hashlib.md5(data).hexdigest()
        if md5 in by_md5:
            duplicates.append({"url": u, "md5": md5, "duplicate_of": by_md5[md5]})
            continue
        fname = f"{len(images) + 1:02d}_{name_part}"
        path = input_dir / fname
        with open(path, "xb") as fp:  # 같은 이름이 있으면 덮어쓰지 않고 오류
            fp.write(data)
        fmt, w, h = image_info(path)
        by_md5[md5] = fname
        images.append({"file": f"input/{fname}", "url": u, "md5": md5, "format": fmt, "width": w, "height": h,
                       "bytes": len(data)})

    info = {
        "url": product_url,
        "json_url": json_url,
        "fetched_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST"),
        "official": {
            "title": p.get("title", ""),
            "description": plain_text(p.get("description", "")),
            "type": p.get("type", ""),
            "vendor": p.get("vendor", ""),
            "tags": p.get("tags", []),
            "available": bool(p.get("available")),
            "published_at": p.get("published_at", ""),
            "handle": p.get("handle", handle),
            "barcode": next((v.get("barcode") for v in p.get("variants", []) if v.get("barcode")), ""),
            "copyright": copyright_text(page),
        },
        "price": price,
        "images": images,
        "duplicates": duplicates,
        "failed_images": failed,
        "warnings": warnings,
        "usage": USAGE,
    }
    (out / "product.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(out / "product-info.md", info)

    print(f"상품명: {info['official']['title']}")
    print(f"가격: {price['display'] or '-'} [{price['status']}]")
    print(f"이미지: 저장 {len(images)}장 / 중복 {len(duplicates)}장 / 실패 {len(failed)}장 → {input_dir}")
    for w in warnings + [f"이미지 실패: {f['url']} — {f['error']}" for f in failed]:
        print(f"[경고] {w}")
    print(f"저장: {out / 'product.json'}, {out / 'product-info.md'}")
    if not images:
        print("[오류] 상품 이미지를 한 장도 받지 못했습니다. 상품 정보만 저장했습니다.")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

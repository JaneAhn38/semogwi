"""공식 출처 없이 기사·위키 등 2차 자료만으로 4가지 콘텐츠 유형의 구성안을 만듭니다. Claude와 외부 사이트에 접속하지 않습니다."""

import pytest

from tests.test_research import client, clear_cooldowns, fake  # noqa: F401
from tests.test_templates import api, start, wait

USE_TEMPLATES = True
NEWS = "https://news.example/article"

# 유형마다 핵심 항목을 기사(2차 자료)에서만 찾은 경우
CORE = {
    "popup": [("popup_name", "세모귀 팝업"), ("period", "12.1 ~ 12.31"), ("place", "서울 성수동")],
    "goods": [("product_names", "세모귀 키링"), ("price", "1,500원")],
    "collab": [("partners", "세모귀 × 카페"), ("content", "콜라보 음료와 굿즈")],
    "character": [("official_name", "세모귀"), ("personality", "다정하고 호기심이 많아요")],
}


@pytest.mark.parametrize("content_type", ["popup", "goods", "collab", "character"])
def test_secondary_sources_alone_make_an_outline(client, fake, content_type):
    fake.sources = [{"id": "s1", "title": "기사", "url": NEWS, "kind": "secondary", "publishedAt": "2026-11-20"}]
    fake.fetches = [{"url": NEWS, "code": 200}]
    fake.items = [{"key": k, "value": v, "quote": v, "sourceIds": ["s1"]} for k, v in CORE[content_type]]
    job_id = start(client, mode="ai", contentType=content_type, topic="세모귀 소식", url=NEWS)
    job = wait(client, job_id, "waiting_outline", "waiting_material")
    assert job["state"] == "waiting_outline"  # 공식 확인이 없다고 자료 부족으로 멈추지 않음
    items = {i["key"]: i for i in job["research"]["items"]}
    for key, _ in CORE[content_type]:
        assert items[key]["state"] == "secondary"  # 출처 종류(2차 자료)는 그대로 기록
        assert items[key]["evidence"][0]["publishedAt"] == "2026-11-20" and items[key]["evidence"][0]["at"]  # 원문 게시일·조사일
    assert not job.get("researchGap", {}).get("rows") or all(r["key"] not in dict(CORE[content_type]) for r in job["researchGap"]["rows"])
    issues = job["outline"]["issues"]
    assert not any(i["errors"] for i in issues.values()), issues
    assert not any("공식" in w and "확인" in w for i in issues.values() for w in i["warnings"])  # '공식 확인 필요' 같은 문구 없음
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200

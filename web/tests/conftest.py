import os
import tempfile

# 어떤 테스트 파일을 따로 실행해도 실제 작업 폴더(web/data)를 건드리지 않도록, app을 불러오기 전에 임시 폴더를 지정합니다.
# (app.jobs·app.site_policy는 불러올 때 데이터 폴더를 정합니다)
os.environ["SEMOGWI_DATA_DIR"] = tempfile.mkdtemp(prefix="semogwi-test-")
os.environ.setdefault("SEMOGWI_DEMO_DELAY", "0")

import pytest  # noqa: E402

from app import templates  # noqa: E402


@pytest.fixture(autouse=True)
def _design_format(request, monkeypatch):
    """기존 테스트는 기존 방식(형식 1·2) 작업을 검사합니다. 고정 템플릿 테스트 파일은 USE_TEMPLATES = True로 켭니다."""
    if not getattr(request.module, "USE_TEMPLATES", False):
        monkeypatch.setattr(templates, "ENABLED_TYPES", set())


@pytest.fixture(autouse=True)
def _friend_pick(request, monkeypatch):
    """card-04 친구 고르기(2026-11-23)는 FRIEND_PICK = True인 테스트 파일에서만 켭니다.
    기존 테스트는 조사 → 구성안을 바로 이어서 검사합니다 (예전 흐름 그대로)."""
    if not getattr(request.module, "FRIEND_PICK", False):
        from app import friend_pick
        monkeypatch.setattr(friend_pick, "needed", lambda job: False)


@pytest.fixture(autouse=True)
def _no_preview_network(request, monkeypatch):
    """크루 후보 미리보기(2026-11-24)는 테스트에서 실제 사이트에 요청하지 않습니다. test_friend_preview.py는 가짜 응답으로 따로 검사합니다."""
    if not getattr(request.module, "PREVIEW_NETWORK", False):
        from app import friend_preview
        monkeypatch.setattr(friend_preview, "find_image", lambda fetcher, page, name: None)

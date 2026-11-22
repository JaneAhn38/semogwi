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

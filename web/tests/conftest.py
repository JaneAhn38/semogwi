import pytest

from app import templates


@pytest.fixture(autouse=True)
def _design_format(request, monkeypatch):
    """기존 테스트는 기존 방식(형식 1·2) 작업을 검사합니다. 고정 템플릿 테스트 파일은 USE_TEMPLATES = True로 켭니다."""
    if not getattr(request.module, "USE_TEMPLATES", False):
        monkeypatch.setattr(templates, "ENABLED_TYPES", set())

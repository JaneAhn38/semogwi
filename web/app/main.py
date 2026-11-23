"""세모귀 웹 (로컬 전용). 실행: run.bat 또는 uvicorn app.main:app --host 127.0.0.1 --port 8000
팀원 공유: share.bat + cloudflared (공개 주소는 접속 코드 확인, app/access.py 참고)

작업 파일을 다루는 라우트는 모두 async입니다. 이벤트 루프 하나에서 순서대로 처리해 job.json이 엉키지 않게 합니다.
"""

import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import asyncio

from . import access, claude_cli, cutout, detail_images, jobs, research_library, site_policy, templates
from .outline import CardEdit
from .provider import CONTENT_TYPES, DEFAULT_THEME, THEMES

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
TOPIC_MAX = 30
URL_MAX = 500
SOURCE_MAX = 100
MAX_IMAGES = 12  # 구성안에서 카드마다 이미지를 올릴 수 있어 넉넉히 둡니다 (캐릭터 템플릿 이미지 자리 7개)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
DESIGN_REQUEST_MAX = 200
RIGHTS = ("허가됨", "확인 필요", "허가 안 됨")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' blob: data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)

app = FastAPI(title="세모귀 웹", docs_url=None, redoc_url=None, openapi_url=None)
access.announce()


def _security_headers(response, csp: str = CSP):
    response.headers["Content-Security-Policy"] = csp
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _login_response(html: str, status_code: int = 200):
    # no-referrer 문서에서 보낸 양식 POST는 브라우저가 Origin을 null로 보내 출처 검사에 걸립니다. 접속 화면만 same-origin으로 둡니다
    response = _security_headers(HTMLResponse(html, status_code=status_code), access.LOGIN_CSP)
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


async def _access_gate(request: Request) -> Response | None:
    """Cloudflare Tunnel로 들어온 요청은 접속 코드를 확인합니다. 통과하면 None을 돌려줍니다."""
    path = request.url.path
    if path == access.LOGIN_PATH:
        if request.method == "POST":
            key = access.client_key(request)
            if access.locked(key):
                return _login_response(access.login_page("/", "시도가 너무 많아요. 10분 뒤에 다시 시도해 주세요."), 429)
            code, next_path = access.read_form(await request.body())
            if not access.check_code(code):
                access.record_failure(key)
                return _login_response(access.login_page(next_path, "접속 코드가 맞지 않아요."), 401)
            response = RedirectResponse(next_path, status_code=303)
            response.set_cookie(access.COOKIE, access._token(), max_age=access.COOKIE_MAX_AGE, httponly=True, secure=True, samesite="lax")
            return _security_headers(response)
        next_path = access.safe_next(request.query_params.get("next", "/"))
        return _login_response(access.login_page(next_path))
    if access.authorized(request.cookies):
        return None
    if path.startswith("/api/") or request.method not in ("GET", "HEAD"):
        return _security_headers(JSONResponse({"detail": "접속 코드를 먼저 입력해 주세요"}, status_code=401))
    target = path + (f"?{request.url.query}" if request.url.query else "")
    return _security_headers(RedirectResponse(f"{access.LOGIN_PATH}?{urlencode({'next': access.safe_next(target)})}", status_code=303))


@app.middleware("http")
async def local_only(request: Request, call_next):
    # 다른 사이트가 브라우저를 통해 이 서버를 호출하지 못하게 합니다 (DNS rebinding, CSRF 방지).
    # 로컬 주소는 그대로 받고, 공유 모드에서 허용한 공개 주소(Cloudflare Tunnel)만 접속 코드를 확인해 받습니다
    host = request.headers.get("host", "")
    hostname = access.hostname(host)
    local = access.is_local(hostname, request.headers)
    if not local and not (access.share_host(hostname) or (hostname in ALLOWED_HOSTS and access.SETTINGS.enabled)):
        return JSONResponse({"detail": "로컬 주소로만 접속할 수 있어요"}, status_code=403)
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD") and origin and urlparse(origin).netloc != host:
        return JSONResponse({"detail": "다른 사이트에서 보낸 요청은 받지 않아요"}, status_code=403)
    if not local:
        blocked = await _access_gate(request)
        if blocked is not None:
            return blocked
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        # 화면 파일은 매번 ETag로 새 버전인지 확인합니다. 헤더가 없으면 브라우저가 옛 renderer.js를 캐시에서 꺼내
        # 새 app.js와 섞어 실행할 수 있습니다 (renderTemplate is not a function).
        response.headers["Cache-Control"] = "no-cache"
    if not local:
        response.headers["Cache-Control"] = "private, no-store" if request.url.path.startswith("/api/") else "private, no-cache"
    return _security_headers(response)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InputBody(Strict):
    topic: str
    contentType: str
    url: str = ""
    notes: str = Field(default="", max_length=4000)  # 사용자가 직접 입력한 참고 자료
    notesKind: Literal["", "official", "namuwiki", "other"] = ""  # 참고 자료의 출처 종류 (공식을 골라도 공식 확인이 아님)
    notesUrl: str = Field(default="", max_length=URL_MAX)  # 참고 자료를 옮겨 온 주소 (자동으로 읽지 않음)
    mode: Literal["demo", "ai"] = "demo"
    researchMode: Literal["new", "saved"] = "new"  # 새로 조사하기 / 저장된 자료 사용
    researchVersion: str | None = Field(default=None, max_length=40)


class AssetPatch(Strict):
    rights: str | None = None
    source: str | None = None
    useVariant: Literal["original", "cutout"] | None = None


class CutoutBody(Strict):
    model: str = cutout.DEFAULT_MODEL


class CardImageBody(Strict):
    assetId: str | None
    variant: Literal["original", "cutout"] = "original"


class SlotAdjustBody(Strict):
    scale: float = Field(ge=jobs.SCALE_RANGE[0], le=jobs.SCALE_RANGE[1])
    dx: float = Field(ge=jobs.OFFSET_RANGE[0], le=jobs.OFFSET_RANGE[1])
    dy: float = Field(ge=jobs.OFFSET_RANGE[0], le=jobs.OFFSET_RANGE[1])


class SuggestionBody(Strict):
    frame: str | None = None
    slot: str | None = None


class DesignRequestBody(Strict):
    text: str = Field(min_length=1, max_length=DESIGN_REQUEST_MAX)


class MaterialSource(Strict):
    """자료 직접 입력의 출처 묶음 하나. kind는 사용자가 고른 표시일 뿐 공식 확인이 아닙니다."""
    url: str = Field(default="", max_length=URL_MAX)
    kind: str = Field(default="", pattern=r"^(|official|namuwiki|other)$")
    text: str = Field(default="", max_length=4000)


class MaterialBody(Strict):
    extra: str = Field(default="", max_length=3000)  # '추가로 알려주고 싶은 정보' (기본 자유 입력)
    sources: list[MaterialSource] = Field(default_factory=list, max_length=3)
    # 아래는 선택 입력 (세부 항목). 예전 화면과도 호환됩니다
    name: str = Field(default="", max_length=100)
    price: str = Field(default="", max_length=50)
    features: str = Field(default="", max_length=1000)
    seller: str = Field(default="", max_length=100)
    sourceUrl: str = Field(default="", max_length=URL_MAX)
    sourceKind: str = Field(default="", pattern=r"^(|official|namuwiki|other)$")
    pasted: str = Field(default="", max_length=8000)

    def has_content(self) -> bool:
        texts = [self.extra, self.name, self.price, self.features, self.seller, self.pasted] + [b.text for b in self.sources]
        return any(t.strip() for t in texts) or any(b.url for b in self.sources)


class RedesignBody(Strict):
    text: str = Field(default="", max_length=DESIGN_REQUEST_MAX)


class ContentTypeBody(Strict):
    contentType: str


class TemplateCardEdit(Strict):
    """고정 템플릿 카드 수정. 필드 값의 형식과 글자 수는 템플릿 정의로 jobs에서 검사합니다."""
    role: str = Field(max_length=50)
    fields: dict[str, bool | str | list[str] | list[dict[str, str]]]  # bool: 체크 항목(신상품 여부 등)
    source: str = Field(default="", max_length=200)
    # 항목을 지우거나 순서를 바꿨을 때 항목별 이미지가 따라가도록 저장 전 번호를 보냅니다 (예: {"friends": [0, 2]})
    itemOrder: dict[str, list[int]] | None = None
    # 예전 화면이 보내던 '확인 필요' 표시. 이제 쓰지 않습니다 (공식 확인을 제작 조건으로 두지 않음). 받기만 하고 버립니다
    checkMarks: list[str] = Field(default_factory=list, max_length=40)


def _detect_image(head: bytes) -> tuple[str, str] | None:
    """확장자가 아니라 파일 내용으로 형식을 확인합니다."""
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png", "image/png"
    if head[:3] == b"\xff\xd8\xff":
        return ".jpg", "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None


def _clean_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if len(url) > URL_MAX or parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "URL은 http:// 또는 https://로 시작하는 주소여야 해요")
    return url


def _check_input(topic: str, content_type: str, url: str, require_topic: bool = True) -> tuple[str, str, str]:
    topic = topic.strip()
    if require_topic and not topic:
        raise HTTPException(400, "주제를 입력해 주세요")
    if len(topic) > TOPIC_MAX:
        raise HTTPException(400, f"주제는 {TOPIC_MAX}자 이내로 입력해 주세요")
    if content_type not in CONTENT_TYPES and content_type != jobs.AUTO_TYPE:
        raise HTTPException(400, "콘텐츠 유형을 골라 주세요")
    return topic, content_type, _clean_url(url)


def _check_notes_source(kind: str, url: str) -> str:
    """참고 자료의 주소. 나무위키를 골랐으면 나무위키 주소만 받습니다 (미러 사이트는 원본이 아니라 받지 않음)."""
    url = _clean_url(url)
    if url and site_policy.mirror_site(url):
        raise HTTPException(400, "나무위키 미러 사이트 주소는 받지 않아요. 나무위키 원본 문서 주소를 적어 주세요")
    if kind == "namuwiki" and url and not site_policy.auxiliary_site(url):
        raise HTTPException(400, "출처 종류가 나무위키면 namu.wiki 주소를 적어 주세요")
    return url


def _check_rights(name: str, rights: str, source: str) -> str:
    source = source.strip()[:SOURCE_MAX]
    if rights not in RIGHTS:
        raise HTTPException(400, f"{name}: 사용 권한 값이 올바르지 않아요")
    if rights == "허가됨" and not source:
        raise HTTPException(400, f"{name}: 사용 권한이 '허가됨'이면 출처를 적어 주세요")
    return source


async def _read_image(upload: UploadFile) -> tuple[str, bytes, str, str]:
    name = (upload.filename or "image")[:120]
    data = await upload.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(400, f"{name}: 10MB 이하 이미지만 올릴 수 있어요")
    kind = _detect_image(data[:16])
    if kind is None:
        raise HTTPException(400, f"{name}: PNG, JPG, WebP 이미지만 올릴 수 있어요")
    return name, data, kind[0], kind[1]


def _call(fn, *args):
    try:
        return fn(*args)
    except KeyError:
        raise HTTPException(404, "작업이나 이미지를 찾을 수 없어요")
    except jobs.JobConflict as e:
        raise HTTPException(409, str(e))
    except jobs.LayoutError as e:
        raise HTTPException(409, str(e))


@app.get("/api/options")
async def options():
    return {
        "contentTypes": [{"id": k, "label": v} for k, v in CONTENT_TYPES.items()],
        "styles": [{"id": k, **v} for k, v in THEMES.items()],
        "cutout": cutout.status(),
        "ai": await asyncio.to_thread(claude_cli.status),
        "restrictedSites": [{"domain": s["domain"], "name": s["name"]} for s in site_policy.restricted_sites()],
        "limits": {"topicMax": TOPIC_MAX, "maxImages": MAX_IMAGES, "maxImageBytes": MAX_IMAGE_BYTES, "designRequestMax": DESIGN_REQUEST_MAX},
        "templates": templates.public_templates(),
        "templateTypes": sorted(t for t in CONTENT_TYPES if templates.enabled(t)),
        # 서버가 제공하는 기능. 화면(app.js)만 새 파일이고 서버가 예전 코드로 실행 중이면 화면이 알아채고 안내합니다
        "features": ["libraryManage", "moreResearch", "notesSource"],
    }


@app.post("/api/jobs/draft", status_code=201)
async def create_draft():
    return jobs.create_draft(jobs.new_job_id())


@app.post("/api/jobs", status_code=201)
async def create_job(
    topic: str = Form(...),
    contentType: str = Form(...),
    style: str = Form(DEFAULT_THEME),
    url: str = Form(""),
    imageMeta: str = Form("[]"),
    images: list[UploadFile] = File(default=[]),
):
    """한 번에 만들고 바로 시작합니다. 화면은 초안(/api/jobs/draft) 흐름을 씁니다."""
    topic, contentType, url = _check_input(topic, contentType, url)
    if style not in THEMES:
        raise HTTPException(400, "디자인 스타일 값이 올바르지 않아요")
    if len(images) > MAX_IMAGES:
        raise HTTPException(400, f"이미지는 {MAX_IMAGES}장까지 올릴 수 있어요")
    try:
        meta = json.loads(imageMeta)
    except json.JSONDecodeError:
        raise HTTPException(400, "이미지 정보 형식이 올바르지 않아요")
    if not isinstance(meta, list) or len(meta) != len(images) or not all(isinstance(m, dict) for m in meta):
        raise HTTPException(400, "이미지 정보가 이미지 수와 맞지 않아요")

    # 파일을 저장하기 전에 전부 검사합니다
    prepared = []
    for upload, m in zip(images, meta):
        name, data, ext, mime = await _read_image(upload)
        rights = m.get("rights", "확인 필요")
        source = _check_rights(name, rights, str(m.get("source", "")))
        prepared.append((name, data, ext, mime, rights, source))

    job_id = jobs.new_job_id()
    assets = [jobs.new_asset(job_id, *item) for item in prepared]
    return jobs.create(job_id, topic, contentType, style, url, assets)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = jobs.load(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없어요")
    return job


@app.patch("/api/jobs/{job_id}/input")
async def update_input(job_id: str, body: InputBody):
    topic, content_type, url = _check_input(body.topic, body.contentType, body.url, require_topic=False)
    notes_url = _check_notes_source(body.notesKind, body.notesUrl)
    return _call(jobs.update_input, job_id, topic, content_type, url, body.notes.strip(), body.notesKind, notes_url)


@app.post("/api/jobs/{job_id}/start")
async def start_job(job_id: str, body: InputBody):
    topic, content_type, url = _check_input(body.topic, body.contentType, body.url)
    notes_url = _check_notes_source(body.notesKind, body.notesUrl)
    _call(jobs.update_input, job_id, topic, content_type, url, body.notes.strip(), body.notesKind, notes_url)
    return _call(jobs.start, job_id, body.mode, body.researchMode, body.researchVersion)


# ---------- 조사 자료 보관함 ----------
@app.get("/api/research-library")
async def research_library_versions(topic: str = "", contentType: str = ""):
    """같은 유형·주제로 저장된 조사 버전 목록 (최근 것부터). 유형이 '자동'이면 모든 유형에서 찾습니다."""
    topic = topic.strip()
    if not topic or len(topic) > TOPIC_MAX:
        return {"versions": []}
    types = [contentType] if contentType in CONTENT_TYPES else list(CONTENT_TYPES)
    found = [v for t in types for v in jobs.research_versions(t, topic)]
    found.sort(key=lambda v: (v["createdAt"], v["number"]), reverse=True)
    return {"versions": found}


class LibraryRename(Strict):
    name: str = Field(default="", max_length=200)


@app.patch("/api/research-library/{version_id}")
async def rename_research_version(version_id: str, body: LibraryRename):
    """버전 이름만 바꿉니다. 빈 이름이면 기본 이름(조사일·유형)으로 되돌립니다. 조사 자료는 고치지 않습니다."""
    version = research_library.rename(version_id, body.name)
    if version is None:
        raise HTTPException(404, "저장된 조사 자료를 찾을 수 없어요")
    return version


@app.get("/api/research-library/{version_id}/usage")
async def research_version_usage(version_id: str):
    """지우기 전에 확인: 이 버전과 연결된 작업 목록."""
    if research_library.get(version_id) is None:
        raise HTTPException(404, "저장된 조사 자료를 찾을 수 없어요")
    return {"usedBy": jobs.research_version_usage(version_id)}


@app.delete("/api/research-library/{version_id}")
async def delete_research_version(version_id: str):
    """버전 하나만 지웁니다. 그 자료로 만든 작업은 복사해 둔 자료를 그대로 씁니다."""
    result = jobs.delete_research_version(version_id)
    if result is None:
        raise HTTPException(404, "저장된 조사 자료를 찾을 수 없어요")
    return result


@app.get("/api/research-library/{version_id}")
async def research_library_version(version_id: str):
    version = research_library.get(version_id)
    if version is None:
        raise HTTPException(404, "저장된 조사 자료를 찾을 수 없어요")
    research = version["research"]
    return {**version, "research": {"items": research.get("items") or [], "facts": research.get("facts", []), "missing": research.get("missing", []),
                                    "sources": version["sources"]}}


@app.post("/api/jobs/{job_id}/material")
async def submit_material(job_id: str, body: MaterialBody):
    # 확인되지 않은 내용을 채우지 않도록 최소한의 자료가 있어야 합니다. 상세 이미지를 올렸으면 이미지만으로도 됩니다
    job = jobs.load(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없어요")
    if not body.has_content():
        if job["detailImages"]:
            return _call(jobs.submit_material, job_id, None)
        raise HTTPException(400, "알려 주고 싶은 정보를 적거나, 출처 내용을 붙여 넣거나, 상세페이지 이미지를 올려 주세요")
    material = {**body.model_dump(), "sourceUrl": _clean_url(body.sourceUrl),
                "sources": [{**b.model_dump(), "url": _clean_url(b.url)} for b in body.sources]}
    return _call(jobs.submit_material, job_id, material)


@app.post("/api/jobs/{job_id}/research/compose-current")
async def compose_with_current(job_id: str):
    # 자료가 부족하다고 판단됐어도 지금 자료로 구성안을 씁니다. 다시 검색하지 않습니다 (구성안 1회)
    return _call(jobs.compose_with_current, job_id)


# ---------- 상세페이지 이미지 (자료 조사용) ----------
@app.post("/api/jobs/{job_id}/detail-images", status_code=201)
async def upload_detail_images(job_id: str, images: list[UploadFile] = File(...)):
    """사용자가 상세페이지 스크린샷이나 이미지 파일을 올립니다. 카드에 넣는 이미지가 아니라 자료로만 씁니다."""
    if not images:
        raise HTTPException(400, "이미지를 골라 주세요")
    _call(jobs.check_detail_upload, job_id, len(images))
    prepared = [await _read_image(upload) for upload in images]  # 모두 검사한 뒤 저장합니다
    saved = [jobs.new_detail_image(job_id, name, data, ext, mime, "upload") for name, data, ext, mime in prepared]
    return _call(jobs.add_detail_images, job_id, saved)


@app.post("/api/jobs/{job_id}/detail-images/fetch")
async def fetch_detail_images(job_id: str):
    """참고 URL 페이지에서 상세 이미지를 찾아 받습니다. 사용자가 누를 때만, 사이트 정책과 robots.txt를 지켜 요청합니다."""
    job = jobs.load(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없어요")
    if not job["url"]:
        raise HTTPException(400, "참고 URL을 먼저 입력해 주세요")
    _call(jobs.check_detail_upload, job_id, 1)
    try:
        found = await asyncio.to_thread(detail_images.find_page_images, job["url"])
    except detail_images.DetailError as e:
        raise HTTPException(409, str(e))
    site_policy.record_failures(found["failures"])  # 요청을 막은 사이트는 한동안 다시 요청하지 않습니다
    saved = [jobs.new_detail_image(job_id, image["imageUrl"].rsplit("/", 1)[-1][:120] or "detail", image["data"], image["ext"], image["mime"],
                                   "page", job["url"], image["imageUrl"]) for image in found["images"]]
    report = {"pageUrl": job["url"], "found": len(saved), "skipped": found["skipped"],
              "failures": [{k: f[k] for k in ("host", "code", "label")} for f in found["failures"]]}
    return _call(jobs.add_detail_images, job_id, saved, report)


@app.post("/api/jobs/{job_id}/detail-images/extract", status_code=202)
async def extract_detail_images(job_id: str):
    return _call(jobs.extract_details, job_id)


@app.get("/api/jobs/{job_id}/detail-images/{image_id}")
async def get_detail_image(job_id: str, image_id: str):
    found = jobs.detail_image(job_id, image_id) if jobs.JOB_ID_RE.match(image_id) else None
    if not found:
        raise HTTPException(404, "이미지를 찾을 수 없어요")
    return FileResponse(found[0], media_type=found[1])


@app.delete("/api/jobs/{job_id}/detail-images/{image_id}")
async def remove_detail_image(job_id: str, image_id: str):
    return _call(jobs.remove_detail_image, job_id, image_id)


class ResearchItemEdit(Strict):
    value: str = Field(default="", max_length=400)


class ResearchChoice(Strict):
    index: int = Field(ge=0, le=20)


# ---------- '저장된 자료 사용': 보완 조사 결과 검토 ----------
@app.put("/api/jobs/{job_id}/research/items/{key}")
async def edit_research_item(job_id: str, key: str, body: ResearchItemEdit):
    """통합된 조사 항목 값을 직접 고칩니다 (사용자 제공 값으로 기록, 이전 값은 보존)."""
    return _call(jobs.edit_research_item, job_id, key, body.value)


@app.post("/api/jobs/{job_id}/research/items/{key}/choose")
async def choose_research_value(job_id: str, key: str, body: ResearchChoice):
    """기존 값과 추가 조사 값이 다를 때 하나를 고릅니다 (0 = 기존 값)."""
    return _call(jobs.choose_research_value, job_id, key, body.index)


@app.post("/api/jobs/{job_id}/research/approve")
async def approve_research(job_id: str):
    """검토한 통합 자료를 새 버전으로 저장하고 그 자료로 구성안을 씁니다."""
    return _call(jobs.approve_research, job_id)


@app.post("/api/jobs/{job_id}/research/supplement-retry")
async def retry_supplement(job_id: str):
    return _call(jobs.retry_supplement, job_id)


# ---------- 조사 결과 화면의 '추가 조사' (초안 → 통합 / 버리기) ----------
class MoreResearchRequest(Strict):
    request: str = Field(min_length=1, max_length=600)  # 서버가 공백을 정리한 뒤 300자로 자릅니다


@app.post("/api/jobs/{job_id}/research/more", status_code=202)
async def request_more_research(job_id: str, body: MoreResearchRequest):
    """사용자가 적은 내용을 추가 조사합니다. 결과는 초안으로만 두고 지금 자료는 바꾸지 않습니다."""
    return _call(jobs.request_more_research, job_id, body.request)


@app.post("/api/jobs/{job_id}/research/more/items/{key}/choose")
async def choose_more_value(job_id: str, key: str, body: ResearchChoice):
    """초안에서 기존 값과 추가 조사 값이 다를 때 하나를 고릅니다 (0 = 기존 값)."""
    return _call(jobs.choose_more_value, job_id, key, body.index)


@app.post("/api/jobs/{job_id}/research/more/accept")
async def accept_more_research(job_id: str):
    """초안을 조사 자료로 통합합니다 (구성안은 그대로, 새 조사 버전 저장)."""
    return _call(jobs.accept_more_research, job_id)


@app.post("/api/jobs/{job_id}/research/more/discard")
async def discard_more_research(job_id: str):
    """초안을 버립니다. 지금 자료는 그대로입니다."""
    return _call(jobs.discard_more_research, job_id)


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str):
    return _call(jobs.retry, job_id)


@app.post("/api/jobs/{job_id}/assets", status_code=201)
async def add_asset(job_id: str, image: UploadFile = File(...), rights: str = Form("확인 필요"), source: str = Form("")):
    job = jobs.load(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없어요")
    if len([a for a in job["assets"] if not a["removed"]]) >= MAX_IMAGES:
        raise HTTPException(400, f"이미지는 {MAX_IMAGES}장까지 올릴 수 있어요")
    name, data, ext, mime = await _read_image(image)
    source = _check_rights(name, rights, source)
    if job["state"] == "running":
        raise HTTPException(409, "제작이 진행 중이에요. 끝난 뒤에 다시 시도해 주세요")
    asset = jobs.new_asset(job_id, name, data, ext, mime, rights, source)
    return _call(jobs.add_asset, job_id, asset)


@app.patch("/api/jobs/{job_id}/assets/{asset_id}")
async def update_asset(job_id: str, asset_id: str, body: AssetPatch):
    if body.rights is not None and body.rights not in RIGHTS:
        raise HTTPException(400, "사용 권한 값이 올바르지 않아요")
    source = None if body.source is None else body.source[:SOURCE_MAX]
    return _call(jobs.update_asset, job_id, asset_id, body.rights, source, body.useVariant)


@app.delete("/api/jobs/{job_id}/assets/{asset_id}")
async def remove_asset(job_id: str, asset_id: str):
    return _call(jobs.remove_asset, job_id, asset_id)


@app.post("/api/jobs/{job_id}/assets/{asset_id}/cutout", status_code=202)
async def start_cutout(job_id: str, asset_id: str, body: CutoutBody):
    state = cutout.status()
    if not state["available"]:
        raise HTTPException(409, state["reason"])
    if body.model not in [m["id"] for m in state["models"]]:
        raise HTTPException(409, "이 모델은 설치되어 있지 않아요. 자동으로 내려받지 않아요.")
    return _call(jobs.start_cutout, job_id, asset_id, body.model)


@app.get("/api/jobs/{job_id}/assets/{asset_id}")
async def get_asset(job_id: str, asset_id: str, variant: Literal["original", "cutout"] = "original"):
    job = jobs.load(job_id)
    asset = next((a for a in job["assets"] if a["id"] == asset_id), None) if job else None
    if asset is None:
        raise HTTPException(404, "이미지를 찾을 수 없어요")
    if variant == "cutout":
        path = jobs.cutout_path(job_id, asset)
        if path is None:
            raise HTTPException(404, "배경을 제거한 이미지가 없어요")
        return FileResponse(path, media_type="image/png")
    return FileResponse(jobs.uploads_dir(job_id) / f"{asset_id}{asset['ext']}", media_type=asset["mime"])


@app.post("/api/jobs/{job_id}/outline/approve")
async def approve_outline(job_id: str):
    return _call(jobs.approve_outline, job_id)


@app.post("/api/jobs/{job_id}/outline/regenerate")
async def regenerate_outline(job_id: str):
    return _call(jobs.regenerate_outline, job_id)


@app.put("/api/jobs/{job_id}/outline/cards/{frame}")
async def edit_outline_card(job_id: str, frame: str, request: Request):
    job = jobs.load(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없어요")
    model = TemplateCardEdit if templates.is_template_job(job) else CardEdit
    try:
        body = model.model_validate(await request.json())
    except (ValidationError, ValueError):
        raise HTTPException(400, "카드 내용 형식이 올바르지 않아요")
    return _call(jobs.edit_outline_card, job_id, frame, body.model_dump())


class CardTemplateBody(Strict):
    template: str = Field(max_length=40)


@app.put("/api/jobs/{job_id}/outline/cards/{frame}/template")
async def change_card_template(job_id: str, frame: str, body: CardTemplateBody):
    """card-02 ~ card-05의 카드 구성(템플릿)을 바꿉니다. 승인 단계에서 사용자가 고를 수 있습니다."""
    return _call(jobs.change_card_template, job_id, frame, body.template)


@app.put("/api/jobs/{job_id}/content-type")
async def change_content_type(job_id: str, body: ContentTypeBody):
    if body.contentType not in CONTENT_TYPES:
        raise HTTPException(400, "콘텐츠 유형을 골라 주세요")
    return _call(jobs.change_content_type, job_id, body.contentType)


@app.put("/api/jobs/{job_id}/cards/{frame}/slots/{slot}")
async def set_slot_image(job_id: str, frame: str, slot: str, body: CardImageBody):
    return _call(jobs.set_slot_image, job_id, frame, slot, body.assetId, body.variant)


@app.post("/api/jobs/{job_id}/cards/{frame}/slots/{slot}/upload", status_code=201)
async def upload_slot_image(job_id: str, frame: str, slot: str, image: UploadFile = File(...), rights: str = Form("확인 필요"), source: str = Form("")):
    """구성안 단계에서 카드 이미지 자리에 바로 올려 넣거나 교체합니다. 권한을 고르지 않아도 되고, 출처는 적으면 함께 저장합니다."""
    job = jobs.load(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없어요")
    if len([a for a in job["assets"] if not a["removed"]]) >= MAX_IMAGES:
        raise HTTPException(400, f"이미지는 {MAX_IMAGES}장까지 올릴 수 있어요. 쓰지 않는 이미지를 빼 주세요")
    name, data, ext, mime = await _read_image(image)
    source = _check_rights(name, rights, source)
    _call(jobs.check_slot_upload, job_id, frame, slot)  # 파일을 저장하기 전에 상태와 자리를 확인합니다
    asset = jobs.new_asset(job_id, name, data, ext, mime, rights, source)
    return _call(jobs.add_asset_to_slot, job_id, frame, slot, asset)


@app.put("/api/jobs/{job_id}/cards/{frame}/slots/{slot}/adjust")
async def adjust_slot_image(job_id: str, frame: str, slot: str, body: SlotAdjustBody):
    return _call(jobs.adjust_slot_image, job_id, frame, slot, body.scale, body.dx, body.dy)


@app.post("/api/jobs/{job_id}/cards/{frame}/slots/{slot}/restore")
async def restore_slot_original(job_id: str, frame: str, slot: str):
    return _call(jobs.restore_slot_original, job_id, frame, slot)


@app.post("/api/jobs/{job_id}/slot-suggestions/apply")
async def apply_slot_suggestions(job_id: str, body: SuggestionBody):
    return _call(jobs.apply_slot_suggestions, job_id, body.frame, body.slot)


@app.post("/api/jobs/{job_id}/outline/cards/{frame}/regenerate")
async def regenerate_outline_card(job_id: str, frame: str):
    return _call(jobs.regenerate_outline_card, job_id, frame)


@app.post("/api/jobs/{job_id}/outline/cards/{frame}/next-teaser")
async def write_next_teaser(job_id: str, frame: str):
    # 다음 캐릭터 예고 카드의 힌트·공개 문구. 버튼을 눌렀을 때만 AI를 부릅니다 (검색 없이 1회)
    return _call(jobs.write_next_teaser, job_id, frame)


@app.post("/api/jobs/{job_id}/preview/approve")
async def approve_preview(job_id: str):
    return _call(jobs.approve_preview, job_id)


@app.post("/api/jobs/{job_id}/preview/regenerate")
async def regenerate_preview(job_id: str):
    return _call(jobs.regenerate_all_layouts, job_id)


@app.post("/api/jobs/{job_id}/preview/cards/{frame}/regenerate")
async def regenerate_card(job_id: str, frame: str):
    return _call(jobs.regenerate_card, job_id, frame)


@app.post("/api/jobs/{job_id}/preview/cards/{frame}/restore")
async def restore_card(job_id: str, frame: str):
    return _call(jobs.restore_card, job_id, frame)


@app.post("/api/jobs/{job_id}/preview/cards/{frame}/ai-redesign")
async def ai_redesign(job_id: str, frame: str, body: RedesignBody):
    return _call(jobs.start_redesign, job_id, frame, body.text)


@app.put("/api/jobs/{job_id}/preview/cards/{frame}/image")
async def set_card_image(job_id: str, frame: str, body: CardImageBody):
    return _call(jobs.set_card_image, job_id, frame, body.assetId, body.variant)


@app.post("/api/jobs/{job_id}/preview/cards/{frame}/design-requests", status_code=201)
async def add_design_request(job_id: str, frame: str, body: DesignRequestBody):
    return _call(jobs.add_design_request, job_id, frame, body.text)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

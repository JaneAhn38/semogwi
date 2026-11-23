"""Claude Code CLI(`claude -p`) 호출. 이 PC에 로그인된 Claude 구독으로 실행합니다.

- API 키로 과금되지 않도록 인증 관련 환경 변수를 지우고 실행합니다. 구독 로그인이 아니면 실행하지 않습니다.
- 프로젝트 파일과 커넥터를 읽지 않도록 빈 작업 폴더에서, 지정한 도구만 허용해 실행합니다.
- 실제 도구 사용 기록(tool_use_result)을 함께 돌려줍니다. 출처 검증은 모델의 말이 아니라 이 기록을 기준으로 합니다.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import site_policy

CLAUDE_BIN = os.environ.get("SEMOGWI_CLAUDE_BIN", "claude")
WORK_DIR = Path(os.environ.get("SEMOGWI_DATA_DIR", Path(__file__).resolve().parent.parent / "data")) / "claude-workdir"
_BILLING_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
_STATUS_TTL = 60

_status_cache: tuple[float, dict] | None = None


class AIError(Exception):
    """화면에 그대로 보여 줄 수 있는 실패 이유. kind: auth, limit, timeout, invalid, insufficient, unavailable, error"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass
class CliRun:
    structured: dict | None = None
    searches: list[dict] = field(default_factory=list)  # {query, results: [{title, url}]}
    fetches: list[dict] = field(default_factory=list)  # {url, code}
    search_failures: list[dict] = field(default_factory=list)  # {query, reason} 검색 도구가 오류로 끝난 경우
    is_error: bool = False
    subtype: str = ""
    api_error_status: int | None = None
    result_text: str = ""
    turns: int = 0
    duration_ms: int = 0
    estimated_usd: float = 0.0
    model: str = ""
    rate_status: str = ""
    five_hour_utilization: float | None = None
    resets_at: int | None = None
    credential_expires_at: str | None = None
    permission_mode: str = ""  # CLI가 시작하면서 알려 준 실제 권한 모드 (init 이벤트)
    init_tools: list[str] | None = None  # CLI가 시작하면서 알려 준 실제 도구 목록. None이면 init 이벤트가 없음


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _BILLING_ENV}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


_NPM_EXE = Path("node_modules") / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"


def _executable() -> str | None:
    """실행할 Claude Code 파일. npm 설치본의 claude.cmd는 그 안의 claude.exe를 찾아 직접 씁니다.

    .cmd·.bat은 Windows가 cmd.exe로 실행하는데, cmd.exe는 인자에 든 줄바꿈 뒤를 버리고 따옴표·%·& 등도 다시 해석합니다.
    그러면 권한 설정(--allowedTools, --permission-mode)이 잘려 검색이 "권한을 아직 안 줬다"며 거절됩니다 (2026-11-20 확인).
    """
    found = shutil.which(CLAUDE_BIN)
    if not found or Path(found).suffix.lower() not in (".cmd", ".bat"):
        return found
    return str(_exe_behind_cmd(Path(found)) or found)


def _exe_behind_cmd(cmd: Path) -> Path | None:
    try:
        text = cmd.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    candidates = [cmd.parent / m.replace("\\", "/") for m in re.findall(r'"%dp0%\\([^"]+?\.exe)"', text, re.IGNORECASE)]
    candidates.append(cmd.parent / _NPM_EXE)
    return next((c for c in candidates if c.is_file()), None)


def status(force: bool = False) -> dict:
    """AI 모드 사용 가능 여부. 구독 로그인일 때만 available입니다."""
    global _status_cache
    if not force and _status_cache and time.monotonic() - _status_cache[0] < _STATUS_TTL:
        return _status_cache[1]
    result = _read_status()
    _status_cache = (time.monotonic(), result)
    return result


def _read_status() -> dict:
    exe = _executable()
    if not exe:
        return {"available": False, "reason": "Claude Code를 찾지 못했어요. 설치 여부를 확인해 주세요."}
    try:
        done = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=30, env=_clean_env(), stdin=subprocess.DEVNULL)
        info = json.loads(done.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {"available": False, "reason": "Claude Code 로그인 상태를 확인하지 못했어요."}
    if not info.get("loggedIn"):
        return {"available": False, "reason": "Claude Code에 로그인되어 있지 않아요. 터미널에서 claude auth login을 실행해 주세요."}
    if info.get("authMethod") != "claude.ai":
        return {"available": False, "reason": "구독 로그인이 아니에요. 별도 과금을 막기 위해 AI 호출을 하지 않아요."}
    return {"available": True, "reason": "", "plan": info.get("subscriptionType", ""), "loginExpiresAt": info.get("loginExpiresAt")}


def parse_stream(stdout: str) -> CliRun:
    run = CliRun()
    fetch_calls: dict[str, str] = {}  # tool_use id -> 요청한 URL
    search_calls: dict[str, str] = {}  # tool_use id -> 검색어
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            run.model = event.get("model", "")
            run.permission_mode = str(event.get("permissionMode") or "")
            run.init_tools = [str(t) for t in event.get("tools") or []]
        elif kind == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_use" and block.get("name") == "WebFetch":
                    fetch_calls[block.get("id", "")] = str((block.get("input") or {}).get("url", ""))
                if block.get("type") == "tool_use" and block.get("name") == "WebSearch":
                    search_calls[block.get("id", "")] = str((block.get("input") or {}).get("query", ""))
        elif kind == "user":
            _read_failed_search(run, event, search_calls)
            count = len(run.fetches)
            if not _read_tool_result(run, event.get("tool_use_result")):
                _read_failed_fetch(run, event, fetch_calls)
            if len(run.fetches) > count:
                wait = re.search(r"retry-after:\s*(\d+)", json.dumps((event.get("message") or {}).get("content"), ensure_ascii=False), re.IGNORECASE)
                if wait:
                    run.fetches[-1]["retryAfter"] = int(wait.group(1))
        elif kind == "rate_limit_event":
            info = event.get("rate_limit_info") or {}
            run.rate_status = info.get("status", run.rate_status)
            run.resets_at = info.get("resetsAt", run.resets_at)
            window = (info.get("unifiedWindows") or {}).get("five_hour") or {}
            if window.get("utilization") is not None:
                run.five_hour_utilization = window["utilization"]
        elif kind == "result":
            run.structured = event.get("structured_output")
            run.is_error = bool(event.get("is_error"))
            run.subtype = event.get("subtype", "")
            run.api_error_status = event.get("api_error_status")
            run.result_text = str(event.get("result") or "")
            run.turns = event.get("num_turns", 0)
            run.duration_ms = event.get("duration_ms", 0)
            run.estimated_usd = event.get("total_cost_usd", 0.0) or 0.0
            run.credential_expires_at = event.get("credential_expires_at")
    return run


ERROR_DETAIL_MAX = 300


def error_detail(content, fallback=None) -> str:
    """도구가 돌려준 오류 원문. 화면과 작업 기록에 그대로 남겨 실패 이유를 확인할 수 있게 합니다."""
    if isinstance(content, list):
        content = " ".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in content)
    text = str(content or "").strip() or (fallback if isinstance(fallback, str) else "")
    text = re.sub(r"</?tool_use_error>", "", text)
    return " ".join(text.split())[:ERROR_DETAIL_MAX]


def _read_failed_fetch(run: CliRun, event: dict, fetch_calls: dict[str, str]) -> None:
    """실패한 WebFetch는 정상 형식의 결과가 없으므로 오류 내용에서 상태 코드를 읽습니다."""
    content = (event.get("message") or {}).get("content")
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        url = fetch_calls.get(block.get("tool_use_id", ""))
        if url:
            text = json.dumps(block.get("content"), ensure_ascii=False)
            found = re.search(r"\b([45]\d\d)\b", text)
            entry = {"url": url, "code": int(found.group(1)) if found else 0,
                     "detail": error_detail(block.get("content"), event.get("tool_use_result"))}
            if not found and re.search(r"denied|permission|not allowed", text, re.IGNORECASE):
                rule = site_policy.blocked_by_rule(url, text)
                if rule:
                    entry.update(denied=True, rule=rule)  # 우리 차단 규칙(금지 사이트·대기 중 사이트)으로 요청하지 않은 경우
                else:
                    entry["refused"] = True  # 도구가 거부했지만 우리 규칙은 아님: 읽기 실패로 보여 줍니다
            run.fetches.append(entry)


def _read_failed_search(run: CliRun, event: dict, search_calls: dict[str, str]) -> None:
    content = (event.get("message") or {}).get("content")
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
            query = search_calls.get(block.get("tool_use_id", ""))
            if query is not None:
                detail = error_detail(block.get("content"), event.get("tool_use_result"))
                run.search_failures.append({"query": query[:200], "reason": "검색 도구 오류" if "denied" not in detail.lower() else "검색 도구 사용 거부",
                                            "detail": detail})


def _read_tool_result(run: CliRun, result) -> bool:
    if not isinstance(result, dict):
        return False
    if "query" in result and "results" in result:
        found = []
        for group in result["results"]:
            content = group.get("content") if isinstance(group, dict) else None
            for item in content if isinstance(content, list) else []:
                if isinstance(item, dict) and item.get("url"):
                    found.append({"title": str(item.get("title", ""))[:200], "url": item["url"]})
        run.searches.append({"query": str(result["query"])[:200], "results": found})
        return True
    if "url" in result and "code" in result:
        run.fetches.append({"url": result["url"], "code": result["code"]})
        return True
    return False


def _reset_text(resets_at: int | None) -> str:
    if not resets_at:
        return ""
    return f" {datetime.fromtimestamp(resets_at).strftime('%m월 %d일 %H:%M')} 이후에 다시 시도해 주세요."


def _classify(run: CliRun, stderr: str, returncode: int) -> AIError:
    text = f"{run.result_text}\n{stderr}".lower()
    if run.rate_status == "rejected" or run.api_error_status == 429 or "hit your" in text or "usage limit" in text or "rate limit" in text:
        return AIError("limit", f"Claude Pro 사용 한도에 도달했어요.{_reset_text(run.resets_at)}")
    if run.api_error_status in (401, 403) or "not logged in" in text or "please run /login" in text or "authentication" in text or "login expired" in text:
        return AIError("auth", "Claude 로그인이 만료됐거나 인증에 실패했어요. 터미널에서 claude auth login을 실행한 뒤 다시 시도해 주세요.")
    if run.subtype == "error_max_budget_usd":
        return AIError("error", "이번 작업의 사용량 상한을 넘어 중단했어요. 다시 시도해 주세요.")
    if run.subtype == "error_max_structured_output_retries":
        return AIError("invalid", "AI가 요구한 JSON 형식으로 답하지 못했어요. 다시 시도해 주세요.")
    return AIError("error", f"AI 호출이 실패했어요 (종료 코드 {returncode}, {run.subtype or '결과 없음'}). 다시 시도해 주세요.")


SETTINGS_LOST = ("Claude CLI에 실행 설정(도구 허용·권한 모드)이 전달되지 않아 결과를 쓰지 않았어요. "
                 "Claude Code 설치 방식을 확인하거나 개발자에게 알려 주세요.")


def build_args(exe: str, system_file: str, schema: dict, *, tools: tuple[str, ...], model: str, effort: str,
               budget_usd: float, disallowed: tuple[str, ...], images: bool = False) -> list[str]:
    args = [
        exe, "-p", "--model", model, "--effort", effort,
        "--output-format", "stream-json", "--verbose",
        "--tools", ",".join(tools) if tools else "",
        "--permission-mode", "dontAsk",
        "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands",
        "--setting-sources", "",
        "--max-budget-usd", str(budget_usd),
        "--system-prompt-file", system_file,
        "--json-schema", json.dumps(schema, ensure_ascii=False),
    ]
    if images:
        args += ["--input-format", "stream-json"]  # 이미지는 명령줄이 아니라 표준 입력(stream-json)으로 보냅니다
    if tools:
        args += ["--allowedTools", ",".join(tools)]
    if disallowed:
        args += ["--disallowedTools", *disallowed]
    if any("\n" in a or "\r" in a for a in args):
        raise AIError("error", "AI 호출 인자에 줄바꿈이 있어 실행하지 않았어요.")  # 줄바꿈은 cmd.exe에서 뒤 인자를 잘라냅니다
    return args


def check_settings_applied(parsed: CliRun, tools: tuple[str, ...]) -> None:
    """CLI가 실제로 받은 권한 모드와 도구가 요청과 같은지. 다르면 설정이 빠진 채 실행된 것이라 결과를 쓰지 않습니다."""
    if parsed.init_tools is None or parsed.permission_mode != "dontAsk":
        raise AIError("error", SETTINGS_LOST)
    if set(parsed.init_tools) - {"StructuredOutput"} != set(tools):
        raise AIError("error", SETTINGS_LOST)
def image_message(prompt: str, images: list[tuple[str, str, bytes]]) -> str:
    """이미지와 글을 한 사용자 메시지로 묶은 stream-json 입력 한 줄. images: [(설명, MIME, 바이트)]

    이미지는 파일 경로가 아니라 내용(base64)으로 보냅니다. 그래서 AI에게 파일 읽기 도구를 주지 않아도 됩니다.
    """
    content = []
    for label, mime, data in images:
        content.append({"type": "text", "text": label})
        content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(data).decode("ascii")}})
    content.append({"type": "text", "text": prompt})
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}, ensure_ascii=False) + "\n"


def run(prompt: str, system: str, schema: dict, *, tools: tuple[str, ...] = (), model: str = "sonnet",
        effort: str = "medium", timeout: int = 300, budget_usd: float = 1.0, disallowed: tuple[str, ...] = (),
        images: list[tuple[str, str, bytes]] | None = None) -> CliRun:
    """프롬프트를 실행하고 구조화된 결과와 도구 사용 기록을 돌려줍니다. 실패하면 AIError를 냅니다.

    images를 주면 이미지와 함께 보냅니다 (상세 이미지 판독). 도구 없이 실행합니다.
    """
    state = status()
    if not state["available"]:
        raise AIError("unavailable", state["reason"])
    exe = _executable()
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    # 여러 줄 지시문은 명령줄이 아니라 파일로 넘깁니다 (명령줄 인자에는 줄바꿈이 없어야 합니다)
    system_file = WORK_DIR / f"system-{uuid.uuid4().hex}.txt"
    system_file.write_text(system, encoding="utf-8")
    try:
        args = build_args(exe, str(system_file), schema, tools=tools, model=model, effort=effort, budget_usd=budget_usd,
                          disallowed=disallowed, images=bool(images))
        try:
            done = subprocess.run(args, input=image_message(prompt, images) if images else prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout, cwd=WORK_DIR, env=_clean_env())
        except subprocess.TimeoutExpired:
            raise AIError("timeout", f"AI 응답이 {timeout // 60}분 안에 끝나지 않아 중단했어요. 다시 시도해 주세요.") from None
        except OSError:
            raise AIError("unavailable", "Claude Code를 실행하지 못했어요.") from None
    finally:
        system_file.unlink(missing_ok=True)

    parsed = parse_stream(done.stdout)
    if done.returncode != 0 or parsed.is_error:
        raise _classify(parsed, done.stderr, done.returncode)
    check_settings_applied(parsed, tools)
    if not isinstance(parsed.structured, dict):
        raise AIError("invalid", "AI가 요구한 JSON 형식으로 답하지 못했어요. 다시 시도해 주세요.")
    return parsed


def call_meta(kind: str, parsed: CliRun) -> dict:
    return {"kind": kind, "model": parsed.model, "turns": parsed.turns, "durationMs": parsed.duration_ms,
            "estimatedUsd": round(parsed.estimated_usd, 4), "searches": len(parsed.searches), "fetches": len(parsed.fetches),
            "fiveHourUtilization": parsed.five_hour_utilization, "at": datetime.now().isoformat(timespec="seconds")}

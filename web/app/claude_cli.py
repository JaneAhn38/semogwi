"""Claude Code CLI(`claude -p`) 호출. 이 PC에 로그인된 Claude 구독으로 실행합니다.

- API 키로 과금되지 않도록 인증 관련 환경 변수를 지우고 실행합니다. 구독 로그인이 아니면 실행하지 않습니다.
- 프로젝트 파일과 커넥터를 읽지 않도록 빈 작업 폴더에서, 지정한 도구만 허용해 실행합니다.
- 실제 도구 사용 기록(tool_use_result)을 함께 돌려줍니다. 출처 검증은 모델의 말이 아니라 이 기록을 기준으로 합니다.
"""

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

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


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _BILLING_ENV}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _executable() -> str | None:
    return shutil.which(CLAUDE_BIN)


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
            entry = {"url": url, "code": int(found.group(1)) if found else 0}
            if not found and re.search(r"denied|permission|not allowed", text, re.IGNORECASE):
                entry["denied"] = True  # 차단 규칙으로 요청하지 않은 경우입니다
            run.fetches.append(entry)


def _read_failed_search(run: CliRun, event: dict, search_calls: dict[str, str]) -> None:
    content = (event.get("message") or {}).get("content")
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
            query = search_calls.get(block.get("tool_use_id", ""))
            if query is not None:
                text = json.dumps(block.get("content"), ensure_ascii=False)
                run.search_failures.append({"query": query[:200], "reason": "검색 도구 오류" if "denied" not in text.lower() else "검색 도구 사용 거부"})


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


def run(prompt: str, system: str, schema: dict, *, tools: tuple[str, ...] = (), model: str = "sonnet",
        effort: str = "medium", timeout: int = 300, budget_usd: float = 1.0, disallowed: tuple[str, ...] = ()) -> CliRun:
    """프롬프트를 실행하고 구조화된 결과와 도구 사용 기록을 돌려줍니다. 실패하면 AIError를 냅니다."""
    state = status()
    if not state["available"]:
        raise AIError("unavailable", state["reason"])
    exe = _executable()
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    args = [
        exe, "-p", "--model", model, "--effort", effort,
        "--output-format", "stream-json", "--verbose",
        "--json-schema", json.dumps(schema, ensure_ascii=False),
        "--system-prompt", system,
        "--tools", ",".join(tools) if tools else "",
        "--permission-mode", "dontAsk",
        "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands",
        "--setting-sources", "",
        "--max-budget-usd", str(budget_usd),
    ]
    if tools:
        args += ["--allowedTools", ",".join(tools)]
    if disallowed:
        args += ["--disallowedTools", *disallowed]
    try:
        done = subprocess.run(args, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, cwd=WORK_DIR, env=_clean_env())
    except subprocess.TimeoutExpired:
        raise AIError("timeout", f"AI 응답이 {timeout // 60}분 안에 끝나지 않아 중단했어요. 다시 시도해 주세요.") from None
    except OSError:
        raise AIError("unavailable", "Claude Code를 실행하지 못했어요.") from None

    parsed = parse_stream(done.stdout)
    if done.returncode != 0 or parsed.is_error:
        raise _classify(parsed, done.stderr, done.returncode)
    if not isinstance(parsed.structured, dict):
        raise AIError("invalid", "AI가 요구한 JSON 형식으로 답하지 못했어요. 다시 시도해 주세요.")
    return parsed


def call_meta(kind: str, parsed: CliRun) -> dict:
    return {"kind": kind, "model": parsed.model, "turns": parsed.turns, "durationMs": parsed.duration_ms,
            "estimatedUsd": round(parsed.estimated_usd, 4), "searches": len(parsed.searches), "fetches": len(parsed.fetches),
            "fiveHourUtilization": parsed.five_hour_utilization, "at": datetime.now().isoformat(timespec="seconds")}

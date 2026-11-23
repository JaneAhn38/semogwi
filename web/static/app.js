"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const POLL_MS = 500;
  const FRAMES = ["card-01", "card-02", "card-03", "card-04", "card-05"];

  const STEP_LABELS = [
    "주제 및 이미지 입력",
    "자료 조사 및 구성안 생성",
    "구성안 검토·수정·승인",
    "디자인 미리보기·수정·승인",
    "PNG 다운로드",
  ];
  const AI_TASK_TEXT = {
    outline: "AI가 문구를 다시 쓰고 있어요. 저장된 조사 결과만 쓰고 검색은 다시 하지 않아요.",
    friends: "AI가 확정한 친구에 맞춰 친구 카드를 다시 쓰고 있어요. 자료에 없는 친구만 짧게 찾아봐요.",
    compose: "AI가 입력한 자료로 구성안을 쓰고 있어요. 사이트에는 접속하지 않아요.",
    design: "AI가 카드 5장을 다시 디자인하고 있어요. 1~3분 걸릴 수 있어요.",
    redesign: "AI가 이 카드만 다시 디자인하고 있어요. 1분 안팎 걸려요. 다른 카드는 그대로예요.",
    vision: "AI가 상세 이미지에서 상품 정보를 읽고 있어요. 이미지가 길면 1~2분 걸려요. 웹에는 접속하지 않아요.",
    retype: "AI가 바뀐 유형의 템플릿에 맞춰 구성안을 다시 쓰고 있어요. 저장된 조사 결과만 쓰고 검색은 다시 하지 않아요.",
    research: "AI가 요청한 내용을 추가 조사하고 있어요. 2~5분 걸릴 수 있어요. 지금 조사 자료와 구성안은 그대로예요.",
  };
  const STATUS_TEXT = {
    running: "예시 작업을 진행하고 있어요. 실제 조사나 AI 생성은 하지 않아요.",
    waiting_outline: "구성안을 확인하고 있어요. 승인해야 다음 단계로 넘어가요.",
    waiting_material: "자료가 더 필요해요. 아래에 직접 입력하면 이어서 진행해요.",
    waiting_research: "저장된 자료와 추가 조사 결과를 합쳤어요. 내용을 확인·수정한 뒤 '이 자료로 구성안 만들기'를 눌러 주세요.",
    waiting_preview: "카드 디자인을 확인하고 있어요. 승인해야 PNG를 받을 수 있어요.",
    done: "완료됐어요. 5단계에서 샘플 PNG를 받을 수 있어요.",
    failed: "제작이 멈췄어요.",
    interrupted: "작업이 중단됐어요.",
  };
  const STEP_TEXT = { pending: "대기", active: "진행 중", done: "완료", failed: "실패", waiting: "승인 대기", material: "자료 입력 대기", skipped: "자동 조사 안 함", review: "자료 검토 대기" };
  const MATERIAL_LABELS = {
    goods: { name: "상품명", price: "가격", seller: "판매처", features: "특징" },
    popup: { name: "행사명", price: "입장료·가격", seller: "장소", features: "기간·예약 방법 등" },
    collab: { name: "콜라보 이름", price: "가격", seller: "판매처·장소", features: "콜라보 내용·기간" },
    character: { name: "캐릭터 이름", price: "관련 가격", seller: "공식 채널", features: "특징" },
  };

  // 자료 직접 입력: 유형별 안내와 자유 입력 예시
  const MATERIAL_GUIDES = {
    popup: { guide: "공식 공지에서 확인한 행사 이름, 기간, 장소, 운영 시간, 입장·예약 방법을 알려 주세요. 모르는 내용은 비워 두세요.",
      example: "예: 치이카와 클리닉 팝업 / 2026.11.27 ~ 12.31 / 더현대 서울 5층 / 사전 예약제(네이버 예약)" },
    goods: { guide: "상품명, 가격(표기 그대로), 구성·종류, 판매처, 판매 기간처럼 공식 페이지에서 확인한 내용을 알려 주세요.",
      example: "예: 치이카와 코인 실린더 / ¥440(세금 포함) / 전 8종 랜덤 / 치이카와 마켓 / 11월 20일 발매" },
    collab: { guide: "콜라보 상대, 기간, 장소·판매처, 메뉴·상품, 특전과 받는 조건을 알려 주세요.",
      example: "예: 치이카와 × ○○카페 / 12.1 ~ 12.31 / 전국 매장 / 음료 1잔당 코스터 1장 랜덤 증정" },
    character: { guide: "캐릭터 이름, 등장 작품, 성격·특징, 친구·가족, 공식 프로필처럼 확인한 내용을 알려 주세요.",
      example: "예: 하치와레는 치이카와의 친구예요. 밝고 긍정적이고 노래를 좋아해요." },
  };
  const NOTE_KINDS = [["", "출처 종류 선택 안 함"], ["official", "공식 출처"], ["namuwiki", "나무위키"], ["other", "기타"]];
  const SOURCE_MAX = 3;
  const warnedDownloads = new Set();  // 미확인 정보 확인창은 작업마다 처음 저장할 때 한 번만

  // 자료 부족 안내: 무엇이 왜 부족한지 (진행을 막지 않음). 못 찾은 정보와 근거가 약한 정보(출처 충돌 등)를 나눠 보여 줍니다
  // 공식 확인 여부로는 부족하다고 보지 않습니다 (2차 자료·값이 적힌 검색 결과도 자료)
  function gapBox(node, gap, title, note) {
    const rows = (gap && gap.rows) || [];
    node.hidden = !rows.length && !note;
    if (node.hidden) return;
    const missing = rows.filter((r) => r.kind === "not_found");
    const pending = rows.filter((r) => r.kind === "needs_official");
    const line = (r) => el("li", {}, el("span", { class: `gap-kind${r.kind === "not_found" ? " is-missing" : ""}`, textContent: r.kind === "not_found" ? "찾지 못함" : "근거 약함" }),
      `${r.label}${r.importance === "core" ? " (핵심)" : ""} · ${r.reason}${r.value ? ` · 현재 값: ${r.value}` : ""}`);
    node.replaceChildren(el("h3", { textContent: title }),
      ...(rows.length ? [el("ul", {}, ...pending.map(line), ...missing.map(line))] : []),
      el("small", { textContent: note || "찾지 못한 정보는 카드에 만들어 넣지 않고 비워 둬요. 기사·위키 같은 2차 자료도 자료로 써요. 출처끼리 다른 값은 구성안에서 경고로 알려 드려요." }));
  }

  let options = null;
  let job = null;
  let viewStep = 1;
  let lastMaxStep = 0;
  let pollTimer = null;
  let editingFrame = null;
  let renderChain = Promise.resolve();
  let compareFrame = null;
  let downloadsKey = "";

  const assetDrafts = new Map(); // 아직 저장되지 않은 출처 입력
  const imageCardKeys = new Map();
  const tiles = new Map(); // frame -> { root, canvas, controls, canvasKey, controlsKey }
  const requestDrafts = new Map();
  const openRequests = new Set();

  function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (key === "class") node.className = value;
      else if (key === "dataset") Object.assign(node.dataset, value);
      else if (key.startsWith("aria-")) node.setAttribute(key, value);
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node[key] = value;
    }
    node.append(...children);
    return node;
  }

  function tag(text, kind = "demo") {
    return el("span", { class: `tag tag-${kind}`, textContent: text });
  }

  async function api(path, init) {
    let response;
    try {
      response = await fetch(path, init);
    } catch {
      throw new Error("서버에 연결하지 못했어요. run.bat이 실행 중인지 확인해 주세요.");
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" ? body.detail : "요청을 처리하지 못했어요.");
    }
    return response.json();
  }

  const jsonInit = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

  function setUrl() {
    const params = new URLSearchParams(location.search);
    if (job) params.set("job", job.id);
    else params.delete("job");
    const query = params.toString();
    history.replaceState(null, "", query ? `?${query}` : "/");
  }

  const visibleAssets = () => (job ? job.assets.filter((a) => !a.removed) : []);
  const isProcessing = (asset) => asset.cutout && asset.cutout.status === "processing";
  const identifying = () => Object.values((job && job.slotIdentities) || {}).some((slots) => Object.values(slots).some((r) => r.status === "processing"));
  const hasCutout = (asset) => Boolean(asset.cutout && asset.cutout.file);

  function assetUrl(assetId, variant = "original") {
    const asset = job.assets.find((a) => a.id === assetId);
    const version = asset && asset.cutout ? asset.cutout.version : 0;
    return `/api/jobs/${job.id}/assets/${assetId}?variant=${variant}&v=${version}`;
  }

  // ---------- 오류·알림 ----------
  function show(id, message) {
    $(id).textContent = message || "";
    $(id).hidden = !message;
  }

  // ---------- 실제 AI·데모 구분 ----------
  const selectedMode = () => ($("job-form").elements.mode && $("job-form").elements.mode.value) || "demo";

  function restrictedSiteOf(url) {
    let host = "";
    try {
      host = new URL(url.trim()).hostname.toLowerCase().replace(/\.$/, "").replace(/^www\./, "");
    } catch {
      return null;
    }
    return ((options && options.restrictedSites) || []).find((s) => host === s.domain || host.endsWith(`.${s.domain}`)) || null;
  }
  const isAI = () => (job && job.state !== "draft" ? job.mode === "ai" : selectedMode() === "ai");

  function applyMode() {
    const ai = isAI();
    document.body.classList.toggle("mode-ai", ai);
    const template = Boolean(job && job.format === 3);
    document.body.classList.toggle("format-template", template);
    const started = job && job.state !== "draft";
    $("mode-field").hidden = Boolean(started);
    if (started) $("research-field").hidden = true;
    $("mode-status").textContent = ai ? "실제 AI 모드" : "데모 모드";
    $("mode-status").className = `tag ${ai ? "tag-real" : "tag-demo"}`;
    const status = options && options.ai;
    const usage = job && job.aiUsage ? `Pro 5시간 한도 ${Math.round(job.aiUsage.fiveHourUtilization * 100)}% 사용` : "";
    $("ai-status").textContent = ai ? usage || (status && status.available ? "Claude Pro 연결됨" : "AI 연결 안 됨") : "예시 내용";
    $("ai-status").className = `tag ${ai ? "tag-real" : "tag-demo"}`;
    $("mode-hint").textContent = selectedMode() === "ai"
      ? "로그인된 Claude Pro로 실제로 조사하고 디자인해요. 추가 결제는 없고 Pro 사용 한도에서 차감돼요."
      : status && !status.available
        ? `실제 AI를 쓸 수 없어요: ${status.reason}`
        : "AI를 호출하지 않고 예시 내용으로 흐름만 보여 줘요. 한도가 차감되지 않아요.";
    const restricted = restrictedSiteOf($("url").value);
    $("url-hint").textContent = selectedMode() !== "ai"
      ? "데모에서는 페이지 내용을 가져오지 않아요. 주소만 기록해요."
      : restricted
        ? `${restricted.name}은 이용규약상 자동으로 읽지 않아요. 시작하면 자료를 직접 입력하는 화면으로 이동해요.`
        : "AI가 이 페이지를 먼저 읽고 자료로 써요. 접속이 막히면 직접 입력할 수 있어요.";
    $("progress-note").textContent = ai ? "" : "자료 조사는 실제로 하지 않아요. 실제 AI 모드에서는 조사 결과와 출처가 표시돼요.";
    $("outline-note").innerHTML = "";
    const draftNote = job && job.userMaterial
      ? "입력한 자료를 바탕으로 AI가 쓴 초안이에요. 내용이 맞는지 확인하고 "
      : "AI가 조사한 내용으로 쓴 초안이에요. 사실이 맞는지 확인하고 ";
    $("outline-note").append(ai ? draftNote : "처음 내용은 AI가 쓴 글이 아니라 예시예요. ", el("b", { textContent: "수정" }), "으로 직접 쓴 문구는 그대로 카드에 들어가요.");
    if (template) $("outline-note").append(" 왼쪽 미리보기는 고정 템플릿 그대로이고, 입력하는 즉시 바뀌어요. 비워 둔 칸은 카드에서 숨겨요.");
    $("preview-note").textContent = template
      ? "팀이 만든 고정 템플릿에 승인된 구성안의 문구와 지정한 이미지를 넣었어요. AI는 디자인을 만들지 않아요."
      : ai
      ? "AI가 내용에 맞춰 설계한 디자인이에요. 승인된 구성안의 문구는 서버가 그대로 넣기 때문에 바뀌지 않아요."
      : "표지는 레이아웃을 고정해요. 지금은 AI가 아니라 미리 만든 레이아웃에서 골라요. 승인된 구성안의 문구는 바뀌지 않아요.";
    $("regen-all-label").textContent = ai ? "전체 AI 다시 디자인" : "전체 다시 배치";
    $("download-note").innerHTML = "";
    if (ai) $("download-note").append("승인한 문구와 디자인 그대로 1080×1350 PNG로 저장해요. AI를 다시 호출하지 않아요.");
    else $("download-note").append("승인한 문구와 디자인 그대로 1080×1350 PNG로 저장해요. 다시 생성하지 않아요. 데모 단계라 ", el("b", { textContent: "DEMO SAMPLE" }), " 표시가 들어가고, 게시용이 아니에요.");
  }

  function applyAiTask() {
    const task = job && job.aiTask;
    const node = $("ai-task");
    node.hidden = !task;
    if (task) node.replaceChildren(el("span", { class: "spinner", "aria-hidden": "true" }), AI_TASK_TEXT[task.kind] || "AI 작업 중이에요.");
  }

  function sourcesOf(card) {
    if (!job.research) return [];
    return (card.sourceIds || []).map((id) => job.research.sources.find((s) => s.id === id)).filter(Boolean);
  }

  function sourceLink(source) {
    // 상세 이미지는 저장된 이미지를 열어 AI가 읽은 값과 대조할 수 있게 합니다
    if (source.verification === "image" && source.imageId) return el("a", { href: `/api/jobs/${job.id}/detail-images/${source.imageId}`, target: "_blank", rel: "noopener", textContent: `${source.id} ${source.title}` });
    if (!/^https?:\/\//.test(source.url)) return el("span", { textContent: source.title });
    return el("a", { href: source.url, target: "_blank", rel: "noopener noreferrer", textContent: source.title || source.url });
  }

  function renderResearch() {
    const research = job.research;
    // 금지 사이트라 조사를 하지 않았고 보여 줄 기록도 없으면 빈 패널을 띄우지 않습니다.
    const nothingYet = research && (research.policyStops || []).length && !research.sources.length && !research.queries.length && !research.fetched.length;
    $("research").hidden = !(research && viewStep === 2 && !nothingYet);
    if (!research) return;
    const state = $("research-state");
    const readCount = research.fetched.filter((f) => f.code >= 200 && f.code < 400).length;
    state.textContent = research.searchPerformed || research.fetched.length
      ? `검색 ${research.queries.length}회 · 읽은 페이지 ${readCount}개`
      : (research.policyStops || []).length ? "자동 조사 안 함" : "웹 검색 기록 없음";
    state.className = `approval ${readCount ? "is-approved" : "is-needed"}`;
    renderResearchVersion();
    renderReview(research);
    renderMore(research);
    renderPeople(research);
    renderChecklist(research);
    renderProblems(research);
    $("research-queries").replaceChildren(...research.queries.map((q) => el("li", { textContent: q })));
    $("research-sources").replaceChildren(...research.sources.map((s) =>
      // 확인 상태·분류 배지는 표시하지 않습니다 (verification·kind·officialBasis는 data 속성과 조사 데이터에 그대로)
      el("li", { dataset: { verification: s.verification, kind: s.kind || "" } }, sourceLink(s), sourceNote(s), roundTag(s.round))));
    $("research-facts").replaceChildren(...research.facts.map((f) =>
      el("li", { dataset: { origin: f.origin || "ai" } }, f.text, roundTag(f.round))));
  }

  // 캐릭터 소개: 친구·가족 캐릭터별로 찾은 TMI와 근거 문장·출처, 찾지 못한 캐릭터, 쓰지 않은 내용과 이유
  function renderPeople(research) {
    const people = research.people || {};
    const detail = research.peopleResearch || null;
    const groups = [["friends", "친구"], ["family", "가족"]].filter(([key]) => (people[key] || []).length);
    $("research-people-wrap").hidden = !groups.length;
    if (!groups.length) return;
    const found = groups.reduce((n, [key]) => n + people[key].filter((p) => p.tmi).length, 0);
    const total = groups.reduce((n, [key]) => n + people[key].length, 0);
    $("research-people-note").textContent = detail
      ? `캐릭터별 추가 조사: 검색 ${detail.queries.length}회 · 읽은 페이지 ${(detail.pages || []).length}개 · TMI 확인 ${found}/${total}명`
        + (detail.queries.length ? ` · 검색어: ${detail.queries.join(" / ")}` : "") + (detail.error ? ` · 추가 조사 실패: ${detail.error}` : "")
      : `TMI 확인 ${found}/${total}명 (캐릭터별 추가 조사 기록 없음)`;
    $("research-people").replaceChildren(...groups.flatMap(([key, label]) => people[key].map((p) =>
      el("li", { dataset: { person: `${key}:${p.name}` } },
        el("span", { class: "tag tag-demo", textContent: label }), " ",
        el("b", { textContent: p.name }), p.relation ? ` (${p.relation})` : "",
        el("div", { class: "person-tmi", textContent: p.tmi ? `TMI: ${p.tmi}` : "TMI: 출처에서 찾지 못했어요 (만들어 넣지 않았어요)" }),
        p.quote ? el("small", { class: "hint", textContent: `근거 문장: “${p.quote}”` }) : "",
        (p.sourceIds || []).length ? el("div", { class: "card-links" }, ...sourceLinksOf(p.sourceIds)) : ""))));
    $("research-people-rejected").replaceChildren(...((detail && detail.rejected) || []).map((r) =>
      el("li", { textContent: `쓰지 않은 내용 · ${r.name}: ${r.tmi} (${r.reason})` })));
  }

  // 조사 항목의 근거 상태(서버 app/research.py)는 화면에 배지로 표시하지 않습니다. 값이 없는 항목의 설명 문장만 씁니다
  const EMPTY_STATES = ["not_searched", "not_found", "failed", "blocked", "missing"];
  const EMPTY_TEXT = {
    not_searched: "이번 조사에서 찾아보지 않았어요",
    not_found: "찾아봤지만 읽은 출처에 이 정보가 없었어요",
    failed: "검색이나 페이지 읽기에 실패해 확인하지 못했어요",
    blocked: "사이트 접근 제한(자동 접근 금지·요청 대기·접근 거부)으로 확인하지 못했어요",
    missing: "찾지 못했어요",
  };
  const ATTEMPT_TEXT = { read: "읽음", failed: "읽기 실패", blocked: "접근 제한", unknown: "조회 기록 없음" };

  function sourceLinksOf(ids) {
    return ids.map((id) => job.research.sources.find((s) => s.id === id)).filter(Boolean).map(sourceLink);
  }

  // 조사 항목에서 "카드에서 입력"을 누르면 그 항목을 쓰는 카드의 편집 화면을 엽니다
  function jumpToItem(itemKey) {
    for (const card of job.outline.cards) {
      const field = templateFor(card.frame).fields.find((f) => f.item === itemKey);
      if (!field) continue;
      goToStep(3, false); // goToStep이 편집 상태를 지우므로 먼저 이동한 뒤 편집을 엽니다
      editingFrame = card.frame;
      outlineDraft = null;
      renderOutline();
      updateApprovalControls();
      const input = $("outline-list").querySelector(`[data-editor='${card.frame}'] [name^='field-${field.key}']`);
      if (input) {
        input.scrollIntoView({ block: "center" });
        input.focus();
      }
      return;
    }
  }

  // 정보별 근거: 어느 페이지에서 언제 확인했는지, 페이지를 실제로 읽었는지, 근거 문장을 검증했는지(아직 안 함)를 따로 보여 줍니다
  function evidenceLine(record) {
    const link = /^https?:\/\//.test(record.url) ? el("a", { href: record.url, target: "_blank", rel: "noopener noreferrer", textContent: record.title || record.url }) : el("span", { textContent: record.title || record.sourceId });
    // 출처 종류 · 원문 게시일 · 조사일 · 원문을 읽었는지(검색 결과만인지)를 구분해 보여 줍니다
    const kind = record.verification === "user_provided" ? "사용자 제공" : record.verification === "image" ? "상세 이미지"
      : record.kind === "official" ? "공식" : "2차 자료";
    const parts = [kind, record.publishedAt ? `원문 게시일 ${record.publishedAt}` : "", record.at ? `조사일 ${record.at.slice(0, 10)}` : "",
      record.verification === "search_result" ? "검색 결과만 · 원문 미확인 (서버가 검색 결과 원문을 확인할 수 없어요)" : ""].filter(Boolean);
    return el("span", { class: "evidence" }, link, ` · ${parts.join(" · ")}`);
  }

  function renderChecklist(research) {
    const items = research.items || [];
    $("research-checklist-wrap").hidden = !items.length;
    const editable = isTemplateJob() && job.outline && ["waiting_outline", "waiting_preview", "done"].includes(job.state);
    $("research-checklist").replaceChildren(...items.map((item) => {
      const empty = EMPTY_STATES.includes(item.state);
      const detail = el("div", { class: "item-detail" }, el("span", { textContent: item.value || EMPTY_TEXT[item.state] || "찾지 못했어요" }));
      if (item.quote) detail.append(el("q", { textContent: item.quote }));
      const coverage = item.coverage;
      if (coverage && coverage.review) {
        // 충분성: 일부만 조사됐거나 전체 규모를 알 수 없음 → 사용자 검토 (개수를 강제하지 않음)
        detail.append(el("span", { class: "item-coverage" }, coverage.level === "partial" ? "일부만 확인됐어요" : "모두 조사됐는지 확인이 필요해요",
          coverage.note ? ` (${coverage.note})` : ""));
      }
      if ((item.evidence || []).length) {
        detail.append(el("span", { class: "evidence-list" }, "근거: ", ...item.evidence.flatMap((r, i) => (i ? [" / ", evidenceLine(r)] : [evidenceLine(r)]))));
      } else {
        const links = sourceLinksOf(item.sourceIds || []);
        if (links.length) detail.append(el("span", {}, "출처: ", ...links.flatMap((a, i) => (i ? [", ", a] : [a]))));
      }
      const checked = ((item.attempts || {}).checked || []);
      if (empty && checked.length) {
        detail.append(el("span", { class: "item-attempts" }, "확인한 페이지: ", ...checked.flatMap((c, i) => [i ? ", " : "", `${c.url.replace(/^https?:\/\//, "").slice(0, 60)} (${ATTEMPT_TEXT[c.result] || c.result})`])));
      }
      const reviewing = job.state === "waiting_research";
      const note = supplementNote(item);
      if (note) detail.append(el("span", { class: "item-supplement" }, note));
      const aux = auxNote(item, research.sources);
      if (aux) detail.append(el("span", { class: "item-supplement", dataset: { aux: item.key } }, aux));
      if (reviewing && item.savedConflict) {
        detail.append(conflictChooser(item));
      } else {
        for (const alt of item.alternatives || []) {
          detail.append(el("span", {}, `다른 값: ${alt.value} `, ...sourceLinksOf(alt.sourceIds || [])));
        }
      }
      for (const entry of item.unclear || []) {
        // 상세 이미지에서 읽기 어려웠던 값: 추측하지 않고 확인을 요청합니다
        detail.append(el("span", { class: "item-unclear" }, `이미지에서 읽기 어려움${entry.quote ? ` ("${entry.quote}")` : ""} · 확인 필요 `, ...sourceLinksOf(entry.sourceIds || [])));
      }
      const needs = [...EMPTY_STATES, "conflict", "unverified", "listed"].includes(item.state) || (item.strict && item.state === "secondary");
      const used = editable && job.outline.cards.some((c) => templateFor(c.frame).fields.some((f) => f.item === item.key));
      if (needs && used) detail.append(el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "카드에서 입력", dataset: { jumpItem: item.key }, onclick: () => jumpToItem(item.key) }));
      if (reviewing) detail.append(reviewEditor(item));
      // 자료 상태 배지는 화면에 표시하지 않습니다 (분류·검증 값은 data-state와 조사 데이터에 그대로 둠)
      return el("li", { dataset: { item: item.key, state: item.state } }, el("b", { textContent: item.label }), detail);
    }));
  }

  // ---------- '저장된 자료 사용': 보완 조사 결과 검토 ----------
  let reviewEditing = "";  // 직접 수정 중인 조사 항목

  function supplementNote(item) {
    return [savedSupplementNote(item), moreNote(item)].filter(Boolean).join(" ");
  }

  function savedSupplementNote(item) {
    if (item.userEdited) return "검토 중에 직접 수정한 값이에요.";
    if (item.chosen === "supplement") return "기존 자료와 달라서 추가 조사 값을 골랐어요.";
    if (item.chosen === "saved") return "기존 자료와 달라서 기존 값을 골랐어요.";
    return {
      added: "추가 조사로 새로 찾은 내용이에요.",
      extended: `추가 조사로 내용이 늘었어요 (기존: ${item.previousValue || ""}).`,
      confirmed: "추가 조사에서도 같은 내용을 확인했어요.",
    }[item.supplement] || "";
  }

  function conflictChooser(item) {
    const options = [{ value: item.value, sourceIds: item.sourceIds, label: "기존 자료" }, ...(item.alternatives || []).map((a) => ({ ...a, label: altLabel(a) }))];
    return el("div", { class: "review-conflict", dataset: { conflict: item.key } },
      el("p", { class: "review-conflict-note", textContent: "기존 자료와 추가 조사 값이 달라요. 어느 값을 쓸지 골라 주세요. 고르지 않은 값도 기록에 남아요." }),
      ...options.map((option, index) => el("div", { class: "review-option" },
        el("span", {}, el("b", { textContent: `${option.label}: ` }), option.value, " ", ...sourceLinksOf(option.sourceIds || [])),
        el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "이 값 사용", dataset: { choose: `${item.key}:${index}` },
          onclick: () => action(`research/items/${item.key}/choose`, jsonInit("POST", { index })) }))));
  }

  function reviewEditor(item) {
    if (reviewEditing !== item.key) {
      return el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "직접 수정", dataset: { editItem: item.key },
        onclick: () => { reviewEditing = item.key; renderResearch(); } });
    }
    const input = el("input", { type: "text", value: item.value || "", maxLength: 200, "aria-label": `${item.label} 값`, dataset: { itemInput: item.key } });
    const save = () => { reviewEditing = ""; action(`research/items/${item.key}`, jsonInit("PUT", { value: input.value })); };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); save(); }
      if (e.key === "Escape") { reviewEditing = ""; renderResearch(); }
    });
    setTimeout(() => input.focus());
    return el("div", { class: "review-edit" }, input,
      el("div", { class: "library-actions" },
        el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "저장", dataset: { saveItem: item.key }, onclick: save }),
        el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "취소", onclick: () => { reviewEditing = ""; renderResearch(); } })),
      el("small", { class: "hint", textContent: "직접 고친 값은 '사용자 제공' 자료로 기록되고, 이전 값도 기록에 남아요. 비우면 이 항목을 쓰지 않아요." }));
  }

  function renderReview(research) {
    const box = $("research-review");
    const supplement = research.supplement;
    const reviewing = job.state === "waiting_research";
    box.hidden = !(supplement && reviewing);
    if (box.hidden) return;
    const base = supplement.base || {};
    const name = base.name ? `'${base.name}'(#${base.number})` : `#${base.number}(조사일 ${base.researchedAt})`;
    const conflicts = (research.items || []).filter((i) => i.savedConflict).length;
    const parts = [];
    if (supplement.failed) {
      parts.push(el("p", { class: "notice", role: "alert", textContent: `추가 조사에 실패했어요: ${supplement.error} 기존 자료 ${name}는 그대로 있어요. 기존 자료로 계속하거나 다시 시도할 수 있어요.` }));
    } else {
      const counts = [["새로 찾은 항목", supplement.added], ["내용이 늘어난 항목", supplement.extended], ["같은 내용을 확인한 항목", supplement.confirmed]]
        .filter(([, list]) => (list || []).length).map(([label, list]) => `${label} ${list.length}개`);
      parts.push(el("p", { class: "review-summary", textContent: `저장된 자료 ${name}를 바탕으로 부족한 내용을 추가 조사해 합쳤어요.${counts.length ? ` ${counts.join(" · ")}.` : " 새로 찾은 내용은 없어요."} 기존 값은 지우지 않았어요.` }));
    }
    if (conflicts) parts.push(el("p", { class: "review-conflict-note", textContent: `기존 자료와 추가 조사 값이 다른 항목이 ${conflicts}개 있어요. 아래 조사 항목에서 쓸 값을 골라 주세요.` }));
    parts.push(el("div", { class: "actions" },
      el("button", { class: "btn btn-primary", type: "button", textContent: "이 자료로 구성안 만들기", dataset: { approveResearch: "" },
        onclick: () => {
          const left = (job.research.items || []).filter((i) => i.savedConflict).length;
          if (left && !confirm(`아직 고르지 않은 다른 값이 ${left}개 있어요. 그 항목은 기존 값을 기준으로 쓰고 '확인 필요'로 남겨요. 구성안을 만들까요?`)) return;
          action("research/approve");
        } }),
      supplement.failed ? el("button", { class: "btn btn-ghost", type: "button", textContent: "추가 조사 다시 시도", dataset: { retrySupplement: "" },
        onclick: () => action("research/supplement-retry") }) : ""));
    parts.push(el("small", { class: "hint", textContent: "구성안을 만들면 이 통합 자료가 새 조사 버전으로 저장돼요. 바탕이 된 저장 버전은 그대로 남아요." }));
    box.replaceChildren(el("h3", { class: "sub-title", textContent: "통합된 자료 검토" }), ...parts);
  }

  // ---------- 조사 결과 화면의 '추가 조사' (초안 → 통합 / 버리기) ----------
  const MORE_STATES = ["waiting_research", "waiting_outline", "waiting_material"];
  const MORE_MAX = 300;
  let moreText = "";  // 다시 그려도 입력 중인 내용을 잃지 않게 둡니다
  const moreAvailable = () => Boolean(options && (options.features || []).includes("moreResearch"));
  const MORE_RESULT = { added: "새로 찾은 항목", extended: "내용이 늘어난 항목", confirmed: "다른 출처에서도 확인한 항목", conflicts: "기존 값과 다른 항목" };

  // ---------- 보조 출처(나무위키)와 공식 확인 구분 ----------
  const NOTES_KIND_TEXT = { "": "사용자 제공", official: "사용자 제공 · 공식 출처라고 입력, 검증 안 됨", namuwiki: "사용자 제공 · 나무위키(보조 출처)", other: "사용자 제공 · 기타 출처" };

  function sourceNote(source) {
    const parts = [];
    if (source.auxiliary) parts.push(source.auxiliary.label);
    if (source.verification === "mirror") parts.push("미러 사이트라 근거로 쓰지 않음");
    if (source.verification === "user_provided") parts.push("사용자 제공");
    if (source.userKind === "official") parts.push("공식 출처라고 입력 · 검증 안 됨");
    return parts.length ? el("span", { class: "more-round", textContent: ` · ${parts.join(" · ")}` }) : "";
  }

  function auxNote(item, sources) {
    if (!item.value) return "";
    const aux = (item.sourceIds || []).map((id) => sources.find((s) => s.id === id)).filter((s) => s && s.auxiliary);
    if (!aux.length) return "";
    const label = aux[0].auxiliary.label;
    if (item.state === "verified") return `공식 확인 · ${label}도 참고`;
    if (item.state === "conflict") return `${label}와 다른 출처의 값이 달라요`;
    return `${label} 근거 (2차 자료)`;
  }

  function roundTag(round) {
    return round ? el("span", { class: "more-round", textContent: ` · 추가 조사 ${round}회차` }) : "";
  }

  function altLabel(alt) {
    if (alt.origin === "more") return `추가 조사 ${alt.round}회차`;
    return alt.origin === "supplement" ? "추가 조사" : "다른 출처";
  }

  function moreNote(item) {
    if (!item.moreRound) return "";
    const head = `추가 조사 ${item.moreRound}회차:`;
    if (item.moreChosen === "more") return `${head} 기존 자료와 달라서 추가 조사 값을 골랐어요.`;
    if (item.moreChosen === "saved") return `${head} 기존 자료와 달라서 기존 값을 골랐어요.`;
    return {
      added: `${head} 새로 찾은 내용이에요.`,
      extended: `${head} 내용이 늘었어요 (기존: ${item.previousValue || ""}).`,
      confirmed: `${head} 같은 내용을 다른 출처에서도 확인했어요.`,
      conflicts: `${head} 기존 값과 다른 값을 찾았어요.`,
    }[item.moreResult] || "";
  }

  function draftLinks(ids, sources) {
    return (ids || []).map((id) => sources.find((s) => s.id === id)).filter(Boolean).map((s) => el("span", {}, " ", sourceLink(s), sourceNote(s), roundTag(s.round)));
  }

  function renderMore(research) {
    const box = $("research-more");
    const approved = job.outline && job.outline.approved;
    box.hidden = !(research && isTemplateJob() && MORE_STATES.includes(job.state) && !approved);
    if (box.hidden) return;
    const title = el("h3", { class: "sub-title", textContent: "추가 조사" });
    if (job.mode !== "ai") {
      // 데모 작업: 기능을 끄고 안내만 보여 줍니다
      box.replaceChildren(title, el("p", { class: "review-summary", dataset: { moreDisabled: "" }, textContent: "추가 조사는 실제 AI 모드에서만 쓸 수 있어요. 데모 작업에서는 쓸 수 없어요." }));
      return;
    }
    if (!moreAvailable()) {
      box.replaceChildren(title, el("p", { class: "review-summary", textContent: "서버가 예전 코드로 실행 중이라 추가 조사를 쓸 수 없어요. 서버 창(run.bat)을 닫고 다시 실행한 뒤 새로고침해 주세요." }));
      return;
    }
    const draft = job.researchDraft;
    box.replaceChildren(title, ...(draft ? moreDraftParts(draft) : moreRequestParts()));
  }

  function moreRequestParts() {
    const parts = [];
    const updated = job.outline && job.outline.researchUpdated;
    if (updated) {
      parts.push(el("p", { class: "notice", dataset: { moreUpdated: "" },
        textContent: `추가 조사 ${updated.round}회차 결과를 조사 자료에 통합했어요. 지금 구성안은 바꾸지 않았어요. 통합된 자료로 문구를 다시 쓰려면 구성안의 '전체 구성안 다시 만들기'를 눌러 주세요.` }));
    }
    const input = el("textarea", { rows: 2, maxLength: MORE_MAX, placeholder: "예: 굿즈 판매처와 가격, 캐릭터의 생일을 더 찾아 줘", "aria-label": "추가로 조사할 내용", dataset: { moreInput: "" } });
    input.value = moreText;
    const count = el("small", { class: "hint", textContent: `${moreText.length}/${MORE_MAX}` });
    input.addEventListener("input", () => { moreText = input.value; count.textContent = `${moreText.length}/${MORE_MAX}`; });
    const button = el("button", { class: "btn btn-ghost", type: "button", textContent: "추가 조사", dataset: { moreRequest: "" },
      onclick: () => {
        const text = input.value.trim();
        if (text.length < 2) { show("action-error", "추가로 조사할 내용을 적어 주세요"); return; }
        if (!confirm("적은 내용을 AI가 웹에서 추가 조사해요. Pro 사용 한도가 차감돼요. 진행할까요?")) return;
        moreText = "";
        action("research/more", jsonInit("POST", { request: text }));
      } });
    parts.push(el("p", { class: "review-summary", textContent: "부족한 내용이 있으면 적어 주세요. 지금 자료를 참고해 적은 내용만 더 찾아요. 결과는 따로 보여 주고, '통합'을 눌러야 조사 자료에 들어가요. 지금 자료와 구성안은 그대로예요." }),
      input, count, el("div", { class: "actions" }, button));
    return parts;
  }

  function moreDraftParts(draft) {
    const research = draft.research;
    const summary = draft.summary || {};
    const round = draft.round;
    const items = (research.items || []).filter((i) => i.moreRound === round);
    const conflicts = items.filter((i) => i.savedConflict);
    const counts = Object.entries(MORE_RESULT).map(([key, label]) => [label, (summary[key] || []).length]).filter(([, n]) => n)
      .map(([label, n]) => `${label} ${n}개`);
    const newSources = (research.sources || []).filter((s) => s.round === round);
    const newFacts = (research.facts || []).filter((f) => f.round === round);
    const newPeople = ((research.peopleResearch || {}).people || []).filter((p) => p.round === round);
    const parts = [el("p", { class: "review-summary", dataset: { moreDraft: String(round) } },
      el("b", { textContent: `추가 조사 ${round}회차 결과 (아직 통합 전)` }), ` · 요청: “${draft.request}” · `,
      `${counts.length ? counts.join(" · ") : "조사 항목에 새로 더한 내용은 없어요"} · 새 출처 ${newSources.length}개 · 새 사실 ${newFacts.length}개`)];
    if (items.length) {
      parts.push(el("ul", { class: "research-checklist" }, ...items.map((item) => {
        const detail = el("div", { class: "item-detail" }, el("span", { textContent: item.value }));
        if (item.quote) detail.append(el("q", { textContent: item.quote }));
        detail.append(el("span", { class: "item-supplement", textContent: moreNote(item) }));
        const aux = auxNote(item, research.sources);
        if (aux) detail.append(el("span", { class: "item-supplement", textContent: aux }));
        if (item.savedConflict) {
          const options = [{ value: item.value, sourceIds: item.sourceIds, label: "기존 자료" }, ...(item.alternatives || []).map((a) => ({ ...a, label: altLabel(a) }))];
          detail.append(el("div", { class: "review-conflict", dataset: { moreConflict: item.key } },
            el("p", { class: "review-conflict-note", textContent: "기존 값과 추가 조사 값이 달라요. 어느 값을 쓸지 골라 주세요. 고르지 않은 값도 기록에 남아요." }),
            ...options.map((option, index) => el("div", { class: "review-option" },
              el("span", {}, el("b", { textContent: `${option.label}: ` }), option.value, ...draftLinks(option.sourceIds, research.sources)),
              el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "이 값 사용", dataset: { moreChoose: `${item.key}:${index}` },
                onclick: () => action(`research/more/items/${item.key}/choose`, jsonInit("POST", { index })) })))));
        } else {
          detail.append(el("span", {}, "출처:", ...draftLinks(item.sourceIds, research.sources)));
        }
        return el("li", { dataset: { item: item.key } }, el("b", { textContent: item.label }), detail);
      })));
    }
    if (newPeople.length) {
      parts.push(el("ul", { class: "research-people" }, ...newPeople.map((p) => el("li", {},
        el("b", { textContent: p.name }), ` TMI: ${p.tmi || "찾지 못했어요"}`, ...draftLinks(p.sourceIds, research.sources)))));
    }
    if (newSources.length) {
      parts.push(el("h4", { class: "sub-title", textContent: "이번에 새로 쓴 출처" }),
        el("ul", { class: "research-sources" }, ...newSources.map((s) => el("li", { dataset: { verification: s.verification, kind: s.kind || "" } }, sourceLink(s), sourceNote(s), roundTag(round)))));
    }
    if (newFacts.length) {
      parts.push(el("details", { class: "research-facts" }, el("summary", { textContent: `새로 찾은 사실 ${newFacts.length}개 보기` }),
        el("ul", {}, ...newFacts.map((f) => el("li", {}, f.text, ...draftLinks(f.sourceIds, research.sources))))));
    }
    if (conflicts.length) parts.push(el("p", { class: "review-conflict-note", textContent: `기존 값과 다른 항목이 ${conflicts.length}개 있어요. 쓸 값을 고른 뒤 통합할 수 있어요.` }));
    parts.push(el("div", { class: "actions" },
      el("button", { class: "btn btn-primary", type: "button", textContent: "통합", dataset: { moreAccept: "" }, onclick: () => action("research/more/accept") }),
      el("button", { class: "btn btn-ghost", type: "button", textContent: "버리기", dataset: { moreDiscard: "" },
        onclick: () => { if (confirm("이번 추가 조사 결과를 버릴까요? 지금 조사 자료와 구성안은 그대로예요.")) action("research/more/discard"); } })));
    parts.push(el("small", { class: "hint", textContent: job.state === "waiting_research"
      ? "통합하면 검토 중인 자료에 들어가고, '이 자료로 구성안 만들기'를 누를 때 새 조사 버전으로 저장돼요."
      : "통합하면 조사 자료가 새 버전으로 저장되고 이전 버전은 그대로 남아요. 지금 구성안은 바뀌지 않아요." }));
    return parts;
  }

  function renderProblems(research) {
    const problems = [
      ...(research.policyStops || []).map((s) => `${s.name}: 이용규약상 자동 수집이 금지된 사이트라 읽지 않았어요`),
      ...(research.searchFailures || []).map((f) => `검색 "${f.query}": ${f.reason}${f.detail ? ` (오류 내용: ${f.detail})` : ""}`),
      ...(research.fetchFailures || []).map(failureText),
      ...(research.fetched || []).filter((f) => f.denied).map(deniedText),
    ];
    $("research-problems-wrap").hidden = !problems.length;
    $("research-problems").replaceChildren(...problems.map((text) => el("li", { textContent: text })));
  }

  function failureText(failure) {
    const reason = failure.label || "접속하지 못했어요";
    const code = failure.code ? ` (HTTP ${failure.code})` : "";
    return `${failure.host}: ${reason}${code}${failure.detail ? ` (오류 내용: ${failure.detail})` : ""}, ${failure.attempts}번 시도`;
  }

  // 우리 차단 규칙(금지 사이트·대기 중 사이트)일 때만 "접근 제한 규칙"이라고 씁니다.
  // rule이 없는 예전 기록은 금지 사이트 목록으로 판단하고, 아니면 읽기 실패로 보여 줍니다
  function deniedText(fetch) {
    const host = (() => { try { return new URL(fetch.url).hostname.replace(/^www\./, ""); } catch { return ""; } })();
    const restricted = (options.restrictedSites || []).some((s) => host === s.domain || host.endsWith(`.${s.domain}`));
    if (fetch.rule || restricted) return `${fetch.url}: 접근 제한 규칙으로 요청하지 않았어요`;
    return `${fetch.url}: 읽기 실패 (오류 내용: ${fetch.detail || "기록되지 않았어요"})`;
  }

  function renderMaterial() {
    const noOutline = !job.outline;
    const open = job.mode === "ai" && viewStep === 2 && !(job.outline && job.outline.approved) &&
      (job.state === "waiting_material" || job.state === "waiting_outline" || (noOutline && ["failed", "interrupted"].includes(job.state)));
    $("material").hidden = !open;
    if (!open) return;
    const research = job.research;
    const failures = (research && research.fetchFailures) || [];
    const blocked = failures.some((f) => f.blocked);
    const stop = ((research && research.policyStops) || [])[0];
    let reason = "조사한 내용에 더하고 싶은 자료가 있으면 입력해 주세요. 지금 구성안은 새로 만들어져요.";
    if (job.state !== "waiting_outline") {
      reason = stop
        ? `${stop.name}은 이용규약상 허가 없는 자동 수집이 금지되어 있어 자동으로 읽지 않았어요. 브라우저에서 페이지를 직접 열어 확인한 내용을 입력하거나 붙여 넣어 주세요.`
        : blocked
          ? "공식 사이트가 요청을 막아 내용을 읽지 못했어요. Claude 사용 한도 문제가 아니에요. 자료를 입력하면 이어서 진행할 수 있어요."
          : "자동 조사만으로는 자료가 부족해요. 자료를 입력하면 이어서 진행할 수 있어요.";
    }
    const stage = job.researchStage || {};
    const waiting = job.state === "waiting_material";
    if (waiting && stage.done && !stop && !blocked) reason = "자동 조사는 끝났지만 확인된 자료가 부족해요. 지금 자료로 구성안을 쓰거나, 자료를 보완해 주세요.";
    $("material-reason").textContent = reason;
    const missing = (research && research.missing) || [];
    const gapRows = ((job.researchGap || {}).rows) || [];
    gapBox($("material-gap"), waiting ? job.researchGap : null, "부족한 정보", waiting && !gapRows.length && missing.length ? "AI가 적은 부족한 내용을 아래에서 확인해 주세요." : "");
    $("material-failures").replaceChildren(
      ...failures.map((f) => el("li", { textContent: failureText(f) })),
      ...(job.state === "waiting_outline" ? [] : missing.map((m) => el("li", { textContent: `AI가 적은 부족한 내용: ${m}` }))),
    );
    // 두 가지 선택: 현재 자료로 구성안 작성 / 자료 보완하기 (조사를 다시 하지 않음)
    const usable = research && ((research.facts || []).length || (research.items || []).some((i) => i.value));
    // 조사 자료가 있으면 예전에 멈춘 작업도 고를 수 있어요 (조사 완료 기록이 없던 작업 포함). 금지 사이트라 조사하지 않은 작업은 자료 입력으로
    $("material-choice").hidden = !(waiting && (stage.done || usable) && !stop);
    const legacy = !(isTemplateJob() && job.templateSet);  // 예전 형식 작업(유형별 5장 템플릿 이전)은 조사와 구성안이 나뉘지 않아 이 기능을 쓸 수 없어요
    $("material-compose").disabled = legacy || !usable || Boolean(job.researchDraft);
    $("material-compose").dataset.locked = $("material-compose").disabled ? "true" : "";
    $("material-compose-note").textContent = legacy ? "예전 형식으로 만든 작업이라 '현재 자료로 구성안 작성'을 쓸 수 없어요. 아래에 자료를 입력하거나 새 카드뉴스로 만들어 주세요."
      : !usable ? "조사된 자료가 없어 지금은 구성안을 쓸 수 없어요. 자료를 입력하거나 추가 조사를 해 주세요."
      : job.researchDraft ? "추가 조사 결과를 먼저 '통합' 또는 '버리기' 해 주세요."
      : "다시 검색하지 않고 지금 자료로 구성안을 써요 (AI 1회). 찾지 못한 정보는 비워 두고, 지어내지 않아요.";
    const labels = MATERIAL_LABELS[job.contentType] || { name: "이름", price: "가격", seller: "판매처·출처", features: "특징·내용" };
    for (const [key, text] of Object.entries(labels)) $(`material-${key}-label`).textContent = text;
    const guide = MATERIAL_GUIDES[job.contentType] || MATERIAL_GUIDES.goods;
    $("material-guide").textContent = guide.guide;
    const form = $("material-form");
    form.elements.extra.placeholder = guide.example;
    const saved = job.userMaterial || {};
    if (form.dataset.job !== job.id) {
      form.dataset.job = job.id;
      for (const key of ["name", "price", "seller", "features", "extra"]) form.elements[key].value = saved[key] || "";
      // 예전 화면의 URL·붙여 넣기 칸은 첫 출처 묶음으로 옮깁니다
      const blocks = [...(saved.sourceUrl || saved.pasted ? [{ url: saved.sourceUrl || "", kind: saved.sourceKind || "", text: saved.pasted || "" }] : []), ...(saved.sources || [])];
      if (!blocks.length && (blocked || stop) && job.url) blocks.push({ url: job.url, kind: "official", text: "" });
      setMaterialSources(blocks.slice(0, SOURCE_MAX));
      form.querySelector(".material-details").open = ["name", "price", "seller", "features"].some((k) => saved[k]);
    }
    const until = research ? research.retryAfter || 0 : 0;
    const wait = Math.max(0, until - Date.now() / 1000);
    const canRetry = job.state === "waiting_material" && wait <= 0;
    $("material-retry").hidden = job.state !== "waiting_material";
    $("material-retry").textContent = stop ? "다른 공식 출처에서 자동 조사" : "자동 조사 다시 시도";
    $("material-retry").disabled = !canRetry;
    $("material-retry").dataset.locked = canRetry ? "" : "true";
    $("material-wait").textContent = job.state === "waiting_material" && wait > 0
      ? `사이트에 부담을 주지 않도록 약 ${Math.ceil(wait / 60)}분 뒤에 자동 조사를 다시 시도할 수 있어요. 새로 고침하면 시간이 갱신돼요.`
      : stop && job.state === "waiting_material" ? `${stop.name}에는 접속하지 않고 다른 사이트만 조사해요. Pro 사용 한도가 차감돼요.` : "";
  }

  // 출처 묶음 (URL · 출처 종류 · 복사한 내용), 최대 3개
  function materialSourceRow(block) {
    const kind = el("select", { name: "src-kind", "aria-label": "출처 종류" }, ...NOTE_KINDS.map(([v, t]) => el("option", { value: v, textContent: t, selected: (block.kind || "") === v })));
    const row = el("div", { class: "material-source" },
      el("input", { type: "url", name: "src-url", inputmode: "url", placeholder: "https:// (공식 페이지 주소)", value: block.url || "", "aria-label": "출처 주소" }),
      kind,
      el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "삭제", onclick: () => { row.remove(); syncSourceAdd(); } }),
      el("textarea", { name: "src-text", rows: 3, maxlength: 4000, placeholder: "이 페이지에서 복사한 내용 (선택)", value: block.text || "", "aria-label": "복사한 내용" }));
    return row;
  }

  function syncSourceAdd() {
    $("material-source-add").disabled = $("material-sources").children.length >= SOURCE_MAX;
  }

  function setMaterialSources(blocks) {
    $("material-sources").replaceChildren(...blocks.map(materialSourceRow));
    syncSourceAdd();
  }

  function collectSources() {
    return [...$("material-sources").children].map((row) => ({
      url: row.querySelector("[name=src-url]").value.trim(), kind: row.querySelector("[name=src-kind]").value, text: row.querySelector("[name=src-text]").value.trim(),
    })).filter((b) => b.url || b.text);
  }

  async function submitMaterial(event) {
    event.preventDefault();
    const form = $("material-form");
    const body = { sources: collectSources() };
    for (const key of ["extra", "name", "price", "seller", "features"]) body[key] = form.elements[key].value.trim();
    show("material-error", "");
    const filled = body.sources.length || ["extra", "name", "price", "seller", "features"].some((k) => body[k]);
    if (!filled && !(job.detailImages || []).length) {
      show("material-error", "알려 주고 싶은 정보를 적거나, 출처 내용을 붙여 넣거나, 아래에서 상세페이지 이미지를 올려 주세요.");
      return;
    }
    if (job.state === "waiting_outline" && !confirm("지금 구성안을 새로 만들어요. 직접 수정한 내용도 바뀌어요. 진행할까요?")) return;
    try {
      await setJob(await api(`/api/jobs/${job.id}/material`, jsonInit("POST", body)));
    } catch (error) {
      show("material-error", error.message);
    }
  }

  // ---------- 상세페이지 이미지 (자료 조사용) ----------
  // 카드에 넣는 이미지(이미지 준비)와 따로 둡니다. AI가 상품 정보를 읽는 자료로만 씁니다.
  const DETAIL_STATES = ["draft", "waiting_material", "waiting_outline", "failed", "interrupted"];
  const detailUrl = (imageId) => `/api/jobs/${job.id}/detail-images/${imageId}`;
  const extractionStale = () => {
    const ids = (job.detailImages || []).map((i) => i.id);
    const done = job.detailExtraction && job.detailExtraction.status === "done";
    return ids.length > 0 && (!done || JSON.stringify(job.detailExtraction.imageIds) !== JSON.stringify(ids));
  };

  function detailEditable() {
    return !job || (DETAIL_STATES.includes(job.state) && !(job.outline && job.outline.approved) && !job.aiTask);
  }

  function renderDetail() {
    const step1 = viewStep === 1 && (!job || job.state === "draft");
    const images = job ? job.detailImages || [] : [];
    const open = step1 || !$("material").hidden || (viewStep === 2 && images.length > 0);
    $("detail-panel").hidden = !open;
    if (!open) return;
    const editable = detailEditable();
    $("detail-upload").disabled = !editable;
    $("detail-files").disabled = !editable;

    const url = job && job.state !== "draft" ? job.url : $("url").value.trim();
    const restricted = url && restrictedSiteOf(url);
    $("detail-fetch").hidden = !url;
    $("detail-fetch").disabled = !editable || Boolean(restricted);
    const note = $("detail-fetch-note");
    note.hidden = !url;
    note.textContent = restricted
      ? `${restricted.name}은 이용규약상 자동 수집이 금지되어 있어 이미지를 자동으로 받지 않아요. 브라우저에서 상세페이지를 직접 캡처해 올려 주세요.`
      : "누를 때만 그 페이지 한 곳에 요청해요. 자동 수집 금지 사이트, robots.txt가 막은 주소, 요청을 막은 사이트에는 요청하지 않아요. 자바스크립트로 그리는 상세 영역은 찾지 못할 수 있어요.";

    $("detail-list").replaceChildren(...images.map((image) => el("li", { dataset: { detail: image.id } },
      el("a", { href: detailUrl(image.id), target: "_blank", rel: "noopener" }, el("img", { src: detailUrl(image.id), alt: `${image.name} 상세 이미지`, loading: "lazy" })),
      el("span", { class: "image-name", textContent: image.name, title: image.imageUrl || image.name }),
      tag(image.origin === "page" ? "페이지에서 받음" : "직접 올림", image.origin === "page" ? "demo" : "real"),
      el("button", { class: "remove", type: "button", textContent: "빼기", disabled: !editable, "aria-label": `${image.name} 빼기`,
        onclick: () => detailAction(`detail-images/${image.id}`, { method: "DELETE" }) }))));

    const report = job && job.detailFetch;
    $("detail-report").replaceChildren(...(report ? [
      el("li", { textContent: `참고 URL에서 상세 이미지 ${report.found}장을 받았어요${report.found ? "" : ". 페이지가 이미지를 자바스크립트로 불러오면 찾지 못해요. 스크린샷을 올려 주세요"}` }),
      ...report.failures.map((f) => el("li", { textContent: `${f.host}: ${f.label} (HTTP ${f.code})` })),
      ...report.skipped.slice(0, 5).map((text) => el("li", { textContent: `요청하지 않음: ${text}` })),
    ] : []));

    const ai = job && job.mode === "ai" && job.state !== "draft";
    $("detail-extract").hidden = !(ai && images.length);
    $("detail-extract").disabled = !editable;
    const stale = job && extractionStale();
    $("detail-hint").textContent = !images.length ? ""
      : !ai ? "실제 AI 모드로 제작을 시작하면 자료 조사 전에 AI가 이 이미지를 먼저 읽어요. 데모 모드에서는 읽지 않아요."
        : stale ? "새 이미지가 있어요. '이미지에서 정보 읽기'를 누르거나, 위의 '이 자료로 구성안 만들기'를 누르면 함께 읽어요. Pro 한도가 1회 차감돼요."
          : "읽은 정보는 '이 자료로 구성안 만들기'를 누르면 구성안에 반영돼요. 페이지 내용과 다르면 출처 충돌로 표시돼 직접 확인하게 돼요.";
    renderExtraction();
  }

  function renderExtraction() {
    const extraction = job && job.detailExtraction;
    const items = (extraction && extraction.items) || [];
    $("detail-result-wrap").hidden = !items.length && !(extraction && extraction.notes && extraction.notes.length);
    if (!extraction) return;
    const refs = extraction.refs || {};
    $("detail-result").replaceChildren(...items.map((item) => {
      const detail = el("div", { class: "item-detail" });
      if (item.unclear) detail.append(el("span", { class: "item-unclear", textContent: "이미지에서 확실히 읽을 수 없어요 · 확인 필요 (카드에 쓰지 않아요). 출처 이미지를 직접 보고 입력해 주세요." }));
      else detail.append(el("span", { textContent: item.value }));
      if (item.quote) detail.append(el("q", { textContent: item.quote }));
      detail.append(el("span", {}, "출처: ", el("a", { href: detailUrl(refs[item.imageRef] || item.imageId), target: "_blank", rel: "noopener",
        textContent: `${item.imageRef} 상세 이미지${item.tile ? ` · 조각 ${item.tile}` : ""}` })));
      return el("li", { dataset: { extract: item.key, unclear: String(item.unclear) } },
        el("b", { textContent: item.label || item.key }), detail);
    }));
    $("detail-notes").replaceChildren(...(extraction.notes || []).map((text) => el("li", { textContent: text })));
  }

  async function detailAction(path, init) {
    show("detail-error", "");
    try {
      await setJob(await api(`/api/jobs/${job.id}/${path}`, init));
      return true;
    } catch (error) {
      show("detail-error", error.message);
      return false;
    }
  }

  async function uploadDetail() {
    const files = [...$("detail-files").files];
    if (!files.length) {
      show("detail-error", "올릴 이미지 파일을 골라 주세요.");
      return;
    }
    const tooBig = files.find((f) => f.size > options.limits.maxImageBytes);
    if (tooBig) {
      show("detail-error", `${tooBig.name}: 10MB 이하 이미지만 올릴 수 있어요. 길면 나눠서 캡처해 주세요.`);
      return;
    }
    try {
      await ensureDraft();
    } catch (error) {
      show("detail-error", error.message);
      return;
    }
    const data = new FormData();
    for (const file of files) data.append("images", file);
    $("detail-upload").disabled = true;
    if (await detailAction("detail-images", { method: "POST", body: data })) $("detail-files").value = "";
    $("detail-upload").disabled = false;
  }

  async function fetchDetail() {
    try {
      await ensureDraft();
      if (job.state === "draft") await saveDraftInput(); // 입력한 URL을 먼저 저장합니다
    } catch (error) {
      show("detail-error", error.message);
      return;
    }
    $("detail-fetch").disabled = true;
    $("detail-hint").textContent = "참고 URL 페이지에서 상세 이미지를 찾고 있어요.";
    await detailAction("detail-images/fetch", { method: "POST" });
    renderDetail();
  }

  function renderThemeNote() {
    const theme = job.designTheme;
    const node = $("theme-note");
    if (isTemplateJob()) {
      node.hidden = false;
      node.replaceChildren(el("b", { textContent: "고정 템플릿" }),
        el("span", { textContent: `${FRAMES.map((f) => templateFor(f).label).join(" · ")}. 디자인은 바뀌지 않고 문구와 이미지만 들어가요.` }));
      return;
    }
    node.hidden = !(theme && theme.source === "ai");
    if (node.hidden) return;
    const swatch = el("span", { class: "swatch" });
    for (const key of ["bgFrom", "accent", "accent2", "accent3"]) {
      const chip = document.createElement("i");
      chip.style.background = theme.palette[key];
      swatch.append(chip);
    }
    node.replaceChildren(swatch, el("b", { textContent: theme.label }), el("span", { textContent: theme.rationale }));
  }

  // ---------- 단계 ----------
  function maxStep() {
    if (!job || job.state === "draft") return 1;
    if (job.state === "done") return 5;
    if (job.state === "waiting_preview") return 4;
    if (job.state === "waiting_outline") return 3;
    if (job.state === "waiting_material" || job.state === "waiting_research") return 2;
    if (job.preview && job.preview.approved) return 5;
    if (job.outline && job.outline.approved) return 4;
    return job.outline ? 3 : 2;
  }

  function renderStepper() {
    const limit = maxStep();
    const list = $("stepper");
    list.replaceChildren();
    STEP_LABELS.forEach((label, i) => {
      const step = i + 1;
      const locked = step > limit;
      const state = step === viewStep ? "is-current" : step < limit || (job && job.state === "done") ? "is-done" : locked ? "is-locked" : "";
      const button = el(
        "button",
        {
          class: `step-chip ${state}`,
          type: "button",
          disabled: locked,
          title: locked ? "앞 단계를 승인하면 열려요" : "",
          dataset: { step: String(step) },
          onclick: () => goToStep(step),
        },
        el("span", { class: "step-number", textContent: String(step) }),
        el("span", { class: "step-label", textContent: label }),
      );
      if (step === viewStep) button.setAttribute("aria-current", "step");
      list.append(el("li", {}, button));
    });
  }

  function gateMessage() {
    if (viewStep < maxStep()) return "";
    if (!job || job.state === "draft") return "주제를 입력하고 제작을 시작해 주세요.";
    if (job.state === "failed" || job.state === "interrupted") return "작업이 멈췄어요. 새로 만들어 주세요.";
    if (job.state === "running") return "진행이 끝나면 넘어갈 수 있어요.";
    if (job.state === "waiting_material") return "자료를 입력하면 구성안 단계로 넘어가요.";
    if (job.state === "waiting_research") return "조사 자료를 확인하고 '이 자료로 구성안 만들기'를 누르면 구성안 단계로 넘어가요.";
    if (viewStep === 3) return "구성안을 승인하면 다음 단계로 갈 수 있어요.";
    if (viewStep === 4) return "디자인을 최종 승인하면 PNG를 받을 수 있어요.";
    return "";
  }

  function renderStepNav() {
    $("step-nav").hidden = !job;
    if (!job) return;
    $("step-prev").disabled = viewStep <= 1;
    $("step-next").disabled = viewStep >= maxStep();
    $("step-gate").textContent = gateMessage();
  }

  function goToStep(step, focus = true) {
    if (step < 1 || step > maxStep()) return;
    if (editingFrame) editingFrame = null;
    viewStep = step;
    renderView();
    if (focus) {
      const motion = matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
      window.scrollTo({ top: 0, behavior: motion });
      const heading = { 2: "progress-title", 3: "outline-title", 4: "preview-title", 5: "download-title" }[step];
      if (heading) $(heading).focus({ preventScroll: true });
    }
  }

  // ---------- 입력 ----------
  const TYPE_SOURCE_TEXT = { ai: "AI 판단", keyword: "키워드로 추정", user: "직접 선택", pending: "AI가 판단할 예정" };
  const typeLabelOf = (id) => (options.contentTypes.find((t) => t.id === id) || {}).label || "AI가 판단";

  function renderOptions() {
    // 기본값은 AI가 판단. 실제 AI 모드는 조사 전에 짧게 판단하고, 데모는 키워드로 추정합니다
    const types = [{ id: "auto", label: "AI가 판단" }, ...options.contentTypes];
    types.forEach((type, i) => {
      const input = el("input", { type: "radio", name: "contentType", value: type.id, checked: i === 0 });
      $("type-options").append(el("label", { class: "chip" }, input, el("span", { textContent: type.label })));
    });
  }

  function renderTypeSwitch() {
    const node = $("type-switch");
    const show = isTemplateJob() && ["waiting_outline", "waiting_preview", "done"].includes(job.state);
    node.hidden = !show;
    if (!show) return;
    const select = el("select", { "aria-label": "디자인 유형", dataset: { typeSelect: "" } },
      ...options.contentTypes.filter((t) => (options.templateTypes || []).includes(t.id))
        .map((t) => el("option", { value: t.id, textContent: t.label, selected: t.id === job.contentType })));
    const source = TYPE_SOURCE_TEXT[job.typeSource] || "";
    const reason = job.typeSource === "ai" && job.typeReason ? `: ${job.typeReason}` : "";
    const button = el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "이 유형으로 바꾸기", dataset: { typeApply: "" },
      onclick: () => {
        if (select.value === job.contentType) return;
        const cost = job.mode === "ai" ? "저장된 조사 결과로 카드 5장을 새 유형에 맞춰 다시 써요. Pro 한도가 1회 차감돼요. " : "카드 5장이 새 유형의 예시 내용으로 바뀌어요. ";
        if (!confirm(`${cost}직접 고친 내용과 이미지 지정, 승인이 모두 초기화돼요. 바꿀까요?`)) return;
        action("content-type", jsonInit("PUT", { contentType: select.value }));
      } });
    node.replaceChildren(el("span", { class: "type-switch-label", textContent: "디자인 유형" }), select, button,
      el("small", { class: "hint", textContent: `${typeLabelOf(job.contentType)} 템플릿 5장 · ${source}${reason}` }));
  }

  function updateTopicCount() {
    $("topic-count").textContent = `${$("topic").value.length} / ${options.limits.topicMax}자`;
  }

  // 참고 자료의 출처 종류·주소는 서버가 받을 수 있을 때만 보냅니다 (예전 서버는 모르는 필드를 거절함)
  const notesSourceAvailable = () => Boolean(options && (options.features || []).includes("notesSource"));
  const readInput = () => ({ topic: $("topic").value.trim(), contentType: $("job-form").elements.contentType.value, url: $("url").value.trim(), notes: $("notes").value.trim(),
    ...(notesSourceAvailable() ? { notesKind: $("notes-kind").value, notesUrl: $("notes-url").value.trim() } : {}) });

  function fillForm() {
    $("topic").value = job.topic;
    $("url").value = job.url;
    $("notes").value = job.notes || "";
    $("notes-kind").value = job.notesKind || "";
    $("notes-url").value = job.notesUrl || "";
    if (job.state !== "draft") {
      const modeRadio = [...$("job-form").elements.mode].find((r) => r.value === job.mode);
      if (modeRadio) modeRadio.checked = true;
    }
    const radio = [...$("job-form").elements.contentType].find((r) => r.value === job.contentType);
    if (radio) radio.checked = true;
    updateTopicCount();
  }

  async function ensureDraft() {
    if (job) return;
    job = await api("/api/jobs/draft", { method: "POST" });
    setUrl();
    await saveDraftInput();
  }

  async function saveDraftInput() {
    if (!job || job.state !== "draft") return;
    try {
      job = await api(`/api/jobs/${job.id}/input`, jsonInit("PATCH", readInput()));
    } catch {
      // 입력 중에는 형식 오류를 띄우지 않습니다. 시작할 때 다시 검사합니다.
    }
  }

  async function addFiles(files) {
    show("form-error", "");
    const valid = [];
    let count = visibleAssets().length;
    for (const file of files) {
      if (count + valid.length >= options.limits.maxImages) {
        show("form-error", `이미지는 ${options.limits.maxImages}장까지 올릴 수 있어요.`);
        break;
      }
      if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
        show("form-error", `${file.name}: PNG, JPG, WebP 이미지만 올릴 수 있어요.`);
        continue;
      }
      if (file.size > options.limits.maxImageBytes) {
        show("form-error", `${file.name}: 10MB 이하 이미지만 올릴 수 있어요.`);
        continue;
      }
      valid.push(file);
    }
    if (!valid.length) return;
    try {
      await ensureDraft();
      for (const file of valid) {
        const data = new FormData();
        data.append("image", file);
        await setJob(await api(`/api/jobs/${job.id}/assets`, { method: "POST", body: data }));
      }
    } catch (error) {
      show("form-error", error.message);
    }
    count = visibleAssets().length;
    renderView();
  }

  async function flushAssetDrafts() {
    for (const asset of visibleAssets()) {
      const draft = assetDrafts.get(asset.id);
      if (draft && draft.source.trim() !== asset.source) await saveAsset(asset.id);
    }
  }

  async function submitForm(event) {
    event.preventDefault();
    show("form-error", "");
    show("form-note", "");
    const input = readInput();
    $("topic").removeAttribute("aria-invalid");
    if (!input.topic || input.topic.length > options.limits.topicMax) {
      $("topic").setAttribute("aria-invalid", "true");
      show("form-error", input.topic ? `주제는 ${options.limits.topicMax}자 이내로 입력해 주세요.` : "주제를 입력해 주세요.");
      $("topic").focus();
      return;
    }
    $("start").disabled = true;
    $("save-input").disabled = true;
    try {
      await flushAssetDrafts();
      if (job && job.state !== "draft") {
        await setJob(await api(`/api/jobs/${job.id}/input`, jsonInit("PATCH", input)));
        show("form-note", "저장했어요. 이미 만든 구성안의 문구는 자동으로 바뀌지 않아요.");
      } else {
        await ensureDraft();
        const research = selectedMode() === "ai" && !$("research-field").hidden && selectedResearchMode() === "saved" && $("research-version")
          ? { researchMode: "saved", researchVersion: $("research-version").value } : { researchMode: "new" };
        await setJob(await api(`/api/jobs/${job.id}/start`, jsonInit("POST", { ...input, mode: selectedMode(), ...research })));
      }
    } catch (error) {
      show("form-error", error.message);
    } finally {
      $("start").disabled = false;
      $("save-input").disabled = false;
    }
  }

  // ---------- 이미지 준비 ----------
  function draftOf(asset) {
    if (!assetDrafts.has(asset.id)) assetDrafts.set(asset.id, { source: asset.source });
    return assetDrafts.get(asset.id);
  }

  async function saveAsset(assetId) {
    const draft = assetDrafts.get(assetId);
    const asset = job.assets.find((a) => a.id === assetId);
    const source = draft.source.trim();
    if (source === asset.source) return;
    try {
      // 출처만 저장합니다. 사용 권한 기록은 바꾸지 않습니다 (확인하지 않은 이미지를 '허가됨'으로 기록하지 않음)
      await setJob(await api(`/api/jobs/${job.id}/assets/${assetId}`, jsonInit("PATCH", { source })));
      show("action-error", "");
    } catch (error) {
      show("action-error", error.message);
    }
  }

  async function assetAction(path, init) {
    show("action-error", "");
    try {
      await setJob(await api(`/api/jobs/${job.id}/${path}`, init));
    } catch (error) {
      show("action-error", error.message);
    }
  }

  function figure(caption, content, extraClass = "") {
    return el("figure", { class: `image-figure ${extraClass}` }, el("figcaption", { textContent: caption }), content);
  }

  function imageCard(asset) {
    const draft = draftOf(asset);
    const info = asset.cutout;
    const original = el("img", { src: assetUrl(asset.id), alt: `${asset.name} 원본` });
    const cutoutView = hasCutout(asset)
      ? el("img", { src: assetUrl(asset.id, "cutout"), alt: `${asset.name} 배경 제거 결과` })
      : el("p", { class: "cutout-empty", textContent: isProcessing(asset) ? "처리 중이에요" : "아직 없어요" });

    const body = [
      el("div", { class: "image-card-head" },
        el("span", { class: "image-name", textContent: asset.name, title: asset.name }),
        el("button", { class: "remove", type: "button", textContent: "빼기", disabled: isProcessing(asset), "aria-label": `${asset.name} 빼기`, onclick: () => assetAction(`assets/${asset.id}`, { method: "DELETE" }) })),
      el("div", { class: "image-compare" }, figure("원본", original), figure("배경 제거", cutoutView, "is-cutout")),
    ];

    const cutoutOptions = options.cutout;
    if (cutoutOptions.available) {
      const model = el("select", { "aria-label": `${asset.name} 이미지 종류` });
      for (const m of cutoutOptions.models) {
        model.append(el("option", { value: m.id, textContent: m.label, selected: info && (info.pendingModel || info.model) === m.id }));
      }
      body.push(
        el("div", { class: "cutout-row" },
          model,
          el("button", {
            class: "btn btn-ghost btn-small",
            type: "button",
            textContent: isProcessing(asset) ? "처리 중…" : hasCutout(asset) ? "다시 처리" : "배경 제거",
            disabled: isProcessing(asset),
            dataset: { cutout: asset.id, locked: isProcessing(asset) ? "true" : "" },
            onclick: () => assetAction(`assets/${asset.id}/cutout`, jsonInit("POST", { model: model.value })),
          })),
      );
    }
    if (isProcessing(asset)) {
      body.push(el("p", { class: "cutout-status", role: "status" }, el("span", { class: "spinner", "aria-hidden": "true" }), "배경을 지우고 있어요. 수십 초 걸릴 수 있어요."));
    } else if (info && info.status === "failed") {
      body.push(el("p", { class: "cutout-error", role: "alert", textContent: `${info.error} 원본은 그대로 쓸 수 있어요.` }));
    }

    // 배경 제거 ON/OFF: 이 이미지를 쓰는 카드 자리에 함께 반영됩니다 (자리에서 원본을 직접 고른 곳은 그대로)
    const bgOn = asset.useVariant === "cutout" && hasCutout(asset);
    const canStart = options.cutout.available && !isProcessing(asset);
    body.push(
      el("div", { class: "use-row" },
        el("label", { class: "switch" },
          el("input", {
            type: "checkbox", checked: bgOn, disabled: !hasCutout(asset) && !canStart || isProcessing(asset),
            dataset: { bgToggle: asset.id, locked: isProcessing(asset) ? "true" : "" },
            onchange: (e) => {
              if (!e.target.checked) assetAction(`assets/${asset.id}`, jsonInit("PATCH", { useVariant: "original" }));
              else if (hasCutout(asset)) assetAction(`assets/${asset.id}`, jsonInit("PATCH", { useVariant: "cutout" }));
              else assetAction(`assets/${asset.id}/cutout`, jsonInit("POST", { model: (body.find((n) => n.classList && n.classList.contains("cutout-row"))?.querySelector("select") || {}).value || "auto" }));
            },
          }),
          el("span", { textContent: `배경 제거 ${bgOn ? "ON" : "OFF"}` })),
        bgOn ? el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "원본 복원", dataset: { assetRestore: asset.id },
          onclick: () => assetAction(`assets/${asset.id}`, jsonInit("PATCH", { useVariant: "original" })) }) : ""),
    );

    const source = el("input", {
      type: "text",
      value: draft.source,
      maxLength: 100,
      placeholder: "이미지 출처 (예: 직접 촬영)",
      "aria-label": `${asset.name} 출처`,
      oninput: (e) => { draft.source = e.target.value; },
      onchange: () => saveAsset(asset.id),
    });
    body.push(source);

    return el("article", { class: "image-card", dataset: { asset: asset.id } }, ...body);
  }

  function renderImages() {
    const assets = visibleAssets();
    const grid = $("image-cards");
    const ids = new Set(assets.map((a) => a.id));
    for (const child of [...grid.children]) {
      if (!ids.has(child.dataset.asset)) {
        imageCardKeys.delete(child.dataset.asset);
        assetDrafts.delete(child.dataset.asset);
        child.remove();
      }
    }
    for (const asset of assets) {
      // 저장 전 입력이 사라지지 않게 서버 값이 바뀐 카드만 다시 그립니다
      const key = JSON.stringify(asset);
      if (imageCardKeys.get(asset.id) === key) continue;
      imageCardKeys.set(asset.id, key);
      const draft = assetDrafts.get(asset.id);
      if (draft && draft.source.trim() === asset.source) assetDrafts.delete(asset.id);
      const card = imageCard(asset);
      const current = grid.querySelector(`[data-asset="${asset.id}"]`);
      if (current) current.replaceWith(card);
      else grid.append(card);
    }
    const unavailable = !options.cutout.available;
    $("cutout-unavailable").hidden = !unavailable;
    if (unavailable) $("cutout-unavailable").textContent = `지금은 배경 제거를 쓸 수 없어요: ${options.cutout.reason} 원본은 그대로 쓸 수 있어요.`;
  }

  // ---------- 작업 상태 ----------
  async function setJob(next) {
    job = next;
    clearTimeout(pollTimer);
    // 제작이 앞으로 진행했을 때만 그 단계로 이동합니다. 승인이 해제되어 뒤로 잠길 때는 지금 화면을 유지합니다.
    const limit = maxStep();
    const first = lastMaxStep === 0;
    if (job.state !== "draft" && (first || limit > lastMaxStep || viewStep > limit)) goToStep(limit, !first);
    lastMaxStep = limit;
    await renderJob();
    if (job.state === "running" || job.aiTask || visibleAssets().some(isProcessing) || identifying()) pollTimer = setTimeout(poll, POLL_MS);
  }

  async function poll() {
    try {
      await setJob(await api(`/api/jobs/${job.id}`));
    } catch (error) {
      show("action-error", error.message);
    }
  }

  async function action(path, init = { method: "POST" }) {
    show("action-error", "");
    setBusy(true);
    try {
      await setJob(await api(`/api/jobs/${job.id}/${path}`, init));
    } catch (error) {
      show("action-error", error.message);
      window.scrollTo({ top: 0 });
    } finally {
      setBusy(Boolean(job.aiTask));
    }
  }

  function setBusy(busy) {
    document.querySelectorAll(".workflow .panel button, .workflow .panel select, .workflow .panel textarea").forEach((node) => {
      if (busy) node.disabled = true;
      else if (!node.dataset.locked) node.disabled = false;
    });
    if (!busy) updateApprovalControls();
  }

  function renderSummary() {
    const list = $("summary-list");
    list.replaceChildren();
    const typeLabel = `${typeLabelOf(job.contentType)}${job.state !== "draft" && TYPE_SOURCE_TEXT[job.typeSource] && job.typeSource !== "user" ? ` (${TYPE_SOURCE_TEXT[job.typeSource]})` : ""}`;
    const assets = visibleAssets();
    const template = isTemplateJob();
    const chosen = template
      ? Object.values(job.slotImages || {}).flatMap((slots) => Object.values(slots))
      : Object.values(job.cardImages || {});
    const used = new Set(chosen.filter(Boolean).map((i) => i.assetId));
    const placed = template ? job.slotImages : job.cardImages;
    const theme = job.designTheme;
    const rows = [
      ["주제", job.topic],
      ["콘텐츠 유형", typeLabel],
      ["참고 URL", job.url || "없음"],
      ["참고 자료", job.notes ? `직접 입력 ${job.notes.length}자 (${NOTES_KIND_TEXT[job.notesKind || ""]})` : "없음"],
      ["이미지", assets.length ? (placed ? `${assets.length}장 중 ${used.size}장을 카드에 사용` : `${assets.length}장`) : "없음"],
      template ? ["디자인", "고정 템플릿 5장"]
        : ["디자인 테마", theme.source === "ai" ? `${theme.label} (AI 선택)` : job.mode === "ai" ? "디자인 단계에서 AI가 정해요" : "기본 테마 (데모)"],
    ];
    for (const [term, value] of rows) {
      list.append(el("dt", { textContent: term }), el("dd", { textContent: value }));
    }
  }

  function displayStepStatus(step) {
    if (step.key === "outline" && job.state === "waiting_outline") return "waiting";
    if (step.key === "outline" && job.state === "waiting_material") return "material";
    if (step.key === "research" && job.state === "waiting_research") return "review";
    if (step.key === "layout" && job.state === "waiting_preview") return "waiting";
    return step.status;
  }

  function renderProgress() {
    const aiRunning = job.mode === "ai" && job.state === "running";
    const activeKey = (job.steps.find((s) => s.status === "active") || {}).key;
    $("status-text").textContent = aiRunning
      ? { research: job.researchBase && !(job.researchStage || {}).done
          ? "AI가 저장된 자료를 바탕으로 부족한 내용을 추가 조사하고 있어요. 2~5분 걸릴 수 있어요. 기존 자료는 그대로 남아요."
          : "AI가 웹에서 자료를 찾고 구성안을 쓰고 있어요. 2~5분 걸릴 수 있어요.",
        layout: isTemplateJob() ? "템플릿에 승인된 문구와 이미지를 넣고 있어요." : "AI가 카드 5장을 디자인하고 있어요. 1~3분 걸릴 수 있어요." }[activeKey] || "진행하고 있어요."
      : STATUS_TEXT[job.state] || "";
    const canRetry = job.mode === "ai" && ["failed", "interrupted"].includes(job.state);
    $("retry").hidden = !canRetry;
    const done = job.steps.filter((s) => s.status === "done").length;
    $("bar-fill").style.width = `${Math.round((done / job.steps.length) * 100)}%`;
    const list = $("steps");
    list.replaceChildren();
    for (const step of job.steps) {
      const status = displayStepStatus(step);
      list.append(
        el("li", { class: `step is-${status}`, dataset: { step: step.key, status } },
          el("span", { textContent: step.label }),
          el("span", { class: "step-state", textContent: `${STEP_TEXT[status]}${step.mode === "demo" ? " · 데모" : ""}` })),
      );
    }
    show("job-error", job.error || "");
  }

  // ---------- 고정 템플릿 (작업 형식 3) ----------
  // 디자인은 템플릿 JSON이 정하고, 구성안의 필드와 이미지 자리만 바뀝니다. 미리보기와 PNG는 같은 렌더러로 그립니다.
  const isTemplateJob = () => Boolean(job && job.format === 3);
  // 카드마다 쓸 템플릿. 예전 형식 3 작업(templateSet 없음)은 표지 1종 + 본문 1종 반복입니다.
  const templateIds = () => job.templateSet || [`${job.contentType}-cover`, ...Array(4).fill(`${job.contentType}-body`)];
  const templateFor = (frame) => options.templates[templateIds()[FRAMES.indexOf(frame)]];
  const outlineTiles = new Map(); // frame -> { canvas, warning, key, overflow, missing }
  let outlineDraft = null; // 편집 중인 카드의 입력값. 저장 전에도 미리보기에 바로 반영합니다
  let outlineChain = Promise.resolve();

  // 유연한 구성(새 작업): card-02 ~ card-05에서 고를 수 있는 템플릿. 예전 작업이나 표지는 빈 목록입니다
  function templateChoices(frame) {
    const type = job.contentType;
    if (!job.templateSet || frame === FRAMES[0] || !options.templates[`${type}-free`] || job.templateSet[0] !== `${type}-01`) return [];
    const choices = [2, 3, 4, 5].map((n) => `${type}-0${n}`).concat(`${type}-free`).filter((id) => options.templates[id]);
    // 예전 판으로 연 카드(예: 친구와 TMI 이전 형식)는 지금 구성을 목록에 함께 보여 줍니다
    const current = job.outline && (job.outline.cards.find((c) => c.frame === frame) || {}).template;
    return current && !choices.includes(current) && options.templates[current] ? [current, ...choices] : choices;
  }

  // 출처를 표시하는 카드인지 (서버 templates.has_source와 같음). 다음 편 예고처럼 조사한 사실이 없는 카드는 출처가 없습니다
  const hasSource = (tpl) => tpl.kind !== "cover" && tpl.showSource !== false;

  function templateSpec(card, draft) {
    const tpl = templateFor(card.frame);
    const index = FRAMES.indexOf(card.frame);
    const values = draft || card;
    // 표지(card-01)의 값을 물려받는 필드. 표지를 고치는 중이면 입력 중인 값을 씁니다
    const cover = job.outline.cards[0];
    const coverFields = (editingFrame === cover.frame && outlineDraft ? outlineDraft : cover).fields || {};
    const inherited = Object.fromEntries((tpl.inherit || []).map((key) => [key, coverFields[key] || ""]));
    return {
      version: 3, frame: card.frame, template: tpl.id, page: index + 1, total: FRAMES.length,
      no: tpl.legacy && tpl.kind === "body" ? String(index).padStart(2, "0") : "",
      fields: { ...inherited, ...values.fields }, source: hasSource(tpl) ? values.source || "" : "",
      images: itemImages(tpl, card.frame, draft),
    };
  }

  // 그 자리에 있는 사진의 이름 확인 기록. 서버 friends.identity와 같이 자리 이름이 아니라 사진으로 찾습니다 (순서를 바꿔도 따라감)
  const identityOf = (frame, key) => {
    const image = currentSlot(frame, key);
    if (!image) return null;
    return Object.values(((job.slotIdentities || {})[frame]) || {}).find((record) => record.assetId === image.assetId) || null;
  };

  function imageVersions(spec) {
    return Object.values(spec.images || {}).filter(Boolean).map((image) => {
      const asset = job.assets.find((a) => a.id === image.assetId);
      return [image.assetId, image.variant, asset && asset.cutout ? asset.cutout.version : 0];
    });
  }

  // showEmpty: 구성안 편집 화면에서만 빈 이미지 자리를 점선으로 표시합니다. 디자인 미리보기(=PNG)에는 그리지 않습니다
  async function drawTemplate(canvas, spec, showEmpty = false) {
    const tpl = options.templates[spec.template];
    await SemogwiRenderer.fontsReady({ fonts: tpl.fonts });
    return SemogwiRenderer.renderTemplate(canvas, spec, tpl, { demo: job.demo, assetUrl, assetInfo, showEmpty });
  }

  function fieldLabel(tpl, key) {
    if (key === "source") return "출처";
    const field = tpl.fields.find((f) => f.key === key);
    return field ? field.label : "고정 문구";
  }

  function templateWarning(tpl, result) {
    const notes = [];
    if (result.overflowFields.length) notes.push(`글자가 칸을 넘쳤어요: ${result.overflowFields.map((k) => fieldLabel(tpl, k)).join(", ")}. 문구를 줄여 주세요.`);
    // 선택 이미지 자리는 비어도 흐린 세모귀로 채워지므로 알리지 않습니다. 필수 자리만 알립니다.
    const missing = tpl.images.filter((s) => s.required && result.missingImages.includes(s.key));
    if (missing.length) notes.push(`비어 있는 이미지 자리: ${missing.map((s) => `${s.label}(필수)`).join(", ")}`);
    return notes.join(" ");
  }

  // ---------- 카드 이미지 자리 (선택·업로드·교체·배경 제거·크기와 위치) ----------
  const slotPanels = new Map(); // "frame:slot" -> { key, node }. 폴링으로 다시 그려도 입력 중인 파일·슬라이더가 사라지지 않게 재사용합니다
  const slotAdjustDrafts = new Map(); // 슬라이더를 움직이는 동안의 값. 놓으면 저장합니다
  // 카드에 쓸 수 있는 이미지 (예전에 '허가 안 됨'으로 직접 표시한 이미지만 빼고 모두)
  const permittedAssets = () => visibleAssets().filter((a) => a.rights !== "허가 안 됨");
  const assetName = (id) => (job.assets.find((a) => a.id === id) || {}).name || "이미지";
  const currentSlot = (frame, key) => ((job.slotImages || {})[frame] || {})[key] || null;
  const suggestionOf = (frame, key) => ((job.slotSuggestions || {})[frame] || {})[key] || null;

  function assetInfo(assetId) {
    const asset = job.assets.find((a) => a.id === assetId);
    return asset && asset.cutout && asset.cutout.stats ? asset.cutout.stats : null;
  }

  // 화면에 그릴 이미지 자리 값. 슬라이더를 움직이는 중이면 그 값을 씁니다
  function slotImageFor(frame, key) {
    const image = currentSlot(frame, key);
    const draft = slotAdjustDrafts.get(`${frame}:${key}`);
    return image && draft ? { ...image, ...draft } : image;
  }

  async function slotAction(path, init) {
    show("action-error", "");
    try {
      await setJob(await api(`/api/jobs/${job.id}/${path}`, init));
      return true;
    } catch (error) {
      show("action-error", error.message);
      return false;
    }
  }

  function slotPicker(frame, slot, current) {
    const select = el("select", {
      "aria-label": `${frame} ${slot.label} 선택`,
      dataset: { slotSelect: `${frame}:${slot.key}` },
      onchange: (e) => {
        const assetId = e.target.value || null;
        const asset = assetId && job.assets.find((a) => a.id === assetId);
        // 같은 이미지를 다시 고르면 지금 방식(원본/누끼)을 유지하고, 새 이미지는 그 이미지의 기본 설정을 따릅니다
        const variant = current && current.assetId === assetId ? current.variant
          : asset && asset.useVariant === "cutout" && hasCutout(asset) ? "cutout" : "original";
        slotAction(`cards/${frame}/slots/${slot.key}`, jsonInit("PUT", { assetId, variant }));
      },
    });
    select.append(el("option", { value: "", textContent: "이미지 사용 안 함", selected: !current }));
    for (const asset of permittedAssets()) {
      select.append(el("option", { value: asset.id, textContent: asset.name, selected: Boolean(current) && current.assetId === asset.id }));
    }
    return select;
  }

  function slotCompare(asset) {
    const original = el("img", { src: assetUrl(asset.id), alt: `${asset.name} 원본` });
    const cutoutView = hasCutout(asset)
      ? el("img", { src: assetUrl(asset.id, "cutout"), alt: `${asset.name} 배경 제거 결과` })
      : el("p", { class: "cutout-empty", textContent: isProcessing(asset) ? "처리 중이에요" : "아직 없어요" });
    return el("div", { class: "image-compare slot-compare" }, figure("원본", original), figure("배경 제거", cutoutView, "is-cutout"));
  }

  function slotBackground(frame, slot, current, asset) {
    const base = `cards/${frame}/slots/${slot.key}`;
    const row = el("div", { class: "slot-bg" });
    const on = current.variant === "cutout";
    const toggle = el("input", {
      type: "checkbox", checked: on, disabled: isProcessing(asset) || !options.cutout.available && !hasCutout(asset),
      dataset: { slotBg: `${frame}:${slot.key}` },
      onchange: (e) => {
        if (!e.target.checked) slotAction(base, jsonInit("PUT", { assetId: asset.id, variant: "original" }));
        else if (hasCutout(asset)) slotAction(base, jsonInit("PUT", { assetId: asset.id, variant: "cutout" }));
        // 누끼가 아직 없으면 만들고, 끝나면 이 자리에 자동으로 들어갑니다
        else slotAction(`assets/${asset.id}/cutout`, jsonInit("POST", { model: "auto" }));
      },
    });
    row.append(el("label", { class: "switch" }, toggle, el("span", { textContent: `배경 제거 ${on ? "ON" : "OFF"}` })));
    if (current.variant === "cutout" || current.scale !== 1 || current.dx || current.dy) {
      row.append(el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "원본 복원", dataset: { slotRestore: `${frame}:${slot.key}` },
        title: "이 자리를 원본 이미지로 되돌리고 크기·위치를 처음대로 돌려요", onclick: () => slotAction(`${base}/restore`) }));
    }
    if (isProcessing(asset)) row.append(el("small", { class: "cutout-status" }, el("span", { class: "spinner", "aria-hidden": "true" }), "배경을 지우고 있어요"));
    else if (asset.cutout && asset.cutout.status === "failed") row.append(el("small", { class: "cutout-error", textContent: `${asset.cutout.error} 원본은 그대로 쓸 수 있어요.` }));
    else if (current.keepOriginal) row.append(el("small", { class: "hint", textContent: "원본을 직접 골랐어요. 배경 제거 결과가 바뀌어도 원본을 유지해요." }));
    return row;
  }

  function slotAdjust(frame, slot, current) {
    const id = `${frame}:${slot.key}`;
    const values = { scale: current.scale ?? 1, dx: current.dx ?? 0, dy: current.dy ?? 0 };
    const inputs = {};
    const read = () => ({ scale: Number(inputs.scale.value) / 100, dx: Number(inputs.dx.value) / 100, dy: Number(inputs.dy.value) / 100 });
    const save = () => {
      const next = read();
      slotAction(`cards/${frame}/slots/${slot.key}/adjust`, jsonInit("PUT", next)).finally(() => slotAdjustDrafts.delete(id));
    };
    const range = (name, label, min, max, value) => {
      const output = el("output", { textContent: `${Math.round(value * 100)}%` });
      inputs[name] = el("input", {
        type: "range", min, max, step: 1, value: Math.round(value * 100), "aria-label": `${frame} ${slot.label} ${label}`,
        dataset: { slotAdjust: `${id}:${name}` },
        oninput: () => {
          output.textContent = `${inputs[name].value}%`;
          slotAdjustDrafts.set(id, read());
          drawOutlinePreviews();
        },
        onchange: save,
      });
      return el("label", { class: "slot-range" }, el("span", { textContent: label }), inputs[name], output);
    };
    return el("details", { class: "slot-adjust", open: slotAdjustOpen.has(id), ontoggle: (e) => (e.target.open ? slotAdjustOpen.add(id) : slotAdjustOpen.delete(id)) },
      el("summary", { textContent: "크기·위치 조정" }),
      range("scale", "크기", 30, 300, values.scale),
      range("dx", "가로 위치", -100, 100, values.dx),
      range("dy", "세로 위치", -100, 100, values.dy),
      el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "처음대로",
        onclick: () => slotAction(`cards/${frame}/slots/${slot.key}/adjust`, jsonInit("PUT", { scale: 1, dx: 0, dy: 0 })) }));
  }
  const slotAdjustOpen = new Set();

  function slotUpload(frame, slot, current) {
    const file = el("input", { type: "file", accept: "image/png,image/jpeg,image/webp", "aria-label": `${frame} ${slot.label} 이미지 파일`, dataset: { slotFile: `${frame}:${slot.key}` } });
    const source = el("input", { type: "text", maxLength: 100, placeholder: "출처 (선택, 예: 직접 촬영, 공식 사이트)", "aria-label": `${frame} ${slot.label} 출처` });
    const error = el("small", { class: "rights-hint", hidden: true });
    const button = el("button", {
      class: "btn btn-ghost btn-small", type: "button", textContent: current ? "새 이미지로 교체" : "올려서 넣기",
      dataset: { slotUpload: `${frame}:${slot.key}` },
      onclick: async () => {
        const fail = (text) => { error.textContent = text; error.hidden = false; };
        if (!file.files.length) return fail("이미지 파일을 골라 주세요.");
        const data = new FormData();
        data.append("image", file.files[0]);
        data.append("source", source.value.trim());  // 출처는 적으면 함께 저장 (선택)
        button.disabled = true;
        if (await slotAction(`cards/${frame}/slots/${slot.key}/upload`, { method: "POST", body: data })) {
          file.value = "";
          error.hidden = true;
        }
        button.disabled = false;
      },
    });
    return el("details", { class: "slot-upload" }, el("summary", { textContent: current ? "다른 이미지 올려서 교체" : "이 카드에 이미지 올리기" }),
      file, source, button, error);
  }

  // 친구 칸: 사진 속 캐릭터 이름을 보여 주고 사용자가 고쳐서 확정합니다. 친구 문구는 확정한 이름으로만 써요
  function identityPanel(frame, slot) {
    const record = identityOf(frame, slot.key);
    const status = record ? record.status : "manual";
    const field = templateFor(frame).fields.find((f) => f.key === slot.identify);
    const nameMax = field.fields.find((s) => s.key === field.linkedName).max;
    let note;
    if (status === "processing") note = el("small", { class: "cutout-status" }, el("span", { class: "spinner", "aria-hidden": "true" }), "사진 속 캐릭터 이름을 확인하고 있어요. 기다리지 않고 직접 입력해도 돼요.");
    else if (status === "suggested" && record.suggested) note = el("small", { class: "hint", textContent: `AI 인식: ${record.suggested} (확신도 ${record.confidence})${record.evidence ? ` · 근거: ${record.evidence}` : ""}. 맞으면 확정하고, 다르면 고쳐서 확정해 주세요.` });
    else if (status === "suggested") note = el("small", { class: "hint", textContent: `AI가 이름을 확신하지 못했어요${record.candidates.length ? ` (후보: ${record.candidates.join(", ")})` : ""}. 이름을 직접 입력해 주세요.` });
    else if (status === "failed") note = el("small", { class: "cutout-error", textContent: record.error });
    else if (status === "confirmed") note = el("small", { class: "hint", textContent: `확정: ${record.name}. 이 칸의 문구는 이 이름으로만 써요.` });
    else note = el("small", { class: "hint", textContent: "사진 속 캐릭터 이름을 입력해 확정해 주세요." });
    const input = el("input", {
      type: "text", maxLength: nameMax, placeholder: "캐릭터 이름", "aria-label": `${frame} ${slot.label} 캐릭터 이름`,
      value: status === "confirmed" ? record.name : (record && record.suggested) || "", dataset: { identityName: `${frame}:${slot.key}` },
    });
    const button = el("button", {
      class: "btn btn-primary btn-small", type: "button", textContent: status === "confirmed" ? "이름 바꾸기" : "이 이름으로 확정",
      dataset: { identityConfirm: `${frame}:${slot.key}` },
      onclick: () => slotAction(`cards/${frame}/slots/${slot.key}/identity`, jsonInit("PUT", { name: input.value })),
    });
    return el("div", { class: "slot-identity", dataset: { identity: `${frame}:${slot.key}` } },
      el("label", { class: "tile-image" }, el("span", { textContent: `캐릭터 이름 (${nameMax}자 이내)` }), input), button, note);
  }

  function slotPanel(frame, slot, context) {
    const current = slotImageFor(frame, slot.key);
    const asset = current && job.assets.find((a) => a.id === current.assetId);
    const suggestion = !current && suggestionOf(frame, slot.key);
    const key = JSON.stringify([current && currentSlot(frame, slot.key), suggestion, asset, permittedAssets().map((a) => [a.id, a.name, a.useVariant, hasCutout(a)]),
      options.cutout.available, job.state, slot.identify ? identityOf(frame, slot.key) : null]);
    const cacheKey = `${context}:${frame}:${slot.key}`;
    const cached = slotPanels.get(cacheKey);
    if (cached && cached.key === key) return cached.node;

    const node = el("div", { class: "slot-panel", dataset: { slot: `${frame}:${slot.key}` } },
      el("label", { class: "tile-image" }, el("span", { textContent: `${slot.label}${slot.required ? " (필수)" : ""}` }), slotPicker(frame, slot, current)));
    if (suggestion) {
      // 추천은 제안만 합니다. 적용을 눌러야 카드에 들어갑니다
      node.append(el("div", { class: "slot-suggest-row" },
        el("span", { textContent: `추천: ${assetName(suggestion.assetId)}${suggestion.variant === "cutout" ? " (배경 제거)" : ""}` }),
        el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "적용", dataset: { applySuggestion: `${frame}:${slot.key}` },
          onclick: () => slotAction("slot-suggestions/apply", jsonInit("POST", { frame, slot: slot.key })) })));
    }
    if (current && slot.identify) node.append(identityPanel(frame, slot));
    if (current && asset) node.append(slotCompare(asset), slotBackground(frame, slot, current, asset), slotAdjust(frame, slot, current));
    node.append(slotUpload(frame, slot, current));
    slotPanels.set(cacheKey, { key, node });
    return node;
  }

  function slotControls(frame, context = "outline") {
    const slots = activeSlots(frame);
    if (!slots.length) return el("p", { class: "hint", textContent: "이 카드에는 이미지 자리가 없어요." });
    return el("div", { class: "slot-list" }, ...slots.map((slot) => slotPanel(frame, slot, context)));
  }

  function renderSlotSuggestions() {
    const box = $("slot-suggest");
    const count = Object.values(job.slotSuggestions || {}).reduce((n, slots) => n + Object.keys(slots).length, 0);
    box.hidden = !isTemplateJob() || !count;
    if (box.hidden) return;
    box.replaceChildren(
      el("span", { textContent: `빈 이미지 자리 ${count}곳에 올린 이미지를 추천했어요. 적용해야 카드에 들어가요.` }),
      el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "추천 모두 적용", dataset: { applySuggestion: "all" },
        onclick: () => slotAction("slot-suggestions/apply", jsonInit("POST", {})) }));
  }

  function fieldText(field, value) {
    if (field.type === "flag") return value ? "예" : "아니요";
    if (field.type === "choice") return (field.options.find((o) => o.value === value) || field.options.find((o) => o.value === field.default)).label;
    if (field.type === "list") return value.map((t) => `#${t}`).join(" ");
    if (field.type === "items") return value.map((item) => field.fields.map((sub) => item[sub.key]).filter(Boolean).join(" · ")).join("\n");
    if (field.type === "pairs") return value.map((p) => `${p.label}: ${p.value}`).join(" · ");
    return value;
  }

  // 칸의 출처 종류: 가격·일정·장소처럼 공식 우선이거나 중요한 정보, 또는 확인이 필요한 칸에 글로 보여 줍니다 (배지·차단 없음)
  const FIELD_SOURCE = { verified: "공식 확인", secondary: "2차 자료", listed: "검색 결과(원문 미확인)", user: "사용자 제공", user_written: "사용자 작성",
    image: "상세 이미지", conflict: "출처 충돌", unverified: "근거 확인 못 함", absent: "조사에서 찾지 못함" };
  function fieldSourceText(card, field) {
    if (!job.research || !field.item) return "";
    const state = ((job.outline.fieldStates || {})[card.frame] || {})[field.key];
    if (!state || state === "missing" || !FIELD_SOURCE[state]) return "";
    const item = (job.research.items || []).find((i) => i.key === field.item);
    const important = item && (item.strict || item.volatile || ["core", "high"].includes(item.importance));
    return important || ["conflict", "unverified", "absent", "user_written"].includes(state) ? FIELD_SOURCE[state] : "";
  }

  function fieldSummary(card) {
    const tpl = templateFor(card.frame);
    const list = el("dl", { class: "field-list" });
    const states = ((job.outline.fieldStates || {})[card.frame]) || {};
    for (const field of tpl.fields) {
      const value = card.fields[field.key];
      const empty = field.type !== "flag" && field.type !== "choice" && (!value || (Array.isArray(value) && !value.length));
      const active = !field.if || SemogwiRenderer.conditionMet(tpl, card.fields, field.if);
      if (!active && empty) continue; // 다른 카테고리의 빈 목록은 보여 주지 않습니다
      const dd = el("dd", { class: empty || !active ? "is-empty" : "", dataset: { field: field.key } });
      if (states[field.key]) dd.dataset.state = states[field.key]; // 근거 상태는 화면에 배지로 표시하지 않고 속성으로만 둡니다
      if (!active) dd.append("보관 중 · 카테고리를 바꾸면 카드에 보여요: ");
      dd.append(empty ? (field.required ? "비어 있음 · 입력이 필요해요" : field.emptyNote ? `비어 있음 · ${field.emptyNote}` : field.placeholder ? `비어 있음 · 기본 문구 '${field.placeholder}'로 보여요` : "비어 있음 · 카드에서 숨겨요") : fieldText(field, value === undefined && field.type === "choice" ? field.default : value));
      const source = empty ? "" : fieldSourceText(card, field);
      if (source) dd.append(el("small", { class: "field-source", textContent: ` · 출처: ${source}` }));
      list.append(el("dt", { textContent: field.label }), dd);
    }
    if (hasSource(tpl)) list.append(el("dt", { textContent: "출처" }), el("dd", { class: card.source ? "" : "is-empty", textContent: card.source || "출처 없음" }));
    return list;
  }

  function outlineTile(frame) {
    let tile = outlineTiles.get(frame);
    if (!tile) {
      const canvas = el("canvas", { width: SemogwiRenderer.WIDTH, height: SemogwiRenderer.HEIGHT, dataset: { outlinePreview: frame } });
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", `${frame} 템플릿 미리보기`);
      tile = { canvas, warning: el("p", { class: "card-warning", hidden: true }), key: "", overflow: [], missing: [] };
      outlineTiles.set(frame, tile);
    }
    return tile;
  }

  function templateControl(field, value, frame) {
    if (field.type === "choice") {
      // 예: 친구/가족. 바꾸면 그 카테고리 목록이 보이고, 다른 목록은 지우지 않고 보관합니다 (templateEditor가 처리)
      const select = el("select", { name: `field-${field.key}`, dataset: { choice: field.key }, "aria-label": field.label });
      for (const option of field.options) select.append(el("option", { value: option.value, textContent: option.label, selected: (value || field.default) === option.value }));
      return el("label", { class: "edit-field" }, el("span", { textContent: field.label }), select,
        el("small", { class: "hint", textContent: "바꿔도 입력한 친구·가족 정보는 따로 보관돼요. 비어 있는 쪽으로 바꾸면 조사 자료에서 불러와요." }));
    }
    if (field.type === "flag") {
      const box = el("input", { type: "checkbox", name: `field-${field.key}`, checked: Boolean(value) });
      return el("label", { class: "flag-field" }, box, el("span", { textContent: field.label }), field.hint ? el("small", { class: "hint", textContent: field.hint }) : "");
    }
    if (field.type === "text" || field.type === "multiline") {
      const input = field.type === "text"
        ? el("input", { type: "text", value: value || "", name: `field-${field.key}`, placeholder: field.placeholder || field.default || "" })
        : el("textarea", { value: value || "", rows: 2, name: `field-${field.key}` });
      return editField(`${field.label}${field.required ? " (필수)" : ""}`, input, field.max);
    }
    if (field.type === "items" && (field.minItems || field.editor === "list")) return itemsEditor(field, value, frame);
    const group = el("fieldset", { class: "edit-group", dataset: { group: field.key } }, el("legend", { textContent: `${field.label} · 최대 ${field.maxItems}개, 빈 칸은 카드에서 숨겨요` }));
    for (let i = 0; i < field.maxItems; i++) {
      if (field.type === "items") {
        const item = (value || [])[i] || {};
        const row = el("div", { class: "item-row", dataset: { item: `${field.key}-${i}` } }, el("b", { textContent: `${i + 1}` }));
        for (const sub of field.fields) {
          const input = sub.type === "multiline"
            ? el("textarea", { value: item[sub.key] || "", rows: 2, name: `field-${field.key}-${i}-${sub.key}`, placeholder: sub.default || "" })
            : el("input", { type: "text", value: item[sub.key] || "", name: `field-${field.key}-${i}-${sub.key}`, placeholder: sub.default || "" });
          row.append(editField(`${sub.label}${sub.required ? " (필수)" : ""}`, input, sub.max));
        }
        group.append(row);
      } else if (field.type === "list") {
        const input = el("input", { type: "text", value: (value || [])[i] || "", name: `field-${field.key}-${i}`, "aria-label": `${field.label} ${i + 1}` });
        group.append(editField("", input, field.itemMax));
      } else {
        const item = (value || [])[i] || { label: "", value: "" };
        const label = el("input", { type: "text", value: item.label, name: `field-${field.key}-${i}-label`, placeholder: (field.defaultLabels || [])[i] || "항목", "aria-label": `${field.label} ${i + 1} 항목 이름` });
        const val = el("input", { type: "text", value: item.value, name: `field-${field.key}-${i}-value`, "aria-label": `${field.label} ${i + 1} 내용` });
        group.append(el("div", { class: "pair-row" }, editField("", label, field.labelMax), editField("", val, field.valueMax)));
      }
    }
    return group;
  }

  // 개수를 늘리고 줄일 수 있는 항목 (예: 친구 캐릭터 2~4명, 프로필 항목 0~3개). 항목마다 저장 전 번호(orig)를 기억해 이미지가 그 항목을 따라가게 합니다
  // editor: "list"인 필드(프로필 항목)는 0개부터 쓸 수 있고 단위(unit)를 따로 정합니다. 친구·가족은 지금처럼 '명' 단위입니다
  function itemsEditor(field, value, frame) {
    const minItems = field.minItems || 0;
    const unit = field.unit || "명";
    let rows = (value || []).map((item, i) => ({ item: { ...item }, orig: i }));
    if (!rows.length) rows = Array.from({ length: field.defaultItems || minItems }, () => ({ item: {}, orig: -1 }));
    while (rows.length < minItems) rows.push({ item: {}, orig: -1 });
    const group = el("fieldset", { class: "edit-group items-editor", dataset: { group: field.key } });
    const legend = el("legend");
    const list = el("div", { class: "item-list" });
    const note = el("small", { class: "hint" });
    const changed = () => group.closest("form")?.dispatchEvent(new Event("input", { bubbles: true }));
    const read = () => rows.forEach((row, i) => field.fields.forEach((sub) => {
      const input = list.querySelector(`[name="field-${field.key}-${i}-${sub.key}"]`);
      if (input) row.item[sub.key] = input.value;
    }));
    const add = el("button", { class: "btn btn-ghost btn-small", type: "button", dataset: { itemAdd: field.key },
      onclick: () => { read(); if (rows.length < field.maxItems) rows.push({ item: {}, orig: -1 }); draw(); changed(); } });
    const draw = () => {
      legend.textContent = `${field.label} · ${minItems}~${field.maxItems}${unit} (지금 ${rows.length}${unit})`;
      add.textContent = `+ ${field.label.replace(/ 캐릭터$/, "")} 추가`;
      add.disabled = rows.length >= field.maxItems;
      note.textContent = rows.length >= field.maxItems ? `최대 ${field.maxItems}${unit}${unit === "명" ? "이에요" : "예요"}.`
        : minItems && rows.length <= minItems ? `최소 ${minItems}${unit}이 필요해요. 확인된 캐릭터가 부족하면 카드 구성을 '자유 구성'으로 바꿔 주세요.`
        : field.editor === "list" && !rows.length ? "확인된 프로필 항목이 없으면 비워 두세요. 카드는 이름과 소개 문장으로 꾸며져요." : "";
      list.replaceChildren(...rows.map((row, i) => {
        const box = el("div", { class: "item-row", dataset: { item: `${field.key}-${i}` } }, el("b", { textContent: `${i + 1}` }),
          el("input", { type: "hidden", name: `field-${field.key}-${i}-orig`, value: String(row.orig) }));
        // 사진에서 이름을 확정한 항목은 이름을 사진 칸에서만 바꿉니다 (여기서 고쳐도 서버가 확정한 이름으로 되돌려요)
        const record = frame && field.linkedName && field.slotPrefix && row.orig >= 0 ? identityOf(frame, `${field.slotPrefix}${row.orig + 1}`) : null;
        const locked = record && record.status === "confirmed";
        for (const sub of field.fields) {
          const lock = locked && sub.key === field.linkedName;
          const input = sub.type === "multiline"
            ? el("textarea", { value: row.item[sub.key] || "", rows: 3, name: `field-${field.key}-${i}-${sub.key}`, placeholder: sub.placeholder || sub.default || "" })
            : el("input", { type: "text", value: row.item[sub.key] || "", name: `field-${field.key}-${i}-${sub.key}`, placeholder: sub.placeholder || sub.default || "", readOnly: lock });
          box.append(editField(lock ? `${sub.label} · 사진 칸에서 확정` : `${sub.label}${sub.required ? " (필수)" : ""}`, input, sub.max));
        }
        box.append(el("button", { class: "btn btn-ghost btn-small item-remove", type: "button", textContent: "삭제", disabled: rows.length <= minItems,
          dataset: { itemRemove: `${field.key}-${i}` }, "aria-label": `${field.label} ${i + 1} 삭제`,
          onclick: () => { read(); if (rows.length > minItems) rows.splice(i, 1); draw(); changed(); } }));
        return box;
      }));
    };
    draw();
    group.append(legend, list, el("div", { class: "actions" }, add), note);
    // 카테고리를 바꿀 때 templateEditor가 씁니다: 비어 있는지 보고, 조사 자료로 채웁니다 (새 항목이라 이미지는 비어 있음)
    group.isBlank = () => { read(); return rows.every((row) => !Object.values(row.item).some((v) => String(v || "").trim())); };
    group.setItems = (items) => {
      rows = items.slice(0, field.maxItems).map((item) => ({ item: { ...item }, orig: -1 }));
      while (rows.length < minItems) rows.push({ item: {}, orig: -1 });
      draw();
    };
    return group;
  }

  // 카테고리(친구/가족) 선택에 따라 보이는 목록을 바꿉니다. 숨긴 목록도 폼에 남겨 저장하므로 입력한 정보가 사라지지 않습니다
  function bindChoices(form, tpl) {
    const sync = (fromUser) => {
      const values = Object.fromEntries([...form.querySelectorAll("[data-choice]")].map((s) => [s.dataset.choice, s.value]));
      for (const field of tpl.fields) {
        if (!field.if) continue;
        const group = form.querySelector(`[data-group="${field.key}"]`);
        if (!group) continue;
        const on = SemogwiRenderer.conditionMet(tpl, values, field.if);
        group.style.display = on ? "" : "none";
        const people = (((job.research || {}).people) || {})[field.key] || [];
        if (on && fromUser && group.isBlank && group.isBlank() && people.length) {
          group.setItems(people.map((p) => ({ name: p.name, relation: p.relation, tmi: p.tmi })));
        }
      }
    };
    form.querySelectorAll("[data-choice]").forEach((select) => select.addEventListener("change", () => {
      sync(true);
      form.dispatchEvent(new Event("input", { bubbles: true }));
    }));
    sync(false);
  }

  function collectTemplate(form, card) {
    const tpl = templateFor(card.frame);
    const get = (name) => (form.elements[name] ? form.elements[name].value : "");
    const fields = {};
    const itemOrder = {};
    for (const field of tpl.fields) {
      if (field.type === "flag") fields[field.key] = Boolean(form.elements[`field-${field.key}`] && form.elements[`field-${field.key}`].checked);
      else if (field.type === "choice") fields[field.key] = get(`field-${field.key}`) || field.default;
      else if (field.type === "text" || field.type === "multiline") fields[field.key] = get(`field-${field.key}`);
      else if (field.type === "list") fields[field.key] = [...Array(field.maxItems).keys()].map((i) => get(`field-${field.key}-${i}`).trim()).filter(Boolean);
      else if (field.type === "items") {
        const rows = [...Array(field.maxItems).keys()]
          .map((i) => ({ item: Object.fromEntries(field.fields.map((sub) => [sub.key, get(`field-${field.key}-${i}-${sub.key}`).trim()])),
            orig: form.elements[`field-${field.key}-${i}-orig`] ? Number(get(`field-${field.key}-${i}-orig`)) : i }))
          .filter((row) => Object.values(row.item).some(Boolean));
        fields[field.key] = rows.map((row) => row.item);
        if (field.slotPrefix) itemOrder[field.key] = rows.map((row) => row.orig);
      }
      else fields[field.key] = [...Array(field.maxItems).keys()].map((i) => ({ label: get(`field-${field.key}-${i}-label`).trim(), value: get(`field-${field.key}-${i}-value`).trim() }))
        .filter((p) => p.label || p.value);
    }
    const result = { role: get("role"), fields, source: hasSource(tpl) ? get("source") : "" };
    if (Object.keys(itemOrder).length) result.itemOrder = itemOrder;
    return result;
  }

  // 항목별 이미지(친구 1 이미지 …)를 편집 중인 항목 순서에 맞춥니다. 저장하면 서버도 같은 방식으로 옮깁니다
  function itemImages(tpl, frame, draft) {
    const images = Object.fromEntries(tpl.images.map((slot) => [slot.key, slotImageFor(frame, slot.key)]));
    for (const field of tpl.fields) {
      const order = draft && draft.itemOrder && draft.itemOrder[field.key];
      if (!field.slotPrefix || !order) continue;
      for (let j = 0; j < field.maxItems; j++) {
        const source = j < order.length ? order[j] : -1;
        images[`${field.slotPrefix}${j + 1}`] = source >= 0 ? slotImageFor(frame, `${field.slotPrefix}${source + 1}`) : null;
      }
    }
    return images;
  }

  // 카드에 그려지는 이미지 자리만 (예: 친구가 2명이면 친구 3·4 이미지 자리는 숨김)
  function activeSlots(frame) {
    const tpl = templateFor(frame);
    const card = job.outline && job.outline.cards.find((c) => c.frame === frame);
    const fields = (card && card.fields) || {};
    return tpl.images.filter((slot) => !slot.if || SemogwiRenderer.conditionMet(tpl, fields, slot.if));
  }

  // 마무리 카드: 다음 캐릭터 이름을 저장한 뒤 힌트·공개 문구를 AI로 씁니다. 버튼을 눌렀을 때만 AI를 부릅니다 (입력 중에는 부르지 않음)
  function nextTeaserButton(form, card, tpl, error) {
    const spec = tpl.nextTeaser;
    const ai = job.mode === "ai";
    const button = el("button", { class: "btn btn-ghost btn-small", type: "button", dataset: { nextTeaser: card.frame },
      textContent: ai ? "힌트·공개 문구 AI로 쓰기" : "힌트·공개 문구 기본 문구로 채우기" });
    const note = el("small", { class: "hint", textContent: ai
      ? "이름을 저장하고, 조사 자료와 붙여 넣은 자료에서 확인된 특징만으로 힌트를 써요. 확인된 특징이 없으면 기본 문구를 넣고, 공개 날짜는 쓰지 않아요. (AI 1회, 검색 없음)"
      : "데모에서는 AI를 부르지 않고 기본 문구를 넣어요." });
    button.addEventListener("click", async () => {
      error.hidden = true;
      const draft = collectTemplate(form, card);
      if (!String(draft.fields[spec.name] || "").trim()) {
        error.textContent = "다음 캐릭터 이름을 먼저 입력해 주세요.";
        error.hidden = false;
        return;
      }
      const filled = draft.fields[spec.hint] || draft.fields[spec.reveal];
      if (filled && !confirm("지금 쓴 힌트와 공개 문구를 새 문구로 바꿀까요?")) return;
      button.disabled = true;
      try {
        await setJob(await api(`/api/jobs/${job.id}/outline/cards/${card.frame}`, jsonInit("PUT", draft)));
      } catch (err) {
        error.textContent = err.message;
        error.hidden = false;
        button.disabled = false;
        return;
      }
      editingFrame = null;
      outlineDraft = null;
      await action(`outline/cards/${card.frame}/next-teaser`);
      renderOutline();
    });
    return el("div", { class: "edit-field" }, button, note);
  }

  function templateEditor(card) {
    const tpl = templateFor(card.frame);
    const error = el("p", { class: "error", role: "alert", hidden: true });
    const save = el("button", { class: "btn btn-primary btn-small", type: "submit", textContent: "저장" });
    const form = el("form", { class: "outline-editor template-editor", dataset: { editor: card.frame } });
    const choices = templateChoices(card.frame);
    if (choices.length) {
      // card-02 ~ card-05: 자료에 맞는 카드 구성을 고릅니다. 바꾸면 있는 값만 옮기고 새 사실은 만들지 않아요
      const select = el("select", { "aria-label": `${card.frame} 카드 구성`, dataset: { templateSelect: card.frame },
        onchange: async (e) => {
          error.hidden = true;
          try {
            const next = await api(`/api/jobs/${job.id}/outline/cards/${card.frame}/template`, jsonInit("PUT", { template: e.target.value }));
            outlineDraft = null;
            await setJob(next);
            renderOutline();
          } catch (err) {
            e.target.value = card.template;
            error.textContent = err.message;
            error.hidden = false;
          }
        } });
      for (const id of choices) select.append(el("option", { value: id, textContent: options.templates[id].label, selected: id === card.template }));
      form.append(el("label", { class: "edit-field" }, el("span", { textContent: "카드 구성" }), select,
        el("small", { class: "hint", textContent: "필수 정보가 없으면 자유 구성으로 확인된 정보만 담아요." })));
    }
    form.append(editField("역할", el("input", { type: "text", value: card.role, name: "role" }), 10));
    for (const field of tpl.fields) {
      form.append(templateControl(field, card.fields[field.key], card.frame));
      const source = fieldSourceText(card, field);
      if (source) form.append(el("small", { class: "hint field-source", textContent: `${field.label} 출처: ${source} (저장된 내용 기준)` }));
    }
    bindChoices(form, tpl);
    if (hasSource(tpl)) {
      form.append(editField("출처", el("input", { type: "text", value: card.source, name: "source", placeholder: "출처: 공식 사이트 (모르면 비워 두세요)" }), 30));
    }
    if (tpl.nextTeaser) form.append(nextTeaserButton(form, card, tpl, error));
    form.append(
      job.outline.approved ? el("p", { class: "notice", textContent: "내용을 바꿔 저장하면 승인이 해제돼서 구성안과 디자인을 다시 승인해야 해요." }) : "",
      error,
      el("div", { class: "actions" }, save,
        el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "취소", onclick: () => { editingFrame = null; outlineDraft = null; renderOutline(); } })),
    );
    form.addEventListener("input", () => {
      outlineDraft = collectTemplate(form, card);
      drawOutlinePreviews();
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      save.disabled = true;
      try {
        const next = await api(`/api/jobs/${job.id}/outline/cards/${card.frame}`, jsonInit("PUT", collectTemplate(form, card)));
        editingFrame = null;
        outlineDraft = null;
        await setJob(next);
        renderOutline();
      } catch (err) {
        error.textContent = err.message;
        error.hidden = false;
        save.disabled = false;
      }
    });
    return form;
  }

  function renderTemplateOutline() {
    const list = $("outline-list");
    list.replaceChildren();
    const issues = job.outline.issues || {};
    const canEdit = ["waiting_outline", "waiting_preview", "done"].includes(job.state);
    for (const card of job.outline.cards) {
      const tile = outlineTile(card.frame);
      const preview = el("div", { class: "template-preview" }, tile.canvas, tile.warning);
      if (editingFrame === card.frame) {
        list.append(el("li", { class: "outline-item is-template is-editing", dataset: { frame: card.frame } }, preview, templateEditor(card)));
        continue;
      }
      const issue = issues[card.frame] || { errors: [], warnings: [] };
      const notes = [...issue.errors.map((t) => el("p", { class: "outline-issue is-error", textContent: t })),
        ...issue.warnings.map((t) => el("p", { class: "outline-issue", textContent: t }))];
      list.append(
        el("li", { class: "outline-item is-template", dataset: { frame: card.frame } },
          preview,
          el("div", { class: "outline-content" },
            el("span", { class: "outline-role", textContent: card.role }), " ",
            templateChoices(card.frame).length ? el("span", { class: "tag tag-demo", textContent: templateFor(card.frame).label }) : "", " ",
            card.edited ? el("span", { class: "edited-mark", textContent: "직접 수정" }) : job.mode === "ai" ? tag("AI 작성", "real") : tag("예시 내용"),
            fieldSummary(card),
            ...(job.mode === "ai" && sourcesOf(card).length
              ? [el("div", { class: "card-links" }, ...sourcesOf(card).map(sourceLink))]
              : []),
            ...notes,
            slotControls(card.frame),
            el("div", { class: "outline-buttons is-row" },
              el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "내용 수정", disabled: !canEdit, dataset: { edit: card.frame },
                onclick: () => { editingFrame = card.frame; outlineDraft = null; renderOutline(); updateApprovalControls(); $("outline-list").querySelector(".template-editor input")?.focus(); } }),
              el("button", { class: "btn btn-ghost btn-small", type: "button", disabled: !canEdit, dataset: { regenerateOutline: card.frame },
                onclick: () => regenerateOutlineCard(card) }, "이 카드만 다시 만들기 ", el("span", { class: "btn-tag demo-only", textContent: "데모" })))),
        ),
      );
    }
    $("outline-version").textContent = `${job.outline.version}번째 구성안`;
    const partial = job.research && (job.research.partial || (job.researchStage || {}).forced);
    gapBox($("outline-gap"), partial ? job.researchGap : null, "자료가 부족한 상태로 작성한 구성안이에요",
      partial ? "찾지 못한 정보는 비워 뒀어요. 필요하면 카드에서 직접 채우거나, 자료를 보완해 구성안을 다시 만들어 주세요." : "");
    renderTypeSwitch();
    renderSlotSuggestions();
    drawOutlinePreviews();
    updateApprovalControls();
  }

  async function drawOutlinePreviewsNow() {
    if (!isTemplateJob() || !job.outline) return;
    for (const card of job.outline.cards) {
      const tile = outlineTile(card.frame);
      const spec = templateSpec(card, editingFrame === card.frame ? outlineDraft : null);
      const key = JSON.stringify([spec, imageVersions(spec), "outline"]);
      if (key === tile.key) continue;
      tile.key = key;
      try {
        const result = await drawTemplate(tile.canvas, spec, true);
        tile.overflow = result.overflowFields;
        tile.missing = result.missingImages;
        tile.canvas.dataset.overflow = String(result.overflow);
        const message = templateWarning(templateFor(card.frame), result);
        tile.warning.textContent = message;
        tile.warning.hidden = !message;
      } catch (error) {
        tile.warning.textContent = error.message;
        tile.warning.hidden = false;
      }
    }
    updateApprovalControls();
  }

  function drawOutlinePreviews() {
    outlineChain = outlineChain.then(drawOutlinePreviewsNow, drawOutlinePreviewsNow);
    return outlineChain;
  }

  // ---------- 구성안 ----------
  function counter(input, max, node) {
    const update = () => {
      const length = input.value.replace(/\r?\n/g, "").length;
      node.textContent = `${length} / ${max}자`;
      node.classList.toggle("is-over", length > max);
    };
    input.addEventListener("input", update);
    update();
  }

  function editField(label, control, max) {
    const count = el("small", { class: "hint" });
    if (max) counter(control, max, count);
    return el("label", { class: "edit-field" }, el("span", { textContent: label }), control, max ? count : "");
  }

  function outlineEditor(card) {
    const role = el("input", { type: "text", value: card.role, name: "role" });
    const title = el("input", { type: "text", value: card.title, name: "title" });
    const body = el("textarea", { value: card.body, rows: 3, name: "body" });
    const source = el("input", { type: "text", value: card.source, name: "source", placeholder: "출처: 공식 사이트 (없으면 비워 두세요)" });
    const error = el("p", { class: "error", role: "alert", hidden: true });
    const save = el("button", { class: "btn btn-primary btn-small", type: "submit", textContent: "저장" });
    const approved = job.outline.approved;
    return el(
      "form",
      {
        class: "outline-editor",
        dataset: { editor: card.frame },
        onsubmit: async (e) => {
          e.preventDefault();
          save.disabled = true;
          try {
            const next = await api(`/api/jobs/${job.id}/outline/cards/${card.frame}`, jsonInit("PUT", { role: role.value, title: title.value, body: body.value, source: source.value }));
            editingFrame = null;
            await setJob(next);
            renderOutline();
          } catch (err) {
            error.textContent = err.message;
            error.hidden = false;
            save.disabled = false;
          }
        },
      },
      editField("역할", role, 10),
      editField("제목", title, 20),
      editField("본문", body, 80),
      editField("출처", source, 30),
      approved ? el("p", { class: "notice", textContent: "내용을 바꿔 저장하면 승인이 해제돼서 구성안과 디자인을 다시 승인해야 해요." }) : "",
      error,
      el("div", { class: "actions" },
        save,
        el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "취소", onclick: () => { editingFrame = null; renderOutline(); } })),
    );
  }

  function renderOutline() {
    if (isTemplateJob()) return renderTemplateOutline();
    const list = $("outline-list");
    list.replaceChildren();
    const issues = job.outline.issues || {};
    const canEdit = ["waiting_outline", "waiting_preview", "done"].includes(job.state);
    for (const card of job.outline.cards) {
      if (editingFrame === card.frame) {
        list.append(el("li", { class: "outline-item is-editing", dataset: { frame: card.frame } }, outlineEditor(card)));
        continue;
      }
      const issue = issues[card.frame] || { errors: [], warnings: [] };
      const notes = [...issue.errors.map((t) => el("p", { class: "outline-issue is-error", textContent: t })),
        ...issue.warnings.map((t) => el("p", { class: "outline-issue", textContent: t }))];
      list.append(
        el("li", { class: "outline-item", dataset: { frame: card.frame } },
          el("span", { class: "outline-role", textContent: card.role }),
          el("div", { class: "outline-content" },
            el("span", { class: "outline-title", textContent: card.title }),
            card.edited ? el("span", { class: "edited-mark", textContent: "직접 수정" }) : job.mode === "ai" ? tag("AI 작성", "real") : tag("예시 내용"),
            el("p", { class: "outline-body", textContent: card.body }),
            el("p", { class: "outline-source", textContent: card.source || "출처 없음" }),
            ...(job.mode === "ai" && sourcesOf(card).length
              ? [el("div", { class: "card-links" }, ...sourcesOf(card).map(sourceLink))]
              : []),
            ...notes),
          el("div", { class: "outline-buttons" },
            el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "수정", disabled: !canEdit, dataset: { edit: card.frame }, onclick: () => { editingFrame = card.frame; renderOutline(); updateApprovalControls(); $("outline-list").querySelector("input")?.focus(); } }),
            el("button", { class: "btn btn-ghost btn-small", type: "button", disabled: !canEdit, dataset: { regenerateOutline: card.frame },
              onclick: () => regenerateOutlineCard(card) }, "이 카드만 다시 만들기 ", el("span", { class: "btn-tag demo-only", textContent: "데모" })))),
      );
    }
    $("outline-version").textContent = `${job.outline.version}번째 구성안`;
    updateApprovalControls();
  }

  async function regenerateOutlineCard(card) {
    const warn = card.edited ? "이 카드에 직접 쓴 내용이 예시 문구로 바뀌어요. " : "";
    const revoke = job.outline.approved ? "승인도 해제돼요. " : "";
    if ((warn || revoke) && !confirm(`${warn}${revoke}다시 만들까요?`)) return;
    await action(`outline/cards/${card.frame}/regenerate`);
    renderOutline();
  }

  function approvalBadge(node, approved, label) {
    node.textContent = approved ? `${label} 승인됨` : `${label} 승인 필요`;
    node.className = `approval ${approved ? "is-approved" : "is-needed"}`;
  }

  function updateApprovalControls() {
    if (!job) return;
    if (job.outline) {
      const waiting = job.state === "waiting_outline";
      approvalBadge($("outline-approval"), job.outline.approved, "구성안");
      const errors = Object.values(job.outline.issues || {}).some((i) => i.errors.length);
      // 템플릿 작업은 실제로 그려 보고 칸을 넘친 글자가 있으면 승인하지 못하게 합니다
      const overflow = isTemplateJob() && [...outlineTiles.values()].some((t) => t.overflow.length);
      const locked = Boolean(editingFrame) || errors || overflow;
      $("outline-approve").hidden = !waiting;
      $("outline-approve").disabled = locked;
      $("outline-approve").dataset.locked = locked ? "true" : "";
      $("outline-hint").textContent = editingFrame ? "수정을 저장하거나 취소하면 승인할 수 있어요."
        : errors ? "빨간 표시가 있는 카드를 수정해야 승인할 수 있어요."
          : overflow ? "글자가 칸을 넘친 카드가 있어요. 문구를 줄여야 승인할 수 있어요." : "";
    }
    if (job.preview) {
      approvalBadge($("preview-approval"), job.preview.approved, "디자인");
      const waiting = job.state === "waiting_preview";
      const overflow = document.querySelector('canvas[data-overflow="true"]');
      $("preview-approve").hidden = !waiting;
      $("preview-approve").dataset.locked = overflow ? "true" : "";
      if (overflow) $("preview-approve").disabled = true;
      $("preview-hint").textContent = overflow
        ? isTemplateJob() ? "글자가 칸을 넘친 카드가 있어요. 3단계 구성안에서 문구를 줄여야 승인할 수 있어요." : "글자가 칸을 넘친 카드가 있어요. 다시 디자인하거나 문구를 줄여야 승인할 수 있어요."
        : job.state === "done" ? "카드를 바꾸면 승인이 해제돼서 다시 승인해야 해요." : "";
    }
  }

  // ---------- 카드 미리보기 ----------
  function theme() {
    const design = job.designTheme;
    if (design && design.source === "ai") return { ...design.palette, fonts: design.fonts };
    return options.styles.find((s) => s.id === job.style);
  }

  function canvasKeyOf(card) {
    if (card.spec.version === 3) return JSON.stringify([card.spec, imageVersions(card.spec)]);
    const image = card.spec.elements.find((e) => e.type === "image" && e.assetId);
    const asset = image && job.assets.find((a) => a.id === image.assetId);
    return JSON.stringify([card.spec, asset && asset.cutout ? asset.cutout.version : 0, theme()]);
  }

  function imageSelect(card) {
    const current = job.cardImages ? job.cardImages[card.frame] : null;
    const select = el("select", {
      "aria-label": `${card.frame} 이미지 선택`,
      dataset: { imageSelect: card.frame },
      onchange: (e) => {
        const [assetId, variant] = e.target.value ? e.target.value.split(":") : [null, "original"];
        action(`preview/cards/${card.frame}/image`, jsonInit("PUT", { assetId, variant }));
      },
    });
    select.append(el("option", { value: "", textContent: "이미지 사용 안 함", selected: !current }));
    for (const asset of permittedAssets()) {
      const variants = hasCutout(asset) ? [["original", "원본"], ["cutout", "배경 제거"]] : [["original", "원본"]];
      for (const [variant, label] of variants) {
        const value = `${asset.id}:${variant}`;
        select.append(el("option", { value, textContent: `${asset.name} · ${label}`, selected: Boolean(current) && current.assetId === asset.id && current.variant === variant }));
      }
    }
    return select;
  }

  function designRequestBlock(card) {
    const requests = (job.designRequests || {})[card.frame] || [];
    const input = el("textarea", {
      rows: 2,
      maxLength: options.limits.designRequestMax,
      value: requestDrafts.get(card.frame) || "",
      placeholder: "예: 이미지를 더 크게 배치해 줘.",
      "aria-label": `${card.frame} 디자인 수정 요청`,
      dataset: { requestInput: card.frame },
      oninput: (e) => requestDrafts.set(card.frame, e.target.value),
    });
    const list = el("ul", { class: "request-list" });
    const ai = job.mode === "ai";
    for (const request of requests) list.append(el("li", { textContent: ai ? `${request.text} (${request.status})` : request.text }));
    const details = el(
      "details",
      {
        class: "request-box",
        open: openRequests.has(card.frame),
        ontoggle: (e) => (e.target.open ? openRequests.add(card.frame) : openRequests.delete(card.frame)),
      },
      el("summary", { textContent: requests.length ? `디자인 수정 요청 (${requests.length})` : "디자인 수정 요청" }),
      input,
      el("button", {
        class: `btn ${ai ? "btn-primary" : "btn-ghost"} btn-small`,
        type: "button",
        textContent: ai ? "이 요청으로 AI 수정" : "요청 저장",
        dataset: { requestSave: card.frame },
        onclick: async () => {
          const text = input.value.trim();
          if (!text) return;
          openRequests.add(card.frame);
          requestDrafts.delete(card.frame);
          if (ai) await action(`preview/cards/${card.frame}/ai-redesign`, jsonInit("POST", { text }));
          else await action(`preview/cards/${card.frame}/design-requests`, jsonInit("POST", { text }));
        },
      }),
      ai
        ? el("p", { class: "request-note", textContent: "이 카드만 다시 디자인해요. 문구와 다른 카드는 그대로예요." })
        : el("p", { class: "request-note" }, tag("AI 미연결"), " 요청은 저장만 돼요. 카드는 아직 바뀌지 않아요."),
      list,
      ai ? "" : el("button", { class: "btn btn-ghost btn-small", type: "button", disabled: true, dataset: { locked: "true", aiRegenerate: card.frame }, title: "실제 AI 모드에서 쓸 수 있어요", textContent: "이 카드 AI 재생성 (실제 AI 모드)" }),
    );
    return details;
  }

  function tileControls(card) {
    if (card.spec.version === 3) {
      return [el("div", { class: "card-meta" }, el("b", { textContent: `${card.frame} · ${card.layoutLabel}` }), el("small", { textContent: "디자인 고정" })),
        slotControls(card.frame, "preview"), el("p", { class: "request-note", textContent: "문구는 3단계 구성안에서 고칠 수 있어요." })];
    }
    const meta = el("div", { class: "card-meta" }, el("b", { textContent: `${card.frame} · ${card.layoutLabel}` }));
    if (card.layoutName === "cover") meta.append(el("small", { textContent: "표지 고정" }));
    const buttons = el("div", { class: "tile-buttons" });
    if (job.mode === "ai" || card.layoutName !== "cover") {
      buttons.append(
        el("button", { class: "btn btn-ghost btn-small", type: "button", dataset: { regenerate: card.frame }, onclick: () => action(`preview/cards/${card.frame}/regenerate`) },
          job.mode === "ai" ? "AI 다시 디자인" : "다시 배치 ", job.mode === "ai" ? "" : el("span", { class: "btn-tag", textContent: "데모" })),
      );
    }
    if (card.previous) {
      buttons.append(el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "수정 전후 보기", dataset: { compare: card.frame }, onclick: () => openCompare(card.frame) }));
    }
    return [meta, el("label", { class: "tile-image" }, el("span", { textContent: "이 카드의 이미지" }), imageSelect(card)), buttons, designRequestBlock(card)];
  }

  function controlsKeyOf(card) {
    return JSON.stringify([job.mode, card.layoutName, Boolean(card.previous), isTemplateJob() ? (job.slotImages || {})[card.frame] : job.cardImages && job.cardImages[card.frame],
      (job.designRequests || {})[card.frame], visibleAssets().map((a) => [a.id, a.name, a.rights, hasCutout(a), a.useVariant, a.cutout && a.cutout.status]),
      (job.slotSuggestions || {})[card.frame], job.state]);
  }

  async function drawCard(canvas, spec) {
    if (spec.version === 3) return drawTemplate(canvas, spec);
    return SemogwiRenderer.render(canvas, spec, theme(), { demo: job.demo, assetUrl });
  }

  async function renderPreviewNow() {
    const grid = $("card-grid");
    await SemogwiRenderer.fontsReady(theme());
    grid.dataset.ready = "false";
    const ordered = [...job.preview.cards].sort((a, b) => FRAMES.indexOf(a.frame) - FRAMES.indexOf(b.frame));
    for (const card of ordered) {
      let tile = tiles.get(card.frame);
      if (!tile) {
        const canvas = el("canvas", { width: SemogwiRenderer.WIDTH, height: SemogwiRenderer.HEIGHT, dataset: { frame: card.frame } });
        canvas.setAttribute("role", "img");
        const warning = el("p", { class: "card-warning", hidden: true });
        const controls = el("div", { class: "tile-controls" });
        const root = el("article", { class: "card-tile", dataset: { tile: card.frame } }, canvas, warning, controls);
        tile = { root, canvas, controls, warning, canvasKey: "", controlsKey: "" };
        tiles.set(card.frame, tile);
        grid.append(root);
      }
      grid.append(tile.root); // 화면 순서를 card-01 ~ card-05로 맞춥니다 (PNG 파일 이름·ZIP 순서와 같음)
      const controlsKey = controlsKeyOf(card);
      if (controlsKey !== tile.controlsKey) {
        tile.controlsKey = controlsKey;
        tile.controls.replaceChildren(...tileControls(card));
      }
      // 바뀐 카드만 다시 그립니다. 다른 카드는 그대로 둡니다.
      const canvasKey = canvasKeyOf(card);
      if (canvasKey !== tile.canvasKey) {
        tile.canvasKey = canvasKey;
        tile.canvas.setAttribute("aria-label", `${card.frame} 미리보기, ${card.layoutLabel} 레이아웃`);
        try {
          const result = await drawCard(tile.canvas, card.spec);
          tile.canvas.dataset.overflow = String(result.overflow);
          const message = card.spec.version === 3
            ? templateWarning(options.templates[card.spec.template], result)
            : result.overflow ? "글자가 칸을 넘쳤어요. 다시 배치하거나 문구를 줄여 주세요." : "";
          tile.warning.hidden = !message;
          tile.warning.textContent = message;
        } catch (error) {
          tile.warning.hidden = false;
          tile.warning.textContent = error.message;
        }
      }
    }
    grid.dataset.ready = "true";
  }

  function renderPreview() {
    renderChain = renderChain.then(renderPreviewNow, renderPreviewNow);
    return renderChain;
  }

  async function openCompare(frame) {
    const card = job.preview.cards.find((c) => c.frame === frame);
    if (!card || !card.previous) return;
    compareFrame = frame;
    $("compare-title").textContent = `${frame} 수정 전후 비교`;
    await SemogwiRenderer.fontsReady(theme());
    await drawCard($("compare-before"), card.previous.spec);
    await drawCard($("compare-after"), card.spec);
    $("compare-dialog").showModal();
  }

  // ---------- PNG·ZIP ----------
  const fileName = (frame) => (job.demo ? `semogwi-demo-${frame}.png` : `semogwi-${frame}.png`);

  function canvasBlob(frame) {
    return new Promise((resolve, reject) => {
      tiles.get(frame).canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("PNG를 만들지 못했어요."))), "image/png");
    });
  }

  function saveBlob(blob, name) {
    const link = el("a", { href: URL.createObjectURL(blob), download: name });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 2000);
  }

  function publishWarnings() {
    return ((job.outline || {}).publishWarnings) || [];
  }

  function warningBox(node, title) {
    const list = publishWarnings();
    node.hidden = !list.length || job.mode !== "ai";
    if (node.hidden) return;
    node.replaceChildren(el("h3", { textContent: title }),
      el("ul", {}, ...list.map((w) => el("li", { textContent: w.frame ? `${w.frame} · ${w.text}` : w.text }))),
      el("small", { textContent: "저장은 막지 않아요. 게시 전에 한 번 더 확인해 주세요." }));
  }

  // 처음 저장할 때 한 번만 확인합니다 (저장 자체는 막지 않음)
  function confirmDownload() {
    if (job.mode !== "ai" || !publishWarnings().length || warnedDownloads.has(job.id)) return true;
    const ok = confirm(`확인되지 않은 중요 정보가 ${publishWarnings().length}건 있어요. 목록을 확인했나요? 그래도 PNG로 저장할까요?`);
    if (ok) warnedDownloads.add(job.id);
    return ok;
  }

  async function downloadPng(frame) {
    if (!confirmDownload()) return;
    try {
      saveBlob(await canvasBlob(frame), fileName(frame));
    } catch (error) {
      show("action-error", error.message);
    }
  }

  async function downloadZip() {
    if (!confirmDownload()) return;
    $("download-zip").disabled = true;
    try {
      await renderChain;
      const files = [];
      for (const frame of FRAMES) {
        const blob = await canvasBlob(frame);
        files.push({ name: fileName(frame), bytes: new Uint8Array(await blob.arrayBuffer()) });
      }
      saveBlob(SemogwiZip.create(files), job.demo ? "semogwi-demo-cards.zip" : "semogwi-cards.zip");
    } catch (error) {
      show("action-error", error.message);
    } finally {
      $("download-zip").disabled = false;
    }
  }

  function thumbnail(frame) {
    const source = tiles.get(frame).canvas;
    const small = el("canvas", { width: 216, height: 270 });
    small.getContext("2d").drawImage(source, 0, 0, 216, 270);
    return el("img", { src: small.toDataURL("image/png"), alt: `${frame} 미리보기`, width: 216, height: 270 });
  }

  function renderDownloads() {
    warningBox($("download-warnings"), "확인되지 않은 중요 정보");
    const key = job.preview.approvalHash || "";
    if (key === downloadsKey && $("download-list").children.length) return;
    downloadsKey = key;
    const list = $("download-list");
    list.replaceChildren();
    for (const frame of FRAMES) {
      list.append(
        el("li", {}, thumbnail(frame),
          el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: `${frame}.png`, dataset: { download: frame }, onclick: () => downloadPng(frame) })),
      );
    }
  }

  // ---------- 화면 조립 ----------
  function renderView() {
    renderStepper();
    renderStepNav();
    const step = viewStep;
    const started = Boolean(job) && job.state !== "draft";
    const hasAssets = visibleAssets().length > 0;

    $("job-form").hidden = step !== 1;
    $("start").hidden = started;
    $("save-input").hidden = !started;
    $("job-summary").hidden = step === 1 || !job;
    document.querySelector(".input-panel").classList.toggle("is-summary", step !== 1);
    $("new-job").hidden = !started;

    $("empty").hidden = !(step === 1 && !hasAssets);
    $("images-panel").hidden = !(step === 1 && hasAssets);
    const stopped = job && (job.state === "failed" || job.state === "interrupted");
    $("progress").hidden = !job || !(step === 2 || job.state === "running" || stopped);
    $("outline").hidden = !(step === 3 && job && job.outline);
    const previewOpen = step === 4 && job && job.preview && !(job.state === "running" && !job.preview.approved);
    $("preview").hidden = !previewOpen;
    const downloadOpen = step === 5 && job && job.state === "done";
    $("download").hidden = !downloadOpen;
    applyMode();
    if (job) {
      renderResearch();
      renderMaterial();
    } else {
      $("research").hidden = true;
      $("material").hidden = true;
    }
    renderDetail();
  }

  async function renderJob() {
    if (job.state !== "draft") renderSummary();
    renderProgress();
    renderImages();
    if (job.outline && !editingFrame) renderOutline();
    updateApprovalControls();
    renderView();

    applyAiTask();
    if (job.aiError) show("action-error", job.aiError);
    if (job.preview) renderThemeNote();
    if (job.preview) await renderPreview();
    warningBox($("preview-warnings"), "승인 전에 확인할 정보");
    if (job.state === "done" && job.preview) renderDownloads();
    else downloadsKey = "";
    setBusy(Boolean(job.aiTask));
    updateApprovalControls();
  }

  function resetToForm() {
    clearTimeout(pollTimer);
    job = null;
    viewStep = 1;
    lastMaxStep = 0;
    editingFrame = null;
    downloadsKey = "";
    assetDrafts.clear();
    imageCardKeys.clear();
    slotPanels.clear();
    slotAdjustDrafts.clear();
    tiles.clear();
    outlineTiles.clear();
    outlineDraft = null;
    requestDrafts.clear();
    openRequests.clear();
    setUrl();
    $("job-form").reset();
    updateTopicCount();
    for (const id of ["form-error", "form-note", "job-error", "action-error"]) show(id, "");
    $("image-cards").replaceChildren();
    $("card-grid").replaceChildren();
    delete $("card-grid").dataset.ready;
    $("download-list").replaceChildren();
    for (const id of ["progress", "research", "material", "outline", "preview", "download", "ai-task"]) $(id).hidden = true;
    $("material-form").reset();
    $("detail-files").value = "";
    delete $("material-form").dataset.job;
    renderView();
    $("topic").focus();
  }

  // ---------- 조사 자료 보관함 (저장된 자료 사용 / 새로 조사하기) ----------
  const library = { key: "", versions: [], details: new Map(), timer: 0, chosenId: "", renaming: "", busy: false, error: "" };
  // 서버가 이름 변경·삭제 API를 가진 새 코드로 실행 중인지 (예전 서버면 버튼 대신 다시 시작 안내)
  const libraryManageAvailable = () => Boolean(options && (options.features || []).includes("libraryManage"));
  const RESTART_NOTE = "서버가 예전 코드로 실행 중이라 이름 변경·삭제를 쓸 수 없어요. 서버 창(run.bat)을 닫고 다시 실행한 뒤 새로고침해 주세요.";
  // 서버에 그 주소가 없을 때(예전 서버) FastAPI가 주는 기본 메시지를 알아보기 쉬운 안내로 바꿉니다
  const libraryError = (error) => (/^(Not Found|Method Not Allowed)$/.test(error.message) ? RESTART_NOTE : error.message);
  const LIBRARY_NAME_MAX = 40;
  const selectedResearchMode = () => ($("job-form").elements.researchMode && $("job-form").elements.researchMode.value) || "new";

  function scheduleLibrary() {
    clearTimeout(library.timer);
    library.timer = setTimeout(loadLibrary, 350);
  }

  async function loadLibrary() {
    const input = readInput();
    const visible = selectedMode() === "ai" && (!job || job.state === "draft") && Boolean(input.topic);
    $("research-field").hidden = !visible;
    if (!visible) return;
    const key = `${input.contentType}|${input.topic}`;
    if (key !== library.key) {
      library.key = key;
      try {
        const query = new URLSearchParams({ topic: input.topic, contentType: input.contentType || "" });
        library.versions = (await api(`/api/research-library?${query}`)).versions;
      } catch {
        library.versions = [];
      }
      const saved = [...$("job-form").elements.researchMode].find((r) => r.value === "saved");
      const fresh = [...$("job-form").elements.researchMode].find((r) => r.value === "new");
      saved.disabled = !library.versions.length;
      (library.versions.length ? saved : fresh).checked = true; // 저장된 자료가 있으면 기본으로 다시 써서 결과를 일관되게 합니다
    }
    renderLibrary();
  }

  // 기본 이름: 조사일 + 콘텐츠 유형. 사용자가 이름을 바꾸면 그 이름을 씁니다 (서버에 저장)
  const defaultVersionName = (v) => `${v.researchedAt} ${typeLabelOf(v.contentType)}`;
  const versionName = (v) => v.name || defaultVersionName(v);

  function versionLabel(v) {
    return `${versionName(v)} · #${v.number} · 읽은 출처 ${v.sourceCount}개`;
  }

  // 이름 변경·삭제 뒤 목록을 서버에서 다시 받아 옵니다 (새로고침해도 같은 결과)
  async function reloadLibrary() {
    library.key = "";
    library.details.clear();
    await loadLibrary();
  }

  async function renameVersion(v, name) {
    library.busy = true;
    try {
      await api(`/api/research-library/${v.id}`, jsonInit("PATCH", { name }));
      library.renaming = "";
      library.error = "";
    } catch (error) {
      library.error = libraryError(error); // 버튼 바로 아래에 보여 줍니다 (폼 맨 아래 오류 칸은 눈에 잘 안 띔)
    } finally {
      library.busy = false;
    }
    await reloadLibrary();
  }

  async function deleteVersion(v) {
    library.busy = true;
    try {
      // 지우기 전에 이 버전과 연결된 작업을 확인합니다. 작업은 자료를 복사해 두어서 지워도 내용이 바뀌지 않습니다
      const { usedBy } = await api(`/api/research-library/${v.id}/usage`);
      const running = usedBy.filter((u) => u.state === "running").length;
      const linked = usedBy.length
        ? `

이 자료와 연결된 작업 ${usedBy.length}개${running ? `(진행 중 ${running}개)` : ""}는 시작할 때 자료를 복사해 두어서 그대로 유지돼요. 다만 이 자료를 다시 골라 새 카드뉴스를 만들 수는 없어요.`
        : "";
      if (!confirm(`'${versionName(v)}' (#${v.number}) 조사 자료를 삭제할까요?
이 버전만 지워지고 되돌릴 수 없어요. 다른 버전은 그대로예요.${linked}`)) return;
      await api(`/api/research-library/${v.id}`, { method: "DELETE" });
      if (library.chosenId === v.id) library.chosenId = "";
      library.error = "";
    } catch (error) {
      library.error = libraryError(error);
      library.busy = false;
      renderLibrary();
      return;
    } finally {
      library.busy = false;
    }
    await reloadLibrary();
  }

  function libraryActions(v) {
    const error = library.error ? el("p", { class: "library-error", role: "alert", textContent: library.error }) : "";
    if (!libraryManageAvailable()) {
      return el("div", { class: "library-manage" },
        el("div", { class: "library-actions" },
          el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "이름 바꾸기", disabled: true, title: RESTART_NOTE, dataset: { libraryRename: v.id } }),
          el("button", { class: "btn btn-ghost btn-small btn-danger", type: "button", textContent: "삭제", disabled: true, title: RESTART_NOTE, dataset: { libraryDelete: v.id } })),
        el("p", { class: "library-error", role: "alert", textContent: RESTART_NOTE }));
    }
    if (library.renaming === v.id) {
      const input = el("input", { type: "text", value: versionName(v), maxLength: LIBRARY_NAME_MAX, "aria-label": "조사 버전 이름", dataset: { libraryName: v.id },
        onkeydown: (e) => {
          if (e.key === "Enter") { e.preventDefault(); renameVersion(v, input.value); } // 시작 폼이 제출되지 않게
          if (e.key === "Escape") { library.renaming = ""; renderLibrary(); }
        } });
      setTimeout(() => { input.focus(); input.select(); });
      return el("div", { class: "library-rename" },
        input,
        el("div", { class: "library-actions" },
          el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "저장", dataset: { librarySave: v.id }, onclick: () => renameVersion(v, input.value) }),
          el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "기본 이름으로", title: defaultVersionName(v), onclick: () => renameVersion(v, "") }),
          el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "취소", onclick: () => { library.renaming = ""; renderLibrary(); } })),
        el("small", { class: "hint", textContent: `${LIBRARY_NAME_MAX}자까지 · 비우면 기본 이름(${defaultVersionName(v)})으로 돌아가요. 조사 내용은 바뀌지 않아요.` }),
        error);
    }
    return el("div", { class: "library-manage" }, el("div", { class: "library-actions" },
      el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "이름 바꾸기", disabled: library.busy, dataset: { libraryRename: v.id },
        onclick: () => { library.renaming = v.id; library.error = ""; renderLibrary(); } }),
      el("button", { class: "btn btn-ghost btn-small btn-danger", type: "button", textContent: "삭제", disabled: library.busy, dataset: { libraryDelete: v.id },
        onclick: () => deleteVersion(v) })), error);
  }

  async function renderLibrary() {
    const box = $("research-library");
    const mode = selectedResearchMode();
    if (!library.versions.length) {
      box.replaceChildren();
      $("research-hint").textContent = "이 주제·유형으로 저장된 자료가 없어요. '새로 조사하기'로 AI가 조사하고, 결과는 자료 보관함에 저장돼요.";
      return;
    }
    $("research-hint").textContent = mode === "saved"
      ? "저장된 자료를 바탕으로 부족한 내용을 AI가 추가 조사해 합쳐요. 기존 값은 지우지 않고, 다른 값이 나오면 확인을 받아요. 합친 자료를 확인·수정한 뒤 구성안을 만들고, 새 버전으로 저장돼요 (기존 버전은 그대로)."
      : "AI가 새로 조사해 새 버전으로 저장해요. 저장된 자료는 그대로 남아요.";
    if (mode !== "saved") {
      box.replaceChildren(el("small", { class: "hint", textContent: `저장된 자료 ${library.versions.length}개: ${versionLabel(library.versions[0])}` }));
      return;
    }
    const select = el("select", { id: "research-version", "aria-label": "사용할 조사 버전",
      onchange: (e) => { library.chosenId = e.target.value; library.renaming = ""; library.error = ""; renderLibrary(); } });
    const current = box.querySelector("#research-version");
    const chosen = library.versions.find((v) => v.id === library.chosenId) || (current && library.versions.find((v) => v.id === current.value)) || library.versions[0];
    library.chosenId = chosen.id;
    for (const v of library.versions) select.append(el("option", { value: v.id, textContent: versionLabel(v), selected: v.id === chosen.id }));
    const detail = el("div", { class: "library-detail" }, el("small", { class: "hint", textContent: "자료를 불러오는 중이에요" }));
    box.replaceChildren(el("label", { class: "edit-field" }, el("span", { textContent: "조사 버전" }), select),
      libraryActions(chosen),
      chosen.staleNote ? el("p", { class: "notice", textContent: chosen.staleNote }) : "", detail);
    if (!library.details.has(chosen.id)) {
      try {
        library.details.set(chosen.id, await api(`/api/research-library/${chosen.id}`));
      } catch (error) {
        detail.replaceChildren(el("small", { class: "error", textContent: error.message }));
        return;
      }
    }
    detail.replaceChildren(libraryDetail(library.details.get(chosen.id)));
  }

  // 저장된 자료 확인: 항목별 값과 확인 상태, 친구·가족, 출처와 조사일
  function libraryDetail(version) {
    const items = (version.research.items || []).filter((i) => i.value);
    const people = version.people || {};
    const list = el("ul", { class: "library-items" }, ...items.map((item) =>
      el("li", { dataset: { state: item.state } }, `${item.label}: ${item.value}`)));
    const details = version.peopleDetails || {};
    const groups = Object.entries({ friends: "친구", family: "가족" }).filter(([k]) => (people[k] || []).length)
      .flatMap(([k, label]) => (details[k] || people[k].map((name) => ({ name }))).map((p) =>
        el("li", {}, el("b", { textContent: `${label} ${p.name}` }), p.relation ? ` (${p.relation})` : "", ` · TMI: ${p.tmi || "찾지 못함"}`)));
    const sources = el("ul", { class: "library-sources" }, ...version.sources.map((s) =>
      el("li", { dataset: { verification: s.verification } }, /^https?:\/\//.test(s.url) ? el("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", textContent: s.title || s.url }) : s.title)));
    return el("details", { class: "library-view" },
      el("summary", { textContent: `자료 보기 · 조사일 ${version.researchedAt} · 항목 ${items.length}개 · 사실 ${version.factCount}개${version.hasUserMaterial ? " · 사용자 제공 자료 포함" : ""}` }),
      groups.length ? el("ul", { class: "library-people" }, ...groups) : "", list,
      el("h4", { class: "sub-title", textContent: "출처" }), sources);
  }

  function renderResearchVersion() {
    const node = $("research-version-note");
    const info = job && job.researchVersion;
    const fromLibrary = job && job.research && job.research.fromLibrary;
    node.hidden = !info;
    if (!info) return;
    if (info.source === "more") {
      const base = info.basedOn || {};
      node.textContent = `추가 조사 ${info.round}회차 결과를 통합해 새 버전 #${info.number}로 저장했어요.${base.number ? ` 이전 버전 #${base.number}은 그대로예요.` : ""}`;
    } else if (info.source === "supplement") {
      const base = info.basedOn || {};
      node.textContent = `저장된 자료 #${base.number}을 바탕으로 부족한 내용을 추가 조사해 합쳤고, 새 버전 #${info.number}(조사일 ${info.researchedAt})로 저장했어요. 바탕 버전은 그대로예요.`;
    } else if (info.source === "saved" && job.researchBase) {
      node.hidden = job.state === "waiting_research"; // 검토 중에는 아래 '통합된 자료 검토'에서 같은 내용을 보여 줍니다
      node.textContent = `저장된 자료 #${info.number}(조사일 ${info.researchedAt})를 바탕으로 추가 조사했어요.`;
    } else {
      node.textContent = info.source === "saved"
        ? `저장된 자료 #${info.number}(조사일 ${info.researchedAt})를 사용했어요. 새 웹 조사는 하지 않았어요.${fromLibrary && fromLibrary.staleNote ? ` ${fromLibrary.staleNote}` : ""}`
        : `새로 조사한 자료를 보관함에 #${info.number}(조사일 ${info.researchedAt})로 저장했어요. 같은 주제로 다시 만들 때 '저장된 자료 사용'을 고를 수 있어요.`;
    }
  }

  // ---------- 시작 ----------
  function bindEvents() {
    $("job-form").addEventListener("submit", submitForm);
    $("topic").addEventListener("input", () => {
      updateTopicCount();
      $("topic").removeAttribute("aria-invalid");
    });
    for (const id of ["topic", "url", "notes", "notes-kind", "notes-url", "type-options"]) $(id).addEventListener("change", saveDraftInput);
    $("images").addEventListener("change", (e) => {
      const files = [...e.target.files];
      e.target.value = "";
      addFiles(files);
    });
    const zone = $("dropzone");
    for (const type of ["dragenter", "dragover"]) {
      zone.addEventListener(type, (e) => {
        e.preventDefault();
        zone.classList.add("is-over");
      });
    }
    for (const type of ["dragleave", "drop"]) {
      zone.addEventListener(type, (e) => {
        e.preventDefault();
        zone.classList.remove("is-over");
      });
    }
    zone.addEventListener("drop", (e) => addFiles([...e.dataTransfer.files]));

    $("outline-approve").addEventListener("click", () => action("outline/approve"));
    $("outline-regenerate").addEventListener("click", () => {
      const edited = job.outline.cards.some((c) => c.edited);
      const warn = edited ? "직접 수정한 내용까지 모두 예시 문구로 바뀌어요. " : "";
      const revoke = job.outline.approved ? "승인도 해제돼요. " : "";
      if ((warn || revoke) && !confirm(`${warn}${revoke}전체를 다시 만들까요?`)) return;
      action("outline/regenerate");
    });
    $("preview-approve").addEventListener("click", () => action("preview/approve"));
    $("preview-regenerate").addEventListener("click", () => {
      if (job.mode === "ai" && !confirm("카드 5장을 모두 다시 디자인해요. Pro 사용 한도가 차감돼요. 진행할까요?")) return;
      action("preview/regenerate");
    });
    $("retry").addEventListener("click", () => action("retry"));
    $("material-retry").addEventListener("click", () => action("retry"));
    $("detail-upload").addEventListener("click", uploadDetail);
    $("detail-fetch").addEventListener("click", fetchDetail);
    $("detail-extract").addEventListener("click", () => detailAction("detail-images/extract", { method: "POST" }));
    $("url").addEventListener("input", () => { if (viewStep === 1) renderDetail(); });
    $("material-form").addEventListener("submit", submitMaterial);
    $("material-source-add").addEventListener("click", () => {
      if ($("material-sources").children.length < SOURCE_MAX) $("material-sources").append(materialSourceRow({}));
      syncSourceAdd();
    });
    $("material-fill").addEventListener("click", () => { $("material-form").elements.extra.focus(); $("material-form").scrollIntoView({ block: "start", behavior: "smooth" }); });
    $("material-compose").addEventListener("click", async () => {
      if (!confirm("지금 자료로 구성안을 써요. 찾지 못한 정보는 비워 두고 지어내지 않아요. 진행할까요?")) return;
      await action("research/compose-current");
    });
    for (const radio of $("job-form").elements.mode) radio.addEventListener("change", applyMode);
    for (const radio of $("job-form").elements.mode) radio.addEventListener("change", scheduleLibrary);
    for (const radio of $("job-form").elements.researchMode) radio.addEventListener("change", renderLibrary);
    $("topic").addEventListener("input", scheduleLibrary);
    $("type-options").addEventListener("change", scheduleLibrary);
    $("url").addEventListener("input", applyMode);
    $("new-job").addEventListener("click", resetToForm);
    $("edit-input").addEventListener("click", () => goToStep(1));
    $("step-prev").addEventListener("click", () => goToStep(viewStep - 1));
    $("step-next").addEventListener("click", () => goToStep(viewStep + 1));
    $("download-zip").addEventListener("click", downloadZip);
    $("compare-close").addEventListener("click", () => $("compare-dialog").close());
    $("compare-restore").addEventListener("click", async () => {
      $("compare-dialog").close();
      await action(`preview/cards/${compareFrame}/restore`);
    });
  }

  async function init() {
    bindEvents();
    const params = new URLSearchParams(location.search);
    $("debug-footer").hidden = params.get("debug") !== "1";
    try {
      options = await api("/api/options");
    } catch (error) {
      show("form-error", error.message);
      $("start").disabled = true;
      return;
    }
    renderOptions();
    const aiRadio = [...$("job-form").elements.mode].find((r) => r.value === "ai");
    const demoRadio = [...$("job-form").elements.mode].find((r) => r.value === "demo");
    aiRadio.disabled = !options.ai.available;
    (options.ai.available ? aiRadio : demoRadio).checked = true;
    updateTopicCount();
    renderView();
    const jobId = params.get("job");
    if (jobId) {
      try {
        const loaded = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
        job = loaded;
        fillForm();
        await setJob(loaded);
      } catch {
        job = null;
        setUrl();
      }
    }
  }

  init();
})();

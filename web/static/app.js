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
    compose: "AI가 입력한 자료로 구성안을 쓰고 있어요. 사이트에는 접속하지 않아요.",
    design: "AI가 카드 5장을 다시 디자인하고 있어요. 1~3분 걸릴 수 있어요.",
    redesign: "AI가 이 카드만 다시 디자인하고 있어요. 1분 안팎 걸려요. 다른 카드는 그대로예요.",
    retype: "AI가 바뀐 유형의 템플릿에 맞춰 구성안을 다시 쓰고 있어요. 저장된 조사 결과만 쓰고 검색은 다시 하지 않아요.",
  };
  const STATUS_TEXT = {
    running: "예시 작업을 진행하고 있어요. 실제 조사나 AI 생성은 하지 않아요.",
    waiting_outline: "구성안을 확인하고 있어요. 승인해야 다음 단계로 넘어가요.",
    waiting_material: "자료가 더 필요해요. 아래에 직접 입력하면 이어서 진행해요.",
    waiting_preview: "카드 디자인을 확인하고 있어요. 승인해야 PNG를 받을 수 있어요.",
    done: "완료됐어요. 5단계에서 샘플 PNG를 받을 수 있어요.",
    failed: "제작이 멈췄어요.",
    interrupted: "작업이 중단됐어요.",
  };
  const STEP_TEXT = { pending: "대기", active: "진행 중", done: "완료", failed: "실패", waiting: "승인 대기", material: "자료 입력 대기", skipped: "자동 조사 안 함" };
  const MATERIAL_LABELS = {
    goods: { name: "상품명", price: "가격", seller: "판매처", features: "특징" },
    popup: { name: "행사명", price: "입장료·가격", seller: "장소", features: "기간·예약 방법 등" },
    collab: { name: "콜라보 이름", price: "가격", seller: "판매처·장소", features: "콜라보 내용·기간" },
    character: { name: "캐릭터 이름", price: "관련 가격", seller: "공식 채널", features: "특징" },
  };

  let options = null;
  let job = null;
  let viewStep = 1;
  let lastMaxStep = 0;
  let pollTimer = null;
  let editingFrame = null;
  let renderChain = Promise.resolve();
  let compareFrame = null;
  let downloadsKey = "";

  const assetDrafts = new Map(); // 아직 저장되지 않은 권한·출처 입력
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

  function verifyBadge(source) {
    if (source.verification === "user_provided") return el("span", { class: "verify is-user", textContent: "사용자 제공" });
    const text = { fetched: "페이지 읽음", search_result: "검색 목록에만 있음", restricted: "자동 접근 금지" }[source.verification] || "미확인";
    return el("span", { class: `verify ${source.verification === "fetched" ? "is-ok" : "is-no"}`, textContent: text });
  }

  function sourceLink(source) {
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
    renderChecklist(research);
    renderProblems(research);
    $("research-queries").replaceChildren(...research.queries.map((q) => el("li", { textContent: q })));
    $("research-sources").replaceChildren(...research.sources.map((s) =>
      el("li", { dataset: { verification: s.verification } }, verifyBadge(s),
        s.kind === "user" ? "" : el("span", { class: "tag tag-demo", textContent: s.officialBasis === "registered" ? "공식(등록)" : s.kind === "official" ? "공식(AI 판단)" : "2차 출처" }),
        s.verification === "fetched" && s.officialBasis !== "registered" ? el("span", { class: "tag tag-demo", textContent: "이용 조건 미확인" }) : "", sourceLink(s))));
    $("research-facts").replaceChildren(...research.facts.map((f) =>
      el("li", { dataset: { origin: f.origin || "ai" } }, factBadge(f, research), ` ${f.text}`)));
  }

  function factBadge(fact, research) {
    if (fact.origin === "user") return el("span", { class: "verify is-user", textContent: "사용자 제공" });
    const read = (fact.sourceIds || []).some((id) => (research.sources.find((s) => s.id === id) || {}).verification === "fetched");
    return el("span", { class: `verify ${read ? "is-ok" : "is-no"}`, textContent: read ? "페이지에서 확인" : "확인 안 됨" });
  }

  // 조사 항목·필드의 근거 상태 (서버 app/research.py와 같은 이름)
  const ITEM_STATE = {
    verified: ["공식 확인", "is-ok"], secondary: ["2차 자료", "is-ok"], user: ["사용자 제공", "is-user"], listed: ["검색 목록만", "is-no"],
    unverified: ["근거 없음", "is-no"], conflict: ["출처 충돌", "is-no"], missing: ["정보 확인 필요", "is-no"],
  };
  const stateBadge = (state) => el("span", { class: `verify ${(ITEM_STATE[state] || ["", "is-no"])[1]}`, dataset: { state }, textContent: (ITEM_STATE[state] || [state])[0] });

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

  function renderChecklist(research) {
    const items = research.items || [];
    $("research-checklist-wrap").hidden = !items.length;
    const editable = isTemplateJob() && job.outline && ["waiting_outline", "waiting_preview", "done"].includes(job.state);
    $("research-checklist").replaceChildren(...items.map((item) => {
      const detail = el("div", { class: "item-detail" }, el("span", { textContent: item.value || "찾지 못했어요" }));
      if (item.quote) detail.append(el("q", { textContent: item.quote }));
      const links = sourceLinksOf(item.sourceIds || []);
      if (links.length) detail.append(el("span", {}, "출처: ", ...links.flatMap((a, i) => (i ? [", ", a] : [a]))));
      for (const alt of item.alternatives || []) {
        detail.append(el("span", {}, `다른 값: ${alt.value} `, ...sourceLinksOf(alt.sourceIds || [])));
      }
      const needs = ["missing", "conflict", "unverified", "listed"].includes(item.state) || (item.strict && item.state === "secondary");
      const used = editable && job.outline.cards.some((c) => templateFor(c.frame).fields.some((f) => f.item === item.key));
      if (needs && used) detail.append(el("button", { class: "btn btn-ghost btn-small", type: "button", textContent: "카드에서 입력", dataset: { jumpItem: item.key }, onclick: () => jumpToItem(item.key) }));
      return el("li", { dataset: { item: item.key, state: item.state } }, stateBadge(item.state), el("b", { textContent: item.label }), detail);
    }));
  }

  function renderProblems(research) {
    const problems = [
      ...(research.policyStops || []).map((s) => `${s.name}: 이용규약상 자동 수집이 금지된 사이트라 읽지 않았어요`),
      ...(research.searchFailures || []).map((f) => `검색 "${f.query}": ${f.reason}`),
      ...(research.fetchFailures || []).map(failureText),
      ...(research.fetched || []).filter((f) => f.denied).map((f) => `${f.url}: 접근 제한 규칙으로 요청하지 않았어요`),
    ];
    $("research-problems-wrap").hidden = !problems.length;
    $("research-problems").replaceChildren(...problems.map((text) => el("li", { textContent: text })));
  }

  function failureText(failure) {
    const reason = failure.label || "접속하지 못했어요";
    const code = failure.code ? ` (HTTP ${failure.code})` : "";
    return `${failure.host}: ${reason}${code}, ${failure.attempts}번 시도`;
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
    $("material-reason").textContent = reason;
    const missing = (research && research.missing) || [];
    $("material-failures").replaceChildren(
      ...failures.map((f) => el("li", { textContent: failureText(f) })),
      ...(job.state === "waiting_outline" ? [] : missing.map((m) => el("li", { textContent: `부족한 자료: ${m}` }))),
    );
    const labels = MATERIAL_LABELS[job.contentType] || { name: "이름", price: "가격", seller: "판매처·출처", features: "특징·내용" };
    for (const [key, text] of Object.entries(labels)) $(`material-${key}-label`).textContent = text;
    const form = $("material-form");
    const saved = job.userMaterial || {};
    if (form.dataset.job !== job.id) {
      form.dataset.job = job.id;
      for (const key of ["name", "price", "seller", "sourceUrl", "features", "pasted"]) form.elements[key].value = saved[key] || "";
      if (!saved.sourceUrl && (blocked || stop)) form.elements.sourceUrl.value = job.url || "";
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

  async function submitMaterial(event) {
    event.preventDefault();
    const form = $("material-form");
    const body = {};
    for (const key of ["name", "price", "seller", "sourceUrl", "features", "pasted"]) body[key] = form.elements[key].value.trim();
    show("material-error", "");
    if (body.pasted.length < 20 && !(body.name && body.features)) {
      show("material-error", "이름과 특징을 함께 적거나, 공식 페이지 내용을 붙여 넣어 주세요.");
      return;
    }
    if (job.state === "waiting_outline" && !confirm("지금 구성안을 새로 만들어요. 직접 수정한 내용도 바뀌어요. 진행할까요?")) return;
    try {
      await setJob(await api(`/api/jobs/${job.id}/material`, jsonInit("POST", body)));
    } catch (error) {
      show("material-error", error.message);
    }
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
    if (job.state === "waiting_material") return 2;
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

  const readInput = () => ({ topic: $("topic").value.trim(), contentType: $("job-form").elements.contentType.value, url: $("url").value.trim(), notes: $("notes").value.trim() });

  function fillForm() {
    $("topic").value = job.topic;
    $("url").value = job.url;
    $("notes").value = job.notes || "";
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

  function pendingRightsMessage() {
    for (const asset of visibleAssets()) {
      const draft = assetDrafts.get(asset.id);
      if (draft && draft.rights === "허가됨" && !draft.source.trim()) {
        return `${asset.name}: 사용 권한이 '허가됨'이면 출처를 적어 주세요.`;
      }
    }
    return "";
  }

  async function flushAssetDrafts() {
    for (const asset of visibleAssets()) {
      const draft = assetDrafts.get(asset.id);
      if (draft && (draft.rights !== asset.rights || draft.source.trim() !== asset.source)) await saveAsset(asset.id);
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
    const pending = pendingRightsMessage();
    if (pending) {
      show("form-error", pending);
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
        await setJob(await api(`/api/jobs/${job.id}/start`, jsonInit("POST", { ...input, mode: selectedMode() })));
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
    if (!assetDrafts.has(asset.id)) assetDrafts.set(asset.id, { rights: asset.rights, source: asset.source });
    return assetDrafts.get(asset.id);
  }

  async function saveAsset(assetId) {
    const draft = assetDrafts.get(assetId);
    const asset = job.assets.find((a) => a.id === assetId);
    const source = draft.source.trim();
    if (draft.rights === "허가됨" && !source) return; // 출처를 적으면 저장합니다
    if (draft.rights === asset.rights && source === asset.source) return;
    try {
      await setJob(await api(`/api/jobs/${job.id}/assets/${assetId}`, jsonInit("PATCH", { rights: draft.rights, source })));
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

    const rights = el("select", {
      "aria-label": `${asset.name} 사용 권한`,
      onchange: (e) => {
        draft.rights = e.target.value;
        hint.hidden = !(draft.rights === "허가됨" && !draft.source.trim());
        saveAsset(asset.id);
      },
    });
    for (const value of ["확인 필요", "허가됨", "허가 안 됨"]) {
      rights.append(el("option", { value, textContent: `사용 권한: ${value}`, selected: value === draft.rights }));
    }
    const source = el("input", {
      type: "text",
      value: draft.source,
      maxLength: 100,
      placeholder: "이미지 출처 (예: 직접 촬영)",
      "aria-label": `${asset.name} 출처`,
      oninput: (e) => {
        draft.source = e.target.value;
        hint.hidden = !(draft.rights === "허가됨" && !draft.source.trim());
      },
      onchange: () => saveAsset(asset.id),
    });
    const hint = el("small", { class: "hint rights-hint", textContent: "출처를 적으면 '허가됨'으로 저장돼요.", hidden: !(draft.rights === "허가됨" && !draft.source.trim()) });
    body.push(rights, source, hint);

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
      if (draft && draft.rights === asset.rights && draft.source.trim() === asset.source) assetDrafts.delete(asset.id);
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
    if (job.state === "running" || job.aiTask || visibleAssets().some(isProcessing)) pollTimer = setTimeout(poll, POLL_MS);
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
      ["참고 자료", job.notes ? `직접 입력 ${job.notes.length}자 (사용자 제공)` : "없음"],
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
    if (step.key === "layout" && job.state === "waiting_preview") return "waiting";
    return step.status;
  }

  function renderProgress() {
    const aiRunning = job.mode === "ai" && job.state === "running";
    const activeKey = (job.steps.find((s) => s.status === "active") || {}).key;
    $("status-text").textContent = aiRunning
      ? { research: "AI가 웹에서 자료를 찾고 구성안을 쓰고 있어요. 2~5분 걸릴 수 있어요.",
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
      fields: { ...inherited, ...values.fields }, source: tpl.kind !== "cover" ? values.source || "" : "",
      images: Object.fromEntries(tpl.images.map((slot) => [slot.key, slotImageFor(card.frame, slot.key)])),
    };
  }

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
  const permittedAssets = () => visibleAssets().filter((a) => a.rights === "허가됨");
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
    const source = el("input", { type: "text", maxLength: 100, placeholder: "출처 (예: 직접 촬영, 공식 사이트)", "aria-label": `${frame} ${slot.label} 출처` });
    const agree = el("input", { type: "checkbox" });
    const error = el("small", { class: "rights-hint", hidden: true });
    const button = el("button", {
      class: "btn btn-ghost btn-small", type: "button", textContent: current ? "새 이미지로 교체" : "올려서 넣기",
      dataset: { slotUpload: `${frame}:${slot.key}` },
      onclick: async () => {
        const fail = (text) => { error.textContent = text; error.hidden = false; };
        if (!file.files.length) return fail("이미지 파일을 골라 주세요.");
        if (!source.value.trim()) return fail("출처를 적어 주세요.");
        if (!agree.checked) return fail("사용 허가를 확인해 주세요.");
        const data = new FormData();
        data.append("image", file.files[0]);
        data.append("rights", "허가됨");
        data.append("source", source.value.trim());
        button.disabled = true;
        if (await slotAction(`cards/${frame}/slots/${slot.key}/upload`, { method: "POST", body: data })) {
          file.value = "";
          error.hidden = true;
        }
        button.disabled = false;
      },
    });
    return el("details", { class: "slot-upload" }, el("summary", { textContent: current ? "다른 이미지 올려서 교체" : "이 카드에 이미지 올리기" }),
      file, source, el("label", { class: "flag-field" }, agree, el("span", { textContent: "카드에 써도 되는 이미지예요 (사용 권한: 허가됨)" })), button, error);
  }

  function slotPanel(frame, slot, context) {
    const current = slotImageFor(frame, slot.key);
    const asset = current && job.assets.find((a) => a.id === current.assetId);
    const suggestion = !current && suggestionOf(frame, slot.key);
    const key = JSON.stringify([current && currentSlot(frame, slot.key), suggestion, asset, permittedAssets().map((a) => [a.id, a.name, a.useVariant, hasCutout(a)]),
      options.cutout.available, job.state]);
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
    if (current && asset) node.append(slotCompare(asset), slotBackground(frame, slot, current, asset), slotAdjust(frame, slot, current));
    node.append(slotUpload(frame, slot, current));
    slotPanels.set(cacheKey, { key, node });
    return node;
  }

  function slotControls(frame, context = "outline") {
    const slots = templateFor(frame).images;
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
    if (field.type === "list") return value.map((t) => `#${t}`).join(" ");
    if (field.type === "items") return value.map((item) => field.fields.map((sub) => item[sub.key]).filter(Boolean).join(" · ")).join("\n");
    if (field.type === "pairs") return value.map((p) => `${p.label}: ${p.value}`).join(" · ");
    return value;
  }

  function fieldSummary(card) {
    const tpl = templateFor(card.frame);
    const list = el("dl", { class: "field-list" });
    const states = ((job.outline.fieldStates || {})[card.frame]) || {};
    for (const field of tpl.fields) {
      const value = card.fields[field.key];
      const empty = field.type !== "flag" && (!value || (Array.isArray(value) && !value.length));
      const dd = el("dd", { class: empty ? "is-empty" : "", dataset: { field: field.key } });
      if (states[field.key] && job.mode === "ai") dd.append(stateBadge(states[field.key]));
      dd.append(empty ? (field.required ? "비어 있음 · 입력이 필요해요" : "비어 있음 · 카드에서 숨겨요") : fieldText(field, value));
      list.append(el("dt", { textContent: field.label }), dd);
    }
    if (tpl.kind !== "cover") list.append(el("dt", { textContent: "출처" }), el("dd", { class: card.source ? "" : "is-empty", textContent: card.source || "출처 없음" }));
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

  function templateControl(field, value) {
    if (field.type === "flag") {
      const box = el("input", { type: "checkbox", name: `field-${field.key}`, checked: Boolean(value) });
      return el("label", { class: "flag-field" }, box, el("span", { textContent: field.label }), field.hint ? el("small", { class: "hint", textContent: field.hint }) : "");
    }
    if (field.type === "text" || field.type === "multiline") {
      const input = field.type === "text"
        ? el("input", { type: "text", value: value || "", name: `field-${field.key}`, placeholder: field.default || "" })
        : el("textarea", { value: value || "", rows: 2, name: `field-${field.key}` });
      return editField(`${field.label}${field.required ? " (필수)" : ""}`, input, field.max);
    }
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

  function collectTemplate(form, card) {
    const tpl = templateFor(card.frame);
    const get = (name) => (form.elements[name] ? form.elements[name].value : "");
    const fields = {};
    for (const field of tpl.fields) {
      if (field.type === "flag") fields[field.key] = Boolean(form.elements[`field-${field.key}`] && form.elements[`field-${field.key}`].checked);
      else if (field.type === "text" || field.type === "multiline") fields[field.key] = get(`field-${field.key}`);
      else if (field.type === "list") fields[field.key] = [...Array(field.maxItems).keys()].map((i) => get(`field-${field.key}-${i}`).trim()).filter(Boolean);
      else if (field.type === "items") {
        fields[field.key] = [...Array(field.maxItems).keys()]
          .map((i) => Object.fromEntries(field.fields.map((sub) => [sub.key, get(`field-${field.key}-${i}-${sub.key}`).trim()])))
          .filter((item) => Object.values(item).some(Boolean));
      }
      else fields[field.key] = [...Array(field.maxItems).keys()].map((i) => ({ label: get(`field-${field.key}-${i}-label`).trim(), value: get(`field-${field.key}-${i}-value`).trim() }))
        .filter((p) => p.label || p.value);
    }
    return { role: get("role"), fields, source: tpl.kind !== "cover" ? get("source") : "" };
  }

  function templateEditor(card) {
    const tpl = templateFor(card.frame);
    const error = el("p", { class: "error", role: "alert", hidden: true });
    const save = el("button", { class: "btn btn-primary btn-small", type: "submit", textContent: "저장" });
    const form = el("form", { class: "outline-editor template-editor", dataset: { editor: card.frame } });
    form.append(editField("역할", el("input", { type: "text", value: card.role, name: "role" }), 10));
    for (const field of tpl.fields) form.append(templateControl(field, card.fields[field.key]));
    if (tpl.kind !== "cover") {
      form.append(editField("출처", el("input", { type: "text", value: card.source, name: "source", placeholder: "출처: 공식 사이트 (모르면 비워 두세요)" }), 30));
    }
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
            card.edited ? el("span", { class: "edited-mark", textContent: "직접 수정" }) : job.mode === "ai" ? tag("AI 작성", "real") : tag("예시 내용"),
            fieldSummary(card),
            ...(job.mode === "ai" && sourcesOf(card).length
              ? [el("div", { class: "card-links" }, ...sourcesOf(card).flatMap((s) => [verifyBadge(s), sourceLink(s)]))]
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
              ? [el("div", { class: "card-links" }, ...sourcesOf(card).flatMap((s) => [verifyBadge(s), sourceLink(s)]))]
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
    for (const asset of visibleAssets().filter((a) => a.rights === "허가됨")) {
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

  async function downloadPng(frame) {
    try {
      saveBlob(await canvasBlob(frame), fileName(frame));
    } catch (error) {
      show("action-error", error.message);
    }
  }

  async function downloadZip() {
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
    delete $("material-form").dataset.job;
    renderView();
    $("topic").focus();
  }

  // ---------- 시작 ----------
  function bindEvents() {
    $("job-form").addEventListener("submit", submitForm);
    $("topic").addEventListener("input", () => {
      updateTopicCount();
      $("topic").removeAttribute("aria-invalid");
    });
    for (const id of ["topic", "url", "notes", "type-options"]) $(id).addEventListener("change", saveDraftInput);
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
    $("material-form").addEventListener("submit", submitMaterial);
    for (const radio of $("job-form").elements.mode) radio.addEventListener("change", applyMode);
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

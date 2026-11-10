// Layout Spec(JSON)을 1080x1350 캔버스에 그립니다. 미리보기와 PNG가 같은 그림을 씁니다.
// 규격 설명: docs/layout-spec.md
"use strict";

const SemogwiRenderer = (() => {
  const WIDTH = 1080;
  const HEIGHT = 1350;
  const DEFAULT_FONTS = { display: "Jua", body: "Gowun Dodum" };
  const LINE_HEIGHT = 1.35;
  const MIN_FONT_RATIO = 0.6; // 글자가 넘치면 이 비율까지 줄이고, 그래도 넘치면 경고합니다 (글자를 자르지 않음)

  function fontStack(theme, token) {
    const family = (theme.fonts && theme.fonts[token]) || DEFAULT_FONTS[token];
    return `"${family}", "Malgun Gothic", sans-serif`;
  }

  function fontsReady(theme) {
    if (!document.fonts) return Promise.resolve();
    const fonts = (theme && theme.fonts) || DEFAULT_FONTS;
    return Promise.allSettled([document.fonts.load(`40px "${fonts.display}"`, "가A"), document.fonts.load(`40px "${fonts.body}"`, "가A")]);
  }

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("이미지를 불러오지 못했어요"));
      img.src = src;
    });
  }

  function roundRectPath(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, Math.min(r, w / 2, h / 2));
  }

  function wrapLines(ctx, text, maxWidth) {
    const lines = [];
    for (const paragraph of text.split("\n")) {
      let line = "";
      for (const word of paragraph.split(" ")) {
        const candidate = line ? `${line} ${word}` : word;
        if (ctx.measureText(candidate).width <= maxWidth) {
          line = candidate;
          continue;
        }
        if (line) lines.push(line);
        line = "";
        // 한 단어가 줄보다 길 때만 글자 단위로 나눕니다
        for (const ch of word) {
          if (ctx.measureText(line + ch).width > maxWidth && line) {
            lines.push(line);
            line = ch;
          } else {
            line += ch;
          }
        }
      }
      lines.push(line);
    }
    return lines;
  }

  function drawText(ctx, el, theme) {
    const { x, y, w, h } = el.box;
    const minSize = Math.ceil(el.size * MIN_FONT_RATIO);
    let size = el.size;
    let lines;
    for (;;) {
      ctx.font = `${size}px ${fontStack(theme, el.font)}`;
      lines = wrapLines(ctx, el.text, w);
      const fits = lines.length <= el.maxLines && lines.length * size * LINE_HEIGHT <= h;
      if (fits || size <= minSize) break;
      size -= 2;
    }
    const lineHeight = size * LINE_HEIGHT;
    const overflow = lines.length > el.maxLines || lines.length * lineHeight > h || lines.some((l) => ctx.measureText(l).width > w);

    ctx.fillStyle = theme[el.color];
    ctx.textBaseline = "middle";
    ctx.textAlign = el.align;
    const anchor = el.align === "center" ? x + w / 2 : el.align === "right" ? x + w : x;
    const blockHeight = lines.length * lineHeight;
    const top = el.valign === "bottom" ? y + h - blockHeight : el.valign === "middle" ? y + (h - blockHeight) / 2 : y;
    lines.forEach((line, i) => ctx.fillText(line, anchor, top + lineHeight * (i + 0.5)));
    return overflow;
  }

  function starPath(ctx, r) {
    ctx.beginPath();
    for (let i = 0; i < 10; i++) {
      const radius = i % 2 ? r * 0.48 : r;
      const angle = -Math.PI / 2 + (i * Math.PI) / 5;
      ctx.lineTo(Math.cos(angle) * radius, Math.sin(angle) * radius);
    }
    ctx.closePath();
  }

  function heartPath(ctx, r) {
    ctx.beginPath();
    ctx.moveTo(0, r * 0.85);
    ctx.bezierCurveTo(-r * 1.25, -r * 0.1, -r * 0.65, -r * 1.05, 0, -r * 0.35);
    ctx.bezierCurveTo(r * 0.65, -r * 1.05, r * 1.25, -r * 0.1, 0, r * 0.85);
    ctx.closePath();
  }

  function trianglePath(ctx, r) {
    // 세모귀의 둥근 세모
    const [a, b, c] = [[0, -r], [r, r * 0.8], [-r, r * 0.8]];
    const corner = r * 0.24;
    ctx.beginPath();
    ctx.moveTo((a[0] + c[0]) / 2, (a[1] + c[1]) / 2);
    ctx.arcTo(a[0], a[1], b[0], b[1], corner);
    ctx.arcTo(b[0], b[1], c[0], c[1], corner);
    ctx.arcTo(c[0], c[1], a[0], a[1], corner);
    ctx.closePath();
  }

  function drawShape(ctx, el, theme) {
    const { x, y, w, h } = el.box;
    const color = theme[el.color];
    ctx.save();
    ctx.globalAlpha = el.opacity;
    ctx.fillStyle = color;
    ctx.strokeStyle = color;

    if (el.kind === "panel") {
      roundRectPath(ctx, x, y, w, h, 56);
      ctx.fill();
      ctx.restore();
      return;
    }
    const r = Math.min(w, h) / 2;
    ctx.translate(x + w / 2, y + h / 2);
    ctx.rotate((el.rotate * Math.PI) / 180);
    if (el.kind === "circle") {
      ctx.beginPath();
      ctx.arc(0, 0, r, 0, Math.PI * 2);
      ctx.fill();
    } else if (el.kind === "ring") {
      ctx.beginPath();
      ctx.lineWidth = r * 0.26;
      ctx.arc(0, 0, r * 0.86, 0, Math.PI * 2);
      ctx.stroke();
    } else if (el.kind === "star") {
      starPath(ctx, r);
      ctx.fill();
    } else if (el.kind === "heart") {
      heartPath(ctx, r);
      ctx.fill();
    } else if (el.kind === "triangle") {
      trianglePath(ctx, r);
      ctx.fill();
    } else if (el.kind === "blob") {
      ctx.scale(w / (2 * r), h / (2 * r));
      ctx.beginPath();
      ctx.moveTo(r * 0.1, -r);
      ctx.bezierCurveTo(r * 0.8, -r * 1.05, r * 1.05, -r * 0.3, r * 0.9, r * 0.25);
      ctx.bezierCurveTo(r * 0.78, r * 0.85, r * 0.15, r * 1.05, -r * 0.4, r * 0.88);
      ctx.bezierCurveTo(-r * 1.05, r * 0.68, -r * 1.05, -r * 0.2, -r * 0.72, -r * 0.62);
      ctx.bezierCurveTo(-r * 0.5, -r * 0.9, -r * 0.2, -r * 0.98, r * 0.1, -r);
      ctx.closePath();
      ctx.fill();
    } else if (el.kind === "sparkle") {
      ctx.beginPath();
      for (let i = 0; i < 8; i++) {
        const radius = i % 2 ? r * 0.22 : r;
        const angle = -Math.PI / 2 + (i * Math.PI) / 4;
        ctx.lineTo(Math.cos(angle) * radius, Math.sin(angle) * radius);
      }
      ctx.closePath();
      ctx.fill();
    } else if (el.kind === "pill") {
      roundRectPath(ctx, -w / 2, -h / 2, w, h, Math.min(w, h) / 2);
      ctx.fill();
    } else if (el.kind === "dots") {
      const gap = Math.max(22, Math.min(w, h) / 6);
      for (let dx = -w / 2 + gap / 2; dx < w / 2; dx += gap) {
        for (let dy = -h / 2 + gap / 2; dy < h / 2; dy += gap) {
          ctx.beginPath();
          ctx.arc(dx, dy, gap * 0.16, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    } else if (el.kind === "wave") {
      ctx.beginPath();
      ctx.lineCap = "round";
      ctx.lineWidth = Math.max(6, h * 0.16);
      const steps = 4;
      const part = w / steps;
      ctx.moveTo(-w / 2, 0);
      for (let i = 0; i < steps; i++) {
        const sign = i % 2 ? 1 : -1;
        ctx.quadraticCurveTo(-w / 2 + part * (i + 0.5), sign * h * 0.4, -w / 2 + part * (i + 1), 0);
      }
      ctx.stroke();
    }
    ctx.restore();
  }

  async function drawImageElement(ctx, el, theme, assetUrl) {
    const { x, y, w, h } = el.box;
    if (!el.assetId) {
      ctx.save();
      roundRectPath(ctx, x, y, w, h, el.radius);
      ctx.globalAlpha = 0.55;
      ctx.fillStyle = theme.panel;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.setLineDash([18, 14]);
      ctx.lineWidth = 5;
      ctx.strokeStyle = theme.inkSoft;
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = theme.inkSoft;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.font = `44px ${fontStack(theme, "display")}`;
      ctx.fillText("이미지 자리", x + w / 2, y + h / 2 - 28);
      ctx.font = `30px ${fontStack(theme, "body")}`;
      ctx.fillText("허가된 이미지가 없어요", x + w / 2, y + h / 2 + 28);
      ctx.restore();
      return;
    }
    const img = await loadImage(assetUrl(el.assetId, el.variant));
    // contain: 원본 비율 그대로, 잘라 내지 않음
    const scale = Math.min(w / img.naturalWidth, h / img.naturalHeight);
    const dw = img.naturalWidth * scale;
    const dh = img.naturalHeight * scale;
    ctx.drawImage(img, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
  }

  function drawDemoMark(ctx, theme) {
    const label = "DEMO SAMPLE · 게시용 아님";
    ctx.save();
    ctx.font = `26px ${fontStack(theme, "body")}`;
    const textWidth = ctx.measureText(label).width;
    const w = textWidth + 48;
    const x = (WIDTH - w) / 2;
    const y = HEIGHT - 66;
    roundRectPath(ctx, x, y, w, 46, 23);
    ctx.fillStyle = theme.ink;
    ctx.fill();
    ctx.fillStyle = "#FFFFFF";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, WIDTH / 2, y + 24);
    ctx.restore();
  }

  // 그린 결과를 돌려줍니다. overflow가 true면 글자가 칸을 넘친 것입니다.
  async function render(canvas, spec, theme, options) {
    canvas.width = WIDTH;
    canvas.height = HEIGHT;
    const ctx = canvas.getContext("2d");
    const bg = spec.background || { start: "bgFrom", end: "bgTo", angle: null };
    let gradient;
    if (bg.angle === null || bg.angle === undefined) {
      gradient = ctx.createLinearGradient(0, 0, WIDTH, HEIGHT);
    } else {
      const radians = (bg.angle * Math.PI) / 180;
      const dx = Math.sin(radians) * Math.hypot(WIDTH, HEIGHT) * 0.5;
      const dy = -Math.cos(radians) * Math.hypot(WIDTH, HEIGHT) * 0.5;
      gradient = ctx.createLinearGradient(WIDTH / 2 - dx, HEIGHT / 2 - dy, WIDTH / 2 + dx, HEIGHT / 2 + dy);
    }
    gradient.addColorStop(0, theme[bg.start]);
    gradient.addColorStop(1, theme[bg.end]);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, WIDTH, HEIGHT);

    let overflow = false;
    for (const el of spec.elements) {
      if (el.type === "shape") drawShape(ctx, el, theme);
      else if (el.type === "image") await drawImageElement(ctx, el, theme, options.assetUrl);
      else if (el.type === "text") overflow = drawText(ctx, el, theme) || overflow;
    }
    if (options.demo) drawDemoMark(ctx, theme);
    return { overflow };
  }

  // ---------- 고정 템플릿 (작업 형식 3). 규격: docs/template-spec.md ----------
  // 세모귀 로고: 팀 템플릿(semogwi-cardnews-templates)의 인라인 SVG를 그대로 꺼낸 벡터 파일입니다.
  const LOGO_SRC = "/brand/semogwi-logo.svg";
  const imageCache = new Map();

  function cachedImage(src) {
    if (!imageCache.has(src)) imageCache.set(src, loadImage(src).catch((error) => { imageCache.delete(src); throw error; }));
    return imageCache.get(src);
  }

  const pad2 = (n) => String(n).padStart(2, "0");
  const isEmpty = (value) => value === undefined || value === null || value === "" || value === false || (Array.isArray(value) && value.length === 0)
    || (typeof value === "object" && !Array.isArray(value) && Object.values(value).every(isEmpty));
  const tplColor = (tpl, value) => (tpl.palette && tpl.palette[value]) || value;
  const tplFont = (tpl, token, size) => `${size}px "${tpl.fonts[token]}", "Malgun Gothic", sans-serif`;
  // "traits.0.keyword"처럼 배열 항목의 값을 가리킵니다
  const getPath = (fields, path) => path.split(".").reduce((value, key) => (value === undefined || value === null ? undefined : value[key]), fields);
  const baseKey = (path) => path.split(".")[0];

  function fillTokens(spec, text) {
    return text.replace(/\{([\w.]+)\}/g, (_, key) => {
      if (key === "page") return pad2(spec.page);
      if (key === "total") return pad2(spec.total);
      if (key === "no") return spec.no || "";
      if (key === "source") return spec.source || "";
      if (key === "source_text") return (spec.source || "").replace(/^출처:\s*/, "");
      const value = getPath(spec.fields, key);
      return typeof value === "string" ? value : "";
    }).replace(/\s{2,}/g, " ").trim(); // 빈 값이 빠진 자리의 공백을 정리합니다
  }

  function setFont(ctx, tpl, token, size, spacing = 0) {
    ctx.font = tplFont(tpl, token, size);
    if ("letterSpacing" in ctx) ctx.letterSpacing = `${spacing}px`;
  }

  // 칸에 맞을 때까지 글자를 줄입니다. 최소 크기에서도 넘치면 overflow입니다 (글자를 자르지 않음).
  function fitLines(ctx, tpl, text, opt, w, h) {
    const maxLines = opt.maxLines || 1;
    const minSize = opt.minSize || Math.ceil(opt.size * MIN_FONT_RATIO);
    const lineHeight = opt.lineHeight || LINE_HEIGHT;
    let size = opt.size;
    let lines;
    for (;;) {
      setFont(ctx, tpl, opt.font, size, opt.letterSpacing || 0);
      lines = wrapLines(ctx, text, w);
      const fits = lines.length <= maxLines && lines.length * size * lineHeight <= h + size * 0.4 && lines.every((l) => ctx.measureText(l).width <= w);
      if (fits) return { lines, size, overflow: false };
      if (size <= minSize) return { lines, size, overflow: true };
      size = Math.max(minSize, size - 2);
    }
  }

  function drawTextBox(ctx, tpl, text, el) {
    const { x, y, w, h } = el.box;
    const fit = fitLines(ctx, tpl, text, el, w, h);
    const lineHeight = fit.size * (el.lineHeight || LINE_HEIGHT);
    ctx.fillStyle = tplColor(tpl, el.color || "ink");
    ctx.textBaseline = "middle";
    ctx.textAlign = el.align || "left";
    const anchor = el.align === "center" ? x + w / 2 : el.align === "right" ? x + w : x;
    const block = fit.lines.length * lineHeight;
    const top = el.valign === "bottom" ? y + h - block : el.valign === "top" ? y : y + (h - block) / 2;
    fit.lines.forEach((line, i) => ctx.fillText(line, anchor, top + lineHeight * (i + 0.5)));
    if ("letterSpacing" in ctx) ctx.letterSpacing = "0px";
    return fit.overflow;
  }

  function shapePath(ctx, el) {
    ctx.beginPath();
    if (el.type === "circle" || el.shape === "circle") {
      const cx = el.cx ?? el.box.x + el.box.w / 2;
      const cy = el.cy ?? el.box.y + el.box.h / 2;
      ctx.arc(cx, cy, el.r ?? Math.min(el.box.w, el.box.h) / 2, 0, Math.PI * 2);
    } else ctx.roundRect(el.box.x, el.box.y, el.box.w, el.box.h, el.radius || 0);
  }

  function paint(ctx, tpl, el) {
    ctx.save();
    shapePath(ctx, el);
    if (el.fill) {
      ctx.fillStyle = tplColor(tpl, el.fill);
      ctx.fill();
    }
    if (el.stroke) {
      ctx.lineWidth = el.lineWidth || 3;
      ctx.strokeStyle = tplColor(tpl, el.stroke);
      if (el.dash) ctx.setLineDash(el.dash);
      ctx.stroke();
    }
    ctx.restore();
  }

  async function drawLogo(ctx, x, y, w, h, alpha = 1) {
    ctx.save();
    ctx.globalAlpha = alpha;
    try {
      ctx.drawImage(await cachedImage(LOGO_SRC), x, y, w, h);
    } catch {
      ctx.translate(x + w / 2, y + h / 2);
      trianglePath(ctx, Math.min(w, h) / 2);
      ctx.fillStyle = "#FFB8CB";
      ctx.fill();
    }
    ctx.restore();
  }

  async function drawHeader(ctx, tpl, el) {
    await drawLogo(ctx, 72, 72, 84, 74);
    setFont(ctx, tpl, "display", 38);
    ctx.fillStyle = tplColor(tpl, "ink");
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    ctx.fillText("세모귀", 170, 108);
    setFont(ctx, tpl, "display", 27);
    const width = ctx.measureText(el.tag).width + 54;
    ctx.beginPath();
    ctx.roundRect(1008 - width, 82, width, 54, 27);
    ctx.fillStyle = tplColor(tpl, el.tagFill || "accent");
    ctx.fill();
    ctx.fillStyle = tplColor(tpl, "ink");
    ctx.textAlign = "center";
    ctx.fillText(el.tag, 1008 - width / 2, 110);
  }

  function drawFooter(ctx, tpl, el, spec) {
    // parts는 빈 값을 빼고 " · "로 잇습니다 (예: 안내 문구 · 출처)
    const left = el.parts ? el.parts.map((p) => fillTokens(spec, p).trim()).filter(Boolean).join(" · ") : fillTokens(spec, el.left || "");
    let overflow = false;
    const y = 1239 + (el.dy || 0);
    if (left) overflow = drawTextBox(ctx, tpl, left, { box: { x: 73, y, w: 780, h: 42 }, font: "body", size: 26, minSize: 18, color: "inkSoft", align: "left", valign: "middle", maxLines: 1 });
    drawTextBox(ctx, tpl, `${pad2(spec.page)} / ${pad2(spec.total)}`, { box: { x: 850, y, w: 157, h: 42 }, font: "body", size: 26, color: "inkSoft", align: "right", valign: "middle", maxLines: 1 });
    return overflow;
  }

  async function drawSlot(ctx, tpl, el, spec, options) {
    const { assetUrl, assetInfo, showEmpty } = options;
    if (el.rotate) {
      const { x, y, w, h } = el.box;
      ctx.save();
      ctx.translate(x + w / 2, y + h / 2);
      ctx.rotate((el.rotate * Math.PI) / 180);
      ctx.translate(-(x + w / 2), -(y + h / 2));
      const missing = await drawSlot(ctx, tpl, { ...el, rotate: 0 }, spec, options);
      ctx.restore();
      return missing;
    }
    const { x, y, w, h } = el.box;
    const image = spec.images && spec.images[el.slot];
    if (el.fill) paint(ctx, tpl, { ...el, type: "image", fill: el.fill, stroke: null });
    if (!image) {
      // 이미지가 없으면 템플릿의 빈 면만 둡니다. 세모귀 마스코트나 "이미지 자리" 글자를 PNG에 그리지 않습니다.
      if (el.emptyFill) paint(ctx, tpl, { ...el, type: "image", fill: el.emptyFill, stroke: null });
      // 구성안 편집 화면에서만 빈 자리를 점선으로 알려 줍니다 (내보내는 카드에는 그리지 않음)
      if (showEmpty) paint(ctx, tpl, { ...el, type: "image", fill: null, stroke: "rgba(60, 40, 50, 0.45)", dash: [14, 10], lineWidth: 4 });
      return true;
    }
    const img = await loadImage(assetUrl(image.assetId, image.variant));
    const inset = el.inset || 0;
    const bw = w - inset * 2;
    const bh = h - inset * 2;
    const src = subjectRect(img, image, assetInfo);
    // contain: 자르거나 늘리지 않음. 누끼는 투명 여백을 빼고 피사체 기준으로 맞춥니다
    const fill = image.variant === "cutout" && src.trimmed ? CUTOUT_FILL : 1;
    const user = clampNum(image.scale, 0.3, 3, 1);
    const scale = Math.min(bw / src.w, bh / src.h) * fill * user;
    const dw = src.w * scale;
    const dh = src.h * scale;
    const cx = x + inset + bw / 2 + clampNum(image.dx, -1, 1, 0) * bw;
    const cy = y + inset + bh / 2 + clampNum(image.dy, -1, 1, 0) * bh;
    ctx.save();
    shapePath(ctx, { ...el, type: "image" });
    ctx.clip();
    ctx.drawImage(img, src.x, src.y, src.w, src.h, cx - dw / 2, cy - dh / 2, dw, dh);
    ctx.restore();
    return false;
  }

  const CUTOUT_FILL = 0.9; // 누끼 피사체가 이미지 자리의 90%를 차지하도록 (테두리에 닿지 않게)
  const SUBJECT_PAD = 0.03; // 피사체 범위 바깥으로 남기는 여백 (가장자리의 부드러운 알파가 잘리지 않게)
  const clampNum = (value, lo, hi, fallback) => (Number.isFinite(value) ? Math.min(hi, Math.max(lo, value)) : fallback);

  // 그릴 원본 범위. 누끼는 alpha_check가 잰 피사체 범위(bbox)만 씁니다. 원본은 이미지 전체입니다.
  function subjectRect(img, image, assetInfo) {
    const full = { x: 0, y: 0, w: img.naturalWidth, h: img.naturalHeight, trimmed: false };
    const info = image.variant === "cutout" && assetInfo ? assetInfo(image.assetId) : null;
    if (!info || !Array.isArray(info.bbox) || !info.width || !info.height) return full;
    const rx = img.naturalWidth / info.width;
    const ry = img.naturalHeight / info.height;
    const [x0, y0, x1, y1] = info.bbox;
    if (!(x1 > x0 && y1 > y0)) return full;
    const pad = Math.max(x1 - x0, y1 - y0) * SUBJECT_PAD;
    const left = Math.max(0, (x0 - pad) * rx);
    const top = Math.max(0, (y0 - pad) * ry);
    const right = Math.min(img.naturalWidth, (x1 + pad) * rx);
    const bottom = Math.min(img.naturalHeight, (y1 + pad) * ry);
    return { x: left, y: top, w: right - left, h: bottom - top, trimmed: true };
  }

  // 항목 이름과 내용 줄. items(고정 이름 + 필드) 또는 field(pairs)를 받고, 빈 줄은 빼서 위로 당깁니다.
  function drawRows(ctx, tpl, el, spec) {
    const rows = el.items
      ? el.items.map((item) => ({ label: item.label, value: getPath(spec.fields, item.field), key: baseKey(item.field) })).filter((r) => !isEmpty(r.value))
      : (getPath(spec.fields, el.field) || []).map((item) => ({ ...item, key: baseKey(el.field) }));
    const overflow = [];
    rows.slice(0, el.maxRows || 4).forEach((row, i) => {
      const top = el.y + el.rowHeight * i;
      if (drawTextBox(ctx, tpl, row.label, { ...el.label, box: { x: el.x, y: top + (el.labelDy || 0), w: el.labelWidth, h: el.rowHeight }, align: "left", valign: "middle", maxLines: 1, minSize: el.label.minSize || 20 })) overflow.push(row.key);
      if (drawTextBox(ctx, tpl, row.value, { ...el.value, box: { x: el.valueX, y: top + (el.valueDy || 0), w: el.valueWidth, h: el.rowHeight }, align: "left", valign: "middle", maxLines: 1 })) overflow.push(row.key);
    });
    return overflow;
  }

  function drawChips(ctx, tpl, el, spec) {
    const items = (getPath(spec.fields, el.field) || []).slice(0, el.maxItems || 3).map((t) => `${el.prefix || ""}${t}`);
    if (!items.length) return false;
    let size = el.size;
    const widths = () => items.map((t) => ctx.measureText(t).width + el.padX * 2);
    const total = () => widths().reduce((a, b) => a + b, 0) + el.gap * (items.length - 1);
    setFont(ctx, tpl, el.font, size);
    while (total() > el.maxWidth && size > el.minSize) {
      size -= 1;
      setFont(ctx, tpl, el.font, size);
    }
    let cursor = el.x;
    for (const [i, width] of widths().entries()) {
      ctx.beginPath();
      ctx.roundRect(cursor, el.y, width, el.h, el.h / 2);
      ctx.fillStyle = tplColor(tpl, el.fill);
      ctx.fill();
      ctx.fillStyle = tplColor(tpl, el.color);
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(items[i], cursor + width / 2, el.y + el.h / 2 + 1);
      cursor += width + el.gap;
    }
    return total() > el.maxWidth;
  }

  // 글자 길이에 맞춰 너비가 정해지는 알약·배지. align이 center면 x가 가운데, left면 왼쪽 끝입니다.
  function drawPill(ctx, tpl, el, text) {
    let size = el.size;
    const minSize = el.minSize || Math.ceil(el.size * MIN_FONT_RATIO);
    setFont(ctx, tpl, el.font, size);
    const iconSpace = el.icon ? el.h * 0.62 : 0;
    const widthAt = () => Math.max(el.minWidth || 0, ctx.measureText(text).width + el.padX * 2 + iconSpace);
    while (el.maxWidth && widthAt() > el.maxWidth && size > minSize) {
      size -= 1;
      setFont(ctx, tpl, el.font, size);
    }
    const width = widthAt();
    const left = el.align === "center" ? el.x - width / 2 : el.align === "right" ? el.x - width : el.x;
    paint(ctx, tpl, { type: "rect", box: { x: left, y: el.y, w: width, h: el.h }, radius: el.radius ?? el.h / 2, fill: el.fill, stroke: el.stroke, lineWidth: el.lineWidth });
    setFont(ctx, tpl, el.font, size);
    ctx.fillStyle = tplColor(tpl, el.color || "ink");
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, left + (width + iconSpace) / 2, el.y + el.h / 2 + (el.textDy || 1));
    if (el.icon === "pin") drawPin(ctx, tpl, left + el.padX + iconSpace * 0.32, el.y + el.h / 2, el.h * 0.26, el.color || "ink");
    return Boolean(el.maxWidth) && width > el.maxWidth;
  }

  function drawPin(ctx, tpl, cx, cy, r, color) {
    ctx.save();
    ctx.strokeStyle = tplColor(tpl, color);
    ctx.lineWidth = Math.max(2.5, r * 0.22);
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(cx, cy + r * 1.25);
    ctx.bezierCurveTo(cx - r * 1.15, cy + r * 0.1, cx - r * 1.05, cy - r * 1.05, cx, cy - r * 1.05);
    ctx.bezierCurveTo(cx + r * 1.05, cy - r * 1.05, cx + r * 1.15, cy + r * 0.1, cx, cy + r * 1.25);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cy - r * 0.25, r * 0.36, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  function drawBullets(ctx, tpl, el, spec) {
    const items = (getPath(spec.fields, el.field) || []).slice(0, el.maxItems || 3);
    let overflow = false;
    items.forEach((item, i) => {
      const cy = el.y + el.pitch * i;
      setFont(ctx, tpl, el.font, el.size);
      ctx.fillStyle = tplColor(tpl, el.color || "ink");
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(el.bullet || "·", el.x, cy);
      overflow = drawTextBox(ctx, tpl, item, { ...el, box: { x: el.textX, y: cy - el.pitch / 2, w: el.width, h: el.pitch }, align: "left", valign: "middle", maxLines: 1 }) || overflow;
    });
    return overflow;
  }

  // 별 배지 (NEW, PICK 등). points개의 뾰족한 꼭짓점, 글자는 가운데에 둡니다
  function drawStar(ctx, tpl, el) {
    const points = el.points || 7;
    ctx.save();
    ctx.translate(el.cx, el.cy);
    ctx.rotate(((el.rotate || 0) * Math.PI) / 180);
    ctx.beginPath();
    for (let i = 0; i < points * 2; i++) {
      const radius = i % 2 ? el.r * (el.inner || 0.6) : el.r;
      const angle = -Math.PI / 2 + (i * Math.PI) / points;
      ctx.lineTo(Math.cos(angle) * radius, Math.sin(angle) * radius);
    }
    ctx.closePath();
    ctx.fillStyle = tplColor(tpl, el.fill);
    ctx.fill();
    ctx.lineJoin = "miter";
    ctx.lineWidth = el.lineWidth || 3;
    ctx.strokeStyle = tplColor(tpl, el.stroke || "ink");
    ctx.stroke();
    ctx.restore();
    if (el.text) {
      setFont(ctx, tpl, el.font || "display", el.size);
      ctx.fillStyle = tplColor(tpl, el.color || "ink");
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(el.text, el.cx + (el.textDx || 0), el.cy + (el.textDy || 0));
    }
  }

  function drawCheck(ctx, tpl, el) {
    paint(ctx, tpl, { type: "circle", cx: el.cx, cy: el.cy, r: el.r, fill: el.fill || "accent", stroke: el.stroke || "ink", lineWidth: el.lineWidth || 3 });
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(el.cx - el.r * 0.42, el.cy + el.r * 0.02);
    ctx.lineTo(el.cx - el.r * 0.1, el.cy + el.r * 0.32);
    ctx.lineTo(el.cx + el.r * 0.44, el.cy - el.r * 0.3);
    ctx.lineWidth = el.markWidth || el.r * 0.2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = tplColor(tpl, el.stroke || "ink");
    ctx.stroke();
    ctx.restore();
  }

  // 결과: overflow(글자가 칸을 넘침), overflowFields(넘친 필드), missingImages(비어 있는 이미지 자리)
  async function renderTemplate(canvas, spec, tpl, options) {
    canvas.width = WIDTH;
    canvas.height = HEIGHT;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = tplColor(tpl, "bg");
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    const overflowFields = [];
    const missingImages = [];
    const mark = (overflow, name) => {
      for (const key of Array.isArray(overflow) ? overflow : overflow ? [name] : []) if (!overflowFields.includes(key)) overflowFields.push(key);
    };
    for (const el of tpl.elements) {
      if (el.if && isEmpty(getPath(spec.fields, el.if))) continue;
      if (el.type === "header") await drawHeader(ctx, tpl, el);
      else if (el.type === "footer") mark(drawFooter(ctx, tpl, el, spec), "source");
      else if (el.type === "rect" || el.type === "circle") paint(ctx, tpl, el);
      else if (el.type === "line") {
        ctx.beginPath();
        ctx.moveTo(el.x1, el.y1);
        ctx.lineTo(el.x2, el.y2);
        ctx.lineWidth = el.lineWidth || 3;
        ctx.strokeStyle = tplColor(tpl, el.color || "ink");
        ctx.setLineDash(el.dash || []);
        ctx.stroke();
        ctx.setLineDash([]);
      } else if (el.type === "image") {
        if (await drawSlot(ctx, tpl, el, spec, options)) missingImages.push(el.slot);
      } else if (el.type === "asset") await drawLogo(ctx, el.box.x, el.box.y, el.box.w, el.box.h);
      else if (el.type === "check") drawCheck(ctx, tpl, el);
      else if (el.type === "star") drawStar(ctx, tpl, el);
      else if (el.type === "rows") mark(drawRows(ctx, tpl, el, spec), el.field);
      else if (el.type === "chips") mark(drawChips(ctx, tpl, el, spec), baseKey(el.field));
      else if (el.type === "bullets") mark(drawBullets(ctx, tpl, el, spec), baseKey(el.field));
      else if (el.type === "pill" || el.type === "text") {
        const value = el.field ? getPath(spec.fields, el.field) : fillTokens(spec, el.text);
        if (isEmpty(value)) continue;
        const name = el.field ? baseKey(el.field) : "text";
        mark(el.type === "pill" ? drawPill(ctx, tpl, el, value) : drawTextBox(ctx, tpl, value, el), name);
      }
    }
    if (options.demo) drawDemoMark(ctx, { ...tpl.palette, fonts: tpl.fonts });
    return { overflow: overflowFields.length > 0, overflowFields, missingImages };
  }

  return { render, renderTemplate, fontsReady, WIDTH, HEIGHT };
})();

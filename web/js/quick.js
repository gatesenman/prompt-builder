/* PromptBuilder 2.12.4 — quick-pick popup (角色 › indented prompts).
   Driven by Python: __qpPrepare (pre-render while hidden/cloaked) · __qpReset (after hide) · __qpFocus (on show).
   Everything visible is rendered BEFORE the window is shown; __qpFocus only moves focus. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const I = (n, z = 14) => (window.PBIcons ? window.PBIcons.svg(n, z) : "");
  const S = { items: [], shown: [], groups: [], collapsed: {}, sel: 0, preview: true, mode: "list", cur: null, busy: false, showOptional: false, theme: "system", exe: "" };
  const api = () => (window.pywebview && window.pywebview.api) || null;
  const mql = matchMedia("(prefers-color-scheme: light)");
  function applyTheme() {
    const t = S.theme === "system" ? (mql.matches ? "light" : "dark") : S.theme;
    document.documentElement.dataset.theme = t === "light" ? "light" : "dark";
  }
  mql.addEventListener("change", applyTheme);

  // ---------------------------------------------------------------- search
  function matchOne(n, p, q) {
    if (n.startsWith(q)) return 4;
    if (n.includes(q)) return 3;
    // subsequence on name (e.g. "wr" → "weekly report", "周生" → "周报生成")
    let i = 0; for (const ch of n) { if (ch === q[i]) i++; if (i === q.length) return 2; }
    return p.includes(q) ? 1 : 0;
  }
  const terms = (q) => q.split(/\s+/).filter(Boolean);
  function match(item, q) {
    if (!q) return 1;
    const n = item.name.toLowerCase(), p = (item.preview || "").toLowerCase();
    const kw = (item.keywords || []).join(" ").toLowerCase();
    const tg = (item.tags || []).join(" ").toLowerCase();
    const rc = `${item.role_name || ""} ${item.category_name || ""}`.toLowerCase();
    let total = 0;
    for (const term of terms(q)) {
      let s = matchOne(n, p, term);
      if (!s && kw.includes(term)) s = 3;
      if (!s && tg.includes(term)) s = 2;
      if (!s && rc.includes(term)) s = 2;
      if (!s) return 0; total += s;
    }
    return total;
  }
  function hl(name, q) {
    const ts = terms(q); if (!ts.length) return esc(name);
    const low = name.toLowerCase(), on = new Array(name.length).fill(false);
    for (const t of ts) { let i = low.indexOf(t); while (i >= 0) { for (let k = i; k < i + t.length; k++) on[k] = true; i = low.indexOf(t, i + t.length); } }
    let out = "", m = false;
    for (let i = 0; i < name.length; i++) { if (on[i] !== m) { out += on[i] ? "<mark>" : "</mark>"; m = on[i]; } out += esc(name[i]); }
    return out + (m ? "</mark>" : "");
  }
  function cmpRank(a, b) {
    const ap = a.pinned ? 0 : 1, bp = b.pinned ? 0 : 1; if (ap !== bp) return ap - bp;
    const af = a.favorite ? 0 : 1, bf = b.favorite ? 0 : 1; if (af !== bf) return af - bf;
    const ar = a.recent ? 0 : 1, br = b.recent ? 0 : 1; if (ar !== br) return ar - br;
    const au = -(a.use_count || 0), bu = -(b.use_count || 0); if (au !== bu) return au - bu;
    return String(a.name || "").localeCompare(String(b.name || ""), "zh");
  }
  function buildGroups(items) {
    const byRole = new Map();
    for (const it of items) {
      const rid = it.role_id || "_none";
      if (!byRole.has(rid)) {
        byRole.set(rid, {
          id: rid,
          name: it.role_name || "未分组",
          order: it.role_order != null ? it.role_order : 9999,
          items: [],
        });
      }
      byRole.get(rid).items.push(it);
    }
    const roles = Array.from(byRole.values()).sort((a, b) =>
      a.order - b.order || String(a.name).localeCompare(String(b.name), "zh"));
    for (const r of roles) r.items.sort(cmpRank);
    // drop empty roles (e.g. after search)
    return roles.filter((r) => r.items.length);
  }
  function flattenVisible(groups, allowCollapse) {
    const out = [];
    for (const r of groups) {
      if (allowCollapse && S.collapsed["r:" + r.id]) continue;
      out.push(...r.items);
    }
    return out;
  }
  function filter() {
    const q = $("#q").value.trim().toLowerCase();
    const matched = S.items.filter((it) => match(it, q) > 0);
    S.groups = buildGroups(matched);
    const allowCollapse = !q;
    S.shown = flattenVisible(S.groups, allowCollapse);
    if (S.sel >= S.shown.length) S.sel = Math.max(0, S.shown.length - 1);
    renderList(q);
  }
  function renderList(q = $("#q").value.trim().toLowerCase()) {
    const el = $("#list");
    if (!S.items.length) {
      el.innerHTML = `<div class="qp-empty"><div class="e-ico">${I("file", 20)}</div><b>还没有提示词</b><span>在主窗口中新建后，就能在这里一键插入。</span>
        <button class="btn primary sm" data-act="main">${I("window", 14)}打开主窗口</button></div>`;
      foot(); return;
    }
    if (!S.groups.length) {
      el.innerHTML = `<div class="qp-empty"><div class="e-ico">${I("search", 20)}</div><b>没有找到「${esc(q)}」</b><span>换个关键词试试，名称、关键词、标签、正文和角色都会被搜索。</span></div>`;
      foot(); return;
    }
    const allowCollapse = !q;
    let html = "";
    let i = 0;
    for (const r of S.groups) {
      const rk = "r:" + r.id;
      const rCol = allowCollapse && !!S.collapsed[rk];
      const rCount = r.items.length;
      html += `<div class="qp-role${rCol ? " is-collapsed" : ""}" data-collapse="${esc(rk)}" role="presentation" title="点击折叠/展开">
        <span class="qp-twist" aria-hidden="true">${rCol ? "▸" : "▾"}</span>
        <span class="qp-h-name">${esc(r.name)}</span>
        <span class="qp-count">${rCount}</span>
      </div>`;
      if (rCol) continue;
      for (const it of r.items) {
        const badges = it.pinned ? `<span class="tag pin">置顶</span>`
          : it.favorite ? `<span class="tag fav">收藏</span>`
          : it.recent ? `<span class="tag recent">最近</span>` : "";
        const req = it.required_count ? `<span class="tag req">${it.required_count} 必填</span>`
          : it.var_count ? `<span class="tag opt">有默认值</span>` : "";
        html += `<div class="qp-item${i === S.sel ? " sel" : ""}" role="option" id="qo-${i}" aria-selected="${i === S.sel}" data-i="${i}">
      <div class="qp-main"><div class="qp-name">${hl(it.name, q)}</div>${q && (it.keywords||[]).length ? `<div class="qp-kws">${(it.keywords||[]).slice(0,4).map((k)=>`<span class="qp-kw">${esc(k)}</span>`).join("")}</div>` : ""}${S.preview && it.preview ? `<div class="qp-prev">${esc(it.preview)}</div>` : ""}</div>
      <div class="qp-side">${badges}${req}<span class="qp-enter">${I("cornerDownLeft", 14)}</span></div></div>`;
        i++;
      }
    }
    el.innerHTML = html;
    $("#q").setAttribute("aria-activedescendant", S.shown.length ? ("qo-" + S.sel) : "");
    foot();
  }
  function moveSel(d, clamp) {
    if (!S.shown.length) return;
    S.sel = clamp ? Math.max(0, Math.min(S.shown.length - 1, S.sel + d)) : (S.sel + d + S.shown.length) % S.shown.length;
    $$(".qp-item").forEach((n, i) => { n.classList.toggle("sel", i === S.sel); n.setAttribute("aria-selected", i === S.sel); });
    const n = $(".qp-item.sel"); if (n) n.scrollIntoView({ block: "nearest" });
    $("#q").setAttribute("aria-activedescendant", "qo-" + S.sel);
  }
  function foot(msg, kind) {
    const f = $("#foot");
    if (msg) { f.innerHTML = `<span class="${kind === "err" ? "qp-err" : "qp-busy"}">${kind === "err" ? I("alert", 12) : ""}${esc(msg)}</span>`; return; }
    const excl = `<button class="qp-link" data-act="exclude" title="以后在${esc(S.exe || "当前程序")}中输入 // 不再弹出（可在设置中恢复）">${I("ban", 12)}<span>在此程序中停用</span></button>`;
    f.innerHTML = S.mode === "list"
      ? `<span><kbd>↑</kbd><kbd>↓</kbd> 选择</span><span><kbd>Enter</kbd> 插入</span><span><kbd>Shift</kbd>+<kbd>Enter</kbd> 填写后插入</span><span class="grow"></span>${excl}`
      : `<span><kbd>Enter</kbd> 下一项</span><span><kbd>Esc</kbd> 返回列表</span><span class="grow"></span>${excl}`;
  }

  // ---------------------------------------------------------------- choose / form
  async function choose(i, forceForm) {
    const it = S.shown[i]; if (!it || S.busy || !api()) return;
    S.busy = true;
    try {
      const p = await api().qp_get(it.id);
      if (!p) { foot("提示词不存在", "err"); return; }
      if (forceForm ? !(p.variables || []).length : !p.needs_form) return await commit(p.id, {});
      openForm(p, forceForm);
    } finally { S.busy = false; }
  }
  function fieldHtml(v, i) {
    const ph = v.default != null ? `默认：${v.default || "（空）"}` : `请输入${v.name}`;
    const last = (S.cur.last_values || {})[v.name];
    const val = last != null && last !== "" ? last : (v.default != null ? v.default : "");
    const id = `qf-${i}`;
    let ctl;
    if (v.control === "select") {
      ctl = `<select class="select" id="${id}" data-i="${i}">${v.default == null ? '<option value="">请选择…</option>' : ""}${v.options.map((o) => `<option${o === val ? " selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
    } else if (v.control === "radio") {
      const cur = val || "";
      ctl = `<div class="choice-group" role="radiogroup" id="${id}" data-i="${i}" data-choice="radio">` +
        (v.options || []).map((o) => `<label class="choice"><input type="radio" name="qr-${i}" value="${esc(o)}" data-i="${i}"${o === cur ? " checked" : ""}>${esc(o)}</label>`).join("") +
        `</div>`;
    } else if (v.control === "multiselect") {
      const sel = new Set(String(val || "").split(/[、,/，]/).map((s) => s.trim()).filter(Boolean));
      ctl = `<div class="choice-group" id="${id}" data-i="${i}" data-choice="multi">` +
        (v.options || []).map((o) => `<label class="choice"><input type="checkbox" value="${esc(o)}" data-i="${i}"${sel.has(o) ? " checked" : ""}>${esc(o)}</label>`).join("") +
        `</div>`;
    } else if (v.control === "multiline") {
      ctl = `<textarea class="textarea" id="${id}" rows="3" data-i="${i}" placeholder="${esc(ph)}" spellcheck="false" title="Enter 换行，Ctrl+Enter 插入">${esc(val)}</textarea>`;
    } else {
      ctl = `<input class="input" id="${id}" data-i="${i}" value="${esc(val)}" placeholder="${esc(ph)}" spellcheck="false" autocomplete="off"${v.control === "number" ? ' inputmode="decimal"' : ""}>`;
    }
    const lastTag = last != null && last !== "" ? '<span class="tag opt" title="已填入上次使用的值">上次</span>' : "";
    const ctlTag = v.control !== "text" && v.control_label ? `<span class="tag ctl">${esc(v.control_label)}</span>` : "";
    return `<div class="field"><label class="field-label" for="${id}">${esc(v.name)}${v.required ? '<span class="tag req">必填</span>' : ""}${ctlTag}${lastTag}</label>${ctl}<div class="qp-msg" data-m="${i}" aria-live="polite"></div></div>`;
  }
  function openForm(p, showOptional) {
    S.mode = "form"; S.cur = p; S.showOptional = !!showOptional || !(p.variables || []).some((v) => v.required);
    $("#list").classList.add("hidden"); $(".qp-search").classList.add("hidden"); $("#form").classList.remove("hidden");
    $("#formTitle").textContent = p.name;
    renderFields(); foot();
  }
  function renderFields() {
    const vars = S.cur.variables;
    const req = vars.map((v, i) => [v, i]).filter(([v]) => v.required);
    const lastv = S.cur.last_values || {};
    if (!S.showOptional && vars.some((v) => !v.required && lastv[v.name])) S.showOptional = true;
    const opt = vars.map((v, i) => [v, i]).filter(([v]) => !v.required);
    let html = req.map(([v, i]) => fieldHtml(v, i)).join("");
    if (opt.length) {
      html += S.showOptional ? opt.map(([v, i]) => fieldHtml(v, i)).join("")
        : `<button class="qp-more" id="more">${I("plus", 12)}修改可选变量（${opt.length} 个，留空用默认值）</button>`;
    }
    $("#fields").innerHTML = html;
    const more = $("#more"); if (more) more.onclick = () => { const keep = collect(); S.showOptional = true; renderFields(); restore(keep); };
    const focusables = [];
    const seen = new Set();
    $$("#fields [data-i]").forEach((el) => {
      const i = +el.dataset.i; if (seen.has(i)) return; seen.add(i);
      const v = S.cur.variables[i];
      if (v.control === "radio" || v.control === "multiselect") {
        const g = $(`.choice-group[data-i="${i}"]`);
        focusables.push({ el: g ? ($("input", g) || g) : el, i, v });
      } else focusables.push({ el, i, v });
    });
    const first = focusables.find((f) => f.v.required && !readFieldValue(f.i).trim()) || focusables[0];
    if (first) {
      first.el.focus();
      if (first.el.select && first.el.tagName === "INPUT" && first.el.type !== "radio" && first.el.type !== "checkbox") first.el.select();
    }
    const aiNeed = $("#aiNeed"); if (aiNeed) aiNeed.value = "";
    setAiMsg("");
  }
  function readFieldValue(i) {
    const v = S.cur.variables[i]; if (!v) return "";
    if (v.control === "radio") {
      const el = $(`#fields input[type=radio][data-i="${i}"]:checked`);
      return el ? el.value : "";
    }
    if (v.control === "multiselect") {
      return $$(`#fields input[type=checkbox][data-i="${i}"]:checked`).map((x) => x.value).join("、");
    }
    const el = $(`#fields select[data-i="${i}"], #fields textarea[data-i="${i}"], #fields input.input[data-i="${i}"]`);
    return el ? el.value : "";
  }
  function collect() {
    const vals = {}, seen = new Set();
    $$("#fields [data-i]").forEach((el) => {
      const i = +el.dataset.i; if (seen.has(i)) return; seen.add(i);
      vals[S.cur.variables[i].name] = readFieldValue(i);
    });
    return vals;
  }
  function applyFieldValue(i, val) {
    const v = S.cur.variables[i]; if (!v) return;
    val = val == null ? "" : String(val);
    if (v.control === "radio") {
      $$(`#fields input[type=radio][data-i="${i}"]`).forEach((el) => { el.checked = el.value === val; });
      return;
    }
    if (v.control === "multiselect") {
      const sel = new Set(val.split(/[、,/，]/).map((s) => s.trim()).filter(Boolean));
      $$(`#fields input[type=checkbox][data-i="${i}"]`).forEach((el) => { el.checked = sel.has(el.value); });
      return;
    }
    const el = $(`#fields select[data-i="${i}"], #fields textarea[data-i="${i}"], #fields input.input[data-i="${i}"]`);
    if (el) el.value = val;
  }
  function restore(vals) {
    (S.cur.variables || []).forEach((v, i) => { if (v.name in vals) applyFieldValue(i, vals[v.name]); });
  }
  function fieldError(v, val) {
    val = String(val ?? "");
    if (v.required && !val.trim()) return "必填";
    if (val.trim() && v.control === "number" && isNaN(Number(val.trim().replace(/,/g, "")))) return "请输入数字";
    if (val && (v.control === "select" || v.control === "radio") && v.options?.length && !v.options.includes(val)) return "不在选项中";
    if (val.trim() && v.control === "multiselect" && v.options?.length) {
      const bad = val.split(/[、,/，]/).map((s) => s.trim()).filter(Boolean).filter((x) => !v.options.includes(x));
      if (bad.length) return "含无效选项";
    }
    return "";
  }
  function validate(showAll) {
    let firstBad = null; const bad = [];
    const seen = new Set();
    $$("#fields [data-i]").forEach((el) => {
      const i = +el.dataset.i; if (seen.has(i)) return; seen.add(i);
      const v = S.cur.variables[i];
      const group = $(`.choice-group[data-i="${i}"]`) || el;
      const touched = showAll || el.dataset.touched || group.dataset?.touched;
      const msg = touched ? fieldError(v, readFieldValue(i)) : "";
      const mark = (v.control === "radio" || v.control === "multiselect") ? group : el;
      mark.classList.toggle("invalid", !!msg); mark.setAttribute("aria-invalid", msg ? "true" : "false");
      const m = document.querySelector(`[data-m="${i}"]`); if (m) m.textContent = msg;
      if (msg) {
        bad.push(v.name);
        firstBad = firstBad || (v.control === "radio" || v.control === "multiselect" ? ($("input", group) || mark) : el);
      }
    });
    return { bad, firstBad };
  }
  async function submitForm() {
    const vals = collect();
    const { bad, firstBad } = validate(true);
    if (bad.length) { foot(`请填写：${bad.join("、")}`, "err"); if (firstBad) firstBad.focus(); return; }
    await commit(S.cur.id, vals);
  }
  function nextField(el) {
    const all = [];
    const seen = new Set();
    $$("#fields [data-i]").forEach((x) => {
      const i = +x.dataset.i; if (seen.has(i)) return; seen.add(i);
      const v = S.cur.variables[i];
      if (v.control === "radio" || v.control === "multiselect") {
        const g = $(`.choice-group[data-i="${i}"]`);
        all.push(g ? ($("input", g) || g) : x);
      } else all.push(x);
    });
    const cur = el.closest?.("[data-i]") || el;
    const idx = all.findIndex((x) => x === el || x === cur || (x.dataset && cur.dataset && x.dataset.i === cur.dataset.i));
    if (idx >= 0 && idx < all.length - 1) {
      const n = all[idx + 1]; n.focus();
      if (n.select && n.tagName === "INPUT" && n.type !== "radio" && n.type !== "checkbox") n.select();
      return true;
    }
    return false;
  }
  async function commit(id, vals) {
    if (S.committing) return;
    S.committing = true;
    foot("正在插入…");
    try {
      const r = await api().qp_commit(id, vals);
      if (!r || !r.ok) foot((r && r.error) || "插入失败", "err");
    } finally { S.committing = false; }
  }
  function backToList() {
    S.mode = "list"; S.cur = null;
    $("#form").classList.add("hidden"); $("#list").classList.remove("hidden"); $(".qp-search").classList.remove("hidden");
    renderList(); $("#q").focus(); foot();
  }
  function cancel(reason) { if (api()) api().qp_cancel(reason); }


  // ---------------------------------------------------------------- AI fill
  function setAiMsg(text, kind) {
    const el = $("#aiFillMsg"); if (!el) return;
    el.className = "qp-ai-msg" + (kind ? " " + kind : "");
    el.innerHTML = text || "";
  }
  async function runAiFill() {
    if (!api() || !S.cur || S.aiBusy) return;
    const need = ($("#aiNeed")?.value || "").trim();
    if (!need) { setAiMsg("请先用一句话描述需求", "err"); $("#aiNeed")?.focus(); return; }
    const btn = $("#aiFillBtn");
    S.aiBusy = true;
    if (btn) { btn.disabled = true; btn.classList.add("busy"); }
    setAiMsg('<span class="qp-busy">正在填写…</span>');
    try {
      const schema = (S.cur.variables || []).map((v) => ({
        name: v.name, control: v.control, control_label: v.control_label,
        options: v.options || [], required: !!v.required, default: v.default,
      }));
      const r = await api().ai_fill_form(schema, need);
      if (!r) { setAiMsg("无法连接应用", "err"); return; }
      if (r.need_settings || (r.error && /API Key|AI 模型|配置/.test(r.error || ""))) {
        setAiMsg((r.error || "请先配置 API Key") + ' · 打开主窗口「设置 → AI 模型」', "err");
        return;
      }
      if (!r.ok) { setAiMsg(r.error || "AI 填写失败", "err"); return; }
      const vals = r.values || {};
      restore(vals);
      // mark touched so validation reflects AI fill
      $$("#fields [data-i]").forEach((el) => { el.dataset.touched = "1"; });
      $$("#fields .choice-group").forEach((el) => { el.dataset.touched = "1"; });
      validate(false);
      const n = Object.keys(vals).length;
      setAiMsg(`已填写 ${n} 项，可继续手动调整后插入`, "ok");
      foot(`AI 已填 ${n} 项`);
    } catch (e) {
      setAiMsg((e && e.message) || "AI 填写出错", "err");
    } finally {
      S.aiBusy = false;
      if (btn) { btn.disabled = false; btn.classList.remove("busy"); }
    }
  }

  // ---------------------------------------------------------------- events
  $("#q").addEventListener("input", filter);
  $("#fields").addEventListener("input", (e) => {
    if (e.target.dataset.i == null) return;
    const v = S.cur?.variables?.[+e.target.dataset.i];
    if (v && (v.control === "radio" || v.control === "multiselect")) return;
    e.target.dataset.touched = "1"; validate(false);
  });
  $("#fields").addEventListener("change", (e) => {
    if (e.target.dataset.i == null) return;
    const v = S.cur?.variables?.[+e.target.dataset.i];
    if (!v) return;
    if (e.target.tagName === "SELECT" || v.control === "radio" || v.control === "multiselect") {
      e.target.dataset.touched = "1";
      const g = e.target.closest(".choice-group"); if (g) g.dataset.touched = "1";
      validate(false);
    }
  });
  $("#aiFillBtn")?.addEventListener("click", (e) => { e.preventDefault(); runAiFill(); });
  $("#aiNeed")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); runAiFill(); }
  });
  $("#list").addEventListener("mousemove", (e) => {
    const n = e.target.closest(".qp-item"); if (!n) return;
    const i = +n.dataset.i; if (i !== S.sel) { S.sel = i; $$(".qp-item").forEach((x, k) => x.classList.toggle("sel", k === i)); }
  });
  $("#list").addEventListener("click", (e) => {
    if (e.target.closest("[data-act=main]")) { if (api()) api().qp_open_main(); return; }
    const h = e.target.closest("[data-collapse]");
    if (h) {
      const k = h.getAttribute("data-collapse");
      if (k) {
        S.collapsed[k] = !S.collapsed[k];
        const keepId = S.shown[S.sel] && S.shown[S.sel].id;
        filter();
        if (keepId) {
          const ni = S.shown.findIndex((x) => x.id === keepId);
          if (ni >= 0) { S.sel = ni; renderList(); }
        }
      }
      return;
    }
    const n = e.target.closest(".qp-item"); if (n) choose(+n.dataset.i, e.shiftKey);
  });
  $("#foot").addEventListener("click", (e) => { if (e.target.closest("[data-act=exclude]") && api()) api().qp_exclude_current(); });
  $("#back").onclick = backToList;
  $("#insertBtn").onclick = submitForm;
  document.addEventListener("mousedown", (e) => {
    // keep the caret in the search box when clicking list rows (no focus loss → no IME surprises)
    if (S.mode === "list" && !e.target.closest("input, button")) e.preventDefault();
  });
  document.addEventListener("keydown", (e) => {
    if (e.isComposing || e.keyCode === 229) return;  // IME composing: let the IME handle keys
    if (S.mode === "list") {
      if (e.key === "ArrowDown" || (e.key === "Tab" && !e.shiftKey) || (e.ctrlKey && e.key === "n")) { e.preventDefault(); moveSel(1); }
      else if (e.key === "ArrowUp" || (e.key === "Tab" && e.shiftKey) || (e.ctrlKey && e.key === "p")) { e.preventDefault(); moveSel(-1); }
      else if (e.key === "PageDown") { e.preventDefault(); moveSel(5, true); }
      else if (e.key === "PageUp") { e.preventDefault(); moveSel(-5, true); }
      else if ((e.key === "Home" || e.key === "End") && (e.ctrlKey || !$("#q").value)) { e.preventDefault(); moveSel(e.key === "Home" ? -1e6 : 1e6, true); }
      else if (e.key === "Enter") { e.preventDefault(); if (!S.items.length) { if (api()) api().qp_open_main(); } else choose(S.sel, e.shiftKey); }
      else if (e.key === "Escape") { e.preventDefault(); cancel("esc"); }
      else if (document.activeElement !== $("#q") && e.key.length === 1 && !e.ctrlKey && !e.altKey) $("#q").focus();
    } else {
      if (e.key === "Escape") { e.preventDefault(); backToList(); }
      else if (e.key === "Enter" && e.ctrlKey) { e.preventDefault(); submitForm(); }
      else if (e.key === "Enter" && (e.target.tagName === "TEXTAREA" || e.target.tagName === "BUTTON")) { /* newline / button click */ }
      else if (e.key === "Enter") { e.preventDefault(); if (!(e.target.dataset && e.target.dataset.i != null && nextField(e.target))) submitForm(); }
    }
  });
  window.addEventListener("contextmenu", (e) => e.preventDefault());

  // ---------------------------------------------------------------- host API
  function reset() {
    S.mode = "list"; S.cur = null; S.busy = false; S.committing = false; S.sel = 0;
    $("#form").classList.add("hidden"); $("#list").classList.remove("hidden"); $(".qp-search").classList.remove("hidden");
    $("#fields").innerHTML = "";
    const aiNeed = $("#aiNeed"); if (aiNeed) aiNeed.value = "";
    const aiMsg = $("#aiFillMsg"); if (aiMsg) { aiMsg.textContent = ""; aiMsg.className = "qp-ai-msg"; }
    $("#q").value = ""; filter(); $("#list").scrollTop = 0;
    // keep DOM focus on the search box so the first typed key lands there the moment the window shows
    $("#q").focus();
    return true;
  }
  window.__qpPrepare = (payload) => {
    payload = payload || {};
    S.theme = payload.theme || "system"; applyTheme();
    try { localStorage.setItem("pb.theme", S.theme); } catch (e) { /* storage unavailable */ }
    S.items = payload.items || []; S.preview = payload.preview !== false;
    $("#hkHint").textContent = payload.hotkey || "//";
    return reset();
  };
  window.__qpOpen = window.__qpPrepare;  // 2.4 compatibility
  window.__qpReset = reset;
  window.__qpFocus = (ctx) => {
    if (ctx && typeof ctx.exe === "string" && ctx.exe !== S.exe) {
      S.exe = ctx.exe;
      const b = $("[data-act=exclude]"); if (b) b.title = `以后在${S.exe || "当前程序"}中输入 // 不再弹出（可在设置中恢复）`;
    }
    window.focus();
    const el = S.mode === "list" ? $("#q") : $("#fields [data-i]");
    if (el && document.activeElement !== el) el.focus();
    return document.hasFocus();
  };
  if (window.PBIcons) window.PBIcons.fill();
})();

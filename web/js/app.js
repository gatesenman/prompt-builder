/* PromptBuilder 2.12.8 — role system prompt · lint · rev diff · cases · DnD/MD from 2.12.7
   + insert-variable menu, onboarding, F1 help, toasts with undo, settings (theme / admin mode) */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const debounce = (fn, ms) => { let t; const d = (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; d.flush = (...a) => { clearTimeout(t); return fn(...a); }; d.cancel = () => clearTimeout(t); return d; };
  const I = (name, size = 16) => window.PBIcons.svg(name, size);

  const S = {
    api: null, version: "", settings: {}, list: [], query: "",
    tree: { roles: [] },  // Role › Category › Prompt
    expanded: {},         // roleId / catId -> bool (session)
    activeRole: "", activeCat: "",  // where new prompts go
    flatMode: false,      // search / fav / tag / archive → flat list
    flatItems: [],        // flattened prompt rows for keyboard nav
    cur: null,            // {id, name, body, tags, favorite, pinned, ...}
    values: {},           // working test values (string per variable)
    analysis: null, varSig: "", dirty: false, valuesDirty: false,
    tab: "form", previewView: "text", renamingId: null, cursor: -1, elevated: false, admin: null,
    sort: "recent", tag: "", favOnly: false, archivedOnly: false,
    tags: [], starters: [],
    revSel: null, histFilter: "",
  };
  const iconKey = (name) => {
    if (!name) return "folder";
    const map = { "search-code": "searchCode", "file-text": "fileText" };
    const k = map[name] || name;
    return (window.PBIcons && window.PBIcons.names && window.PBIcons.names.includes(k)) ? k : "folder";
  };
  function ensureExpandedDefaults() {
    if (!S.tree || !S.tree.roles) return;
    // first visit: expand 我的提示 + first few roles
    const keys = Object.keys(S.expanded);
    if (keys.length) return;
    S.tree.roles.forEach((r, i) => {
      if (r.id === "role-mine" || i < 2) S.expanded[r.id] = true;
    });
  }

  // ---------------------------------------------------------------- toasts
  const T_ICON = { success: "check", error: "alert", warn: "alert", info: "info" };
  function toast(msg, opt = {}) {
    if (typeof opt === "number") opt = { ms: opt };
    const type = opt.type || "success", box = $("#toasts");
    while (box.children.length >= 3) box.firstElementChild.remove();
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.setAttribute("role", type === "error" ? "alert" : "status");
    el.innerHTML = `<span class="t-ic">${I(T_ICON[type] || "info")}</span><span class="t-msg"></span>` +
      (opt.action ? `<button class="t-act"></button>` : "") + `<button class="t-x" aria-label="关闭">${I("x", 14)}</button>`;
    $(".t-msg", el).textContent = msg;
    let timer;
    const close = () => { clearTimeout(timer); el.classList.add("out"); setTimeout(() => el.remove(), 170); };
    const arm = () => { clearTimeout(timer); timer = setTimeout(close, opt.ms || (opt.action ? 6000 : type === "error" ? 5000 : 2400)); };
    if (opt.action) $(".t-act", el).textContent = opt.action, $(".t-act", el).onclick = () => { close(); opt.onAction && opt.onAction(); };
    $(".t-x", el).onclick = close;
    el.addEventListener("mouseenter", () => clearTimeout(timer));
    el.addEventListener("mouseleave", arm);
    box.appendChild(el); arm();
    return close;
  }
  async function call(name, ...args) {
    try { return await S.api[name](...args); }
    catch (e) { console.error(name, e); toast(`操作失败：${e && e.message ? e.message : e}`, { type: "error" }); return null; }
  }
  function relTime(iso) {
    if (!iso) return "";
    const d = new Date(iso), diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return "刚刚"; if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`; if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`;
    return `${d.getMonth() + 1}/${d.getDate()}`;
  }
  function highlight(text, q) {
    const terms = (q || "").toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return esc(text);
    const low = text.toLowerCase(), marks = new Array(text.length).fill(false);
    terms.forEach((t) => { let i = low.indexOf(t); while (i >= 0) { for (let k = i; k < i + t.length; k++) marks[k] = true; i = low.indexOf(t, i + t.length); } });
    let out = "", on = false;
    for (let i = 0; i < text.length; i++) {
      if (marks[i] !== on) { out += marks[i] ? "<mark>" : "</mark>"; on = marks[i]; }
      out += esc(text[i]);
    }
    return out + (on ? "</mark>" : "");
  }

  // ---------------------------------------------------------------- modals (focus trap + restore)
  const modalStack = [];
  const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';
  function openModal(id, focusSel) {
    const o = $("#" + id); if (!o.classList.contains("hidden")) return;
    modalStack.push({ id, prev: document.activeElement });
    o.classList.remove("hidden");
    const f = (focusSel && $(focusSel, o)) || $$(FOCUSABLE, $(".modal", o)).find((x) => x.offsetParent && !x.hasAttribute("data-close")) || $(".modal", o);
    setTimeout(() => f && f.focus(), 0);
  }
  function closeModal(id) {
    const o = $("#" + id); if (!o || o.classList.contains("hidden")) return;
    o.classList.add("hidden");
    const i = modalStack.findIndex((m) => m.id === id);
    const m = i >= 0 ? modalStack.splice(i, 1)[0] : null;
    if (MODAL_CLOSE[id]) MODAL_CLOSE[id]();
    if (m && m.prev && document.contains(m.prev)) setTimeout(() => m.prev.focus(), 0);
  }
  const MODAL_CLOSE = {};
  const topModal = () => modalStack.length ? modalStack[modalStack.length - 1].id : null;
  $$(".overlay").forEach((o) => o.addEventListener("mousedown", (e) => {
    if (e.target.closest("[data-close]")) return closeModal(o.id);
    if (e.target === o && o.id !== "onbOverlay") closeModal(o.id);
  }));
  document.addEventListener("keydown", (e) => {
    const id = topModal(); if (!id || e.key !== "Tab") return;
    const items = $$(FOCUSABLE, $("#" + id)).filter((x) => x.offsetParent);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }, true);

  let confirmResolve = null;
  function confirmDialog({ title, message, ok = "确定", cancel = "取消", danger = false }) {
    $("#confirmTitle").textContent = title; $("#confirmMsg").textContent = message || "";
    $("#confirmOk").textContent = ok; $("#confirmCancel").textContent = cancel;
    $("#confirmOk").className = "btn sm " + (danger ? "danger" : "primary");
    openModal("confirmOverlay", "#confirmOk");
    return new Promise((res) => { confirmResolve = res; });
  }
  MODAL_CLOSE.confirmOverlay = () => { if (confirmResolve) { const r = confirmResolve; confirmResolve = null; r(false); } };
  $("#confirmOk").onclick = () => { const r = confirmResolve; confirmResolve = null; closeModal("confirmOverlay"); r && r(true); };
  $("#confirmCancel").onclick = () => closeModal("confirmOverlay");

  // ---------------------------------------------------------------- theme
  const mql = matchMedia("(prefers-color-scheme: light)");
  const THEME_NAME = { system: "跟随系统", light: "浅色", dark: "深色" };
  function applyTheme(pref) {
    try { localStorage.setItem("pb.theme", pref || "system"); } catch (e) { /* storage unavailable */ }
    pref = THEME_NAME[pref] ? pref : "system";
    const t = pref === "system" ? (mql.matches ? "light" : "dark") : pref;
    document.documentElement.dataset.theme = t;
    $("#themeIcon").innerHTML = I(pref === "system" ? "monitor" : pref === "light" ? "sun" : "moon");
    $("#themeBtn").title = `主题：${THEME_NAME[pref]}（点击切换）`;
  }
  mql.addEventListener("change", () => applyTheme(S.settings.theme));
  $("#themeBtn").onclick = async () => {
    const order = ["system", "light", "dark"];
    const next = order[(order.indexOf(S.settings.theme) + 1) % 3];
    const r = await saveSettings({ theme: next });
    if (r && r.ok) toast(`主题：${THEME_NAME[next]}`, { type: "info", ms: 1400 });
  };

  // ---------------------------------------------------------------- list / tree
  async function refreshList() {
    S.flatMode = !!(S.query || S.tag || S.favOnly || S.archivedOnly);
    if (S.flatMode) {
      S.list = (await call("list_prompts", S.query, S.sort, S.tag, !!S.favOnly, !!S.archivedOnly)) || [];
      S.flatItems = S.list.slice();
    } else {
      S.tree = (await call("get_tree", S.query || "")) || { roles: [] };
      ensureExpandedDefaults();
      // keep a flat list of all prompts for counts / empty editor
      S.list = [];
      S.flatItems = [];
      (S.tree.roles || []).forEach((r) => {
        (r.prompts || []).forEach((p) => { S.list.push(p); S.flatItems.push(p); });
        // legacy fallback if an older payload still nests categories
        (r.categories || []).forEach((c) => {
          (c.prompts || []).forEach((p) => { S.list.push(p); S.flatItems.push(p); });
        });
      });
    }
    renderList();
    renderTagBar();
  }
  function emptyState(icon, title, body, actions = "") {
    return `<div class="empty"><div class="empty-ico">${I(icon, 22)}</div><div class="empty-title">${title}</div>${body ? `<div>${body}</div>` : ""}${actions ? `<div class="empty-actions">${actions}</div>` : ""}</div>`;
  }
  function promptRowHTML(p, i, depth) {
    const cls = (S.cur && p.id === S.cur.id ? " active" : "") + (i === S.cursor ? " cursor" : "");
    if (p.id === S.renamingId) {
      return `<div class="item tree-leaf depth-${depth}${cls}" data-id="${esc(p.id)}" role="treeitem"><input class="input rename" value="${esc(p.name)}" maxlength="80" aria-label="新名称"></div>`;
    }
    const flags = (p.pinned ? I("pin", 11) : "") + (p.favorite ? I("star", 11) : "") + (p.builtin ? `<span class="sys-badge" title="内置">内置</span>` : "");
    const acts = p.builtin
      ? `<button tabindex="-1" data-act="copybuiltin" title="复制后编辑">${I("copy", 13)}</button><button tabindex="-1" data-act="fav" title="${p.favorite ? "取消收藏" : "收藏"}">${I("star", 13)}</button>`
      : `<button tabindex="-1" data-act="fav" title="${p.favorite ? "取消收藏" : "收藏"}">${I("star", 13)}</button><button tabindex="-1" data-act="rename" title="重命名 (F2)">${I("edit", 13)}</button><button tabindex="-1" data-act="duplicate" title="复制">${I("copy", 13)}</button><button tabindex="-1" class="del" data-act="delete" title="删除">${I("trash", 13)}</button>`;
    const canDrag = !S.flatMode && !p.builtin && !p.system;
    const dragAttr = canDrag ? ` draggable="true" data-pb-drag="prompt"` : (p.builtin || p.system ? ` data-pb-drag="builtin"` : "");
    return `<div class="item tree-leaf depth-${depth}${cls}" role="treeitem" aria-selected="${cls.includes("active")}" id="opt-${i}" data-id="${esc(p.id)}" data-role="${esc(p.role_id || "")}" data-cat="${esc(p.category_id || "")}" title="${esc(p.preview || "")}"${dragAttr}>
      <div class="item-main"><div class="item-name">${highlight(p.name, S.query)}${flags ? `<span class="item-flags">${flags}</span>` : ""}</div></div>
      <div class="item-actions">${acts}</div></div>`;
  }
  function renderList() {
    const el = $("#list");
    const total = S.flatItems.length;
    $("#listCount").textContent = total;
    $("#searchClear").classList.toggle("hidden", !$("#search").value);
    $("#searchKbd").classList.toggle("hidden", !!$("#search").value);
    if (!total && S.flatMode) {
      if (S.archivedOnly) {
        el.innerHTML = emptyState("archive", "归档是空的", "归档的提示词会出现在这里，可随时恢复。");
      } else if (S.favOnly && !(S.query || S.tag)) {
        el.innerHTML = emptyState("star", "还没有收藏", "在提示词上点星标，或打开后点标题旁的收藏，会出现在这里。", `<button class="btn secondary sm" data-empty="goto-all">查看全部</button>`);
      } else if (S.query || S.tag) {
        el.innerHTML = emptyState("search", S.query ? `没有找到「${esc(S.query)}」` : "没有匹配的提示词",
          S.archivedOnly ? "在当前「归档」范围内没有匹配项。可清除搜索，或切换到「全部」。"
            : S.favOnly ? "在当前「收藏」范围内没有匹配项。可清除搜索，或切换到「全部」。"
            : "试试其他关键词，或清除筛选。名称、正文、标签与角色都会被搜索。",
          `<button class="btn secondary sm" data-empty="clear">清除搜索与筛选</button>`);
      } else {
        el.innerHTML = emptyState("file", "还没有提示词", "新建一个，或从角色库选用内置模板。", `<button class="btn primary sm" data-empty="new">${I("plus", 14)}新建提示词</button><button class="btn secondary sm" data-empty="import">${I("import", 14)}导入…</button>`);
      }
      return;
    }
    if (S.flatMode) {
      if (S.cursor < 0 || S.cursor >= S.flatItems.length) {
        const curIdx = S.cur ? S.flatItems.findIndex((p) => p.id === S.cur.id) : -1;
        S.cursor = Math.max(0, curIdx);
      }
      el.innerHTML = S.flatItems.map((p, i) => promptRowHTML(p, i, 0)).join("");
      el.setAttribute("aria-activedescendant", `opt-${S.cursor}`);
      const r = $(".rename", el); if (r) { r.focus(); r.select(); }
      return;
    }
    // Tree mode — 2.10 flat: 角色 › 提示
    let html = "";
    let idx = 0;
    const nav = [];
    (S.tree.roles || []).forEach((role) => {
      const open = !!S.expanded[role.id];
      const rIcon = iconKey(role.icon);
      const prompts = (role.prompts && role.prompts.length)
        ? role.prompts
        : (role.categories || []).flatMap((c) => c.prompts || []);
      html += `<div class="tree-role${open ? " open" : ""}" role="treeitem" aria-expanded="${open}" data-role-id="${esc(role.id)}" id="role-${esc(role.id)}">
        <div class="tree-row role-row" data-toggle-role="${esc(role.id)}" data-role-id="${esc(role.id)}" draggable="true" data-pb-drag="role" tabindex="-1">
          <span class="twisty">${I(open ? "chevDown" : "chevRight", 14)}</span>
          <span class="tree-ico">${I(rIcon, 15)}</span>
          <span class="tree-label">${esc(role.name)}</span>
          <span class="badge">${role.count != null ? role.count : prompts.length}</span>
          ${role.builtin ? `<span class="sys-badge">系统</span>` : ""}
          <span class="tree-acts"><button tabindex="-1" data-role-act="sysprompt" data-role-id="${esc(role.id)}" title="系统提示">${I("file", 12)}</button>${role.builtin ? "" : `<button tabindex="-1" data-role-act="rename" data-role-id="${esc(role.id)}" title="重命名">${I("edit", 12)}</button><button tabindex="-1" data-role-act="delete" data-role-id="${esc(role.id)}" title="删除角色">${I("trash", 12)}</button>`}<button tabindex="-1" data-role-act="add" data-role-id="${esc(role.id)}" title="在此新建提示词">${I("plus", 12)}</button></span>
        </div>`;
      if (open) {
        prompts.forEach((p) => {
          nav.push(p);
          html += promptRowHTML(p, idx++, 1);
        });
      }
      html += `</div>`;
    });
    S.flatItems = nav;
    if (!nav.length && !(S.tree.roles || []).length) {
      el.innerHTML = emptyState("folder", "角色库为空", "创建角色，或检查内置库是否正确安装。", `<button class="btn primary sm" data-empty="newrole">新建角色</button>`);
      return;
    }
    if (S.cursor < 0 || S.cursor >= nav.length) {
      const curIdx = S.cur ? nav.findIndex((p) => p.id === S.cur.id) : -1;
      S.cursor = Math.max(0, curIdx);
    }
    if (!html) {
      el.innerHTML = emptyState("folder", "展开角色查看提示词", "点击角色左侧箭头展开。内置开发角色已就绪。");
    } else {
      el.innerHTML = html;
    }
    if (nav.length) el.setAttribute("aria-activedescendant", `opt-${S.cursor}`);
    const r = $(".rename", el); if (r) { r.focus(); r.select(); }
  }
  async function updateCrumb() {
    const box = $("#crumb");
    if (!S.cur) { box.hidden = true; return; }
    const b = await call("breadcrumb", S.cur.id);
    if (!b || !b.role) { box.hidden = true; return; }
    const roleName = (b.role && b.role.name) || "";
    S.activeRole = (b.role && b.role.id) || S.activeRole;
    // 2.12.1: hide noisy default「我的提示」crumb; only show other roles quietly
    if (!roleName || roleName === "我的提示") { box.hidden = true; return; }
    $("#crumbRole").textContent = roleName;
    const catEl = $("#crumbCat");
    if (catEl) { catEl.textContent = ""; catEl.hidden = true; }
    const sep = box.querySelector(".crumb-sep");
    if (sep) sep.hidden = true;
    box.hidden = false;
  }
  $("#list").addEventListener("click", async (e) => {
    const emp = e.target.closest("[data-empty]")?.dataset.empty;
    if (emp === "clear") { clearSearch(); S.tag = ""; return refreshList(); } /* 2.12.6: keep 全部/收藏/归档 tab */
    if (emp === "goto-all") { setLibScope("all"); return; }
    if (emp === "new") return newPrompt();
    if (emp === "newrole") return newRole();
    if (emp === "import") return runIO("import-json");

    const roleAct = e.target.closest("[data-role-act]");
    if (roleAct) {
      e.stopPropagation();
      const id = roleAct.dataset.roleId, act = roleAct.dataset.roleAct;
      if (act === "add") { S.activeRole = id; S.activeCat = ""; return newPrompt(); }
      if (act === "rename") return renameRole(id);
      if (act === "delete") return deleteRole(id);
      if (act === "sysprompt") return openRoleSysPrompt(id);
      return;
    }
    // 2.10: categories are not user-facing; ignore legacy cat act nodes if any
    if (e.target.closest("[data-cat-act]")) { e.stopPropagation(); return; }
    const tr = e.target.closest("[data-toggle-role]");
    if (tr && !e.target.closest(".tree-acts")) {
      const id = tr.dataset.toggleRole;
      S.expanded[id] = !S.expanded[id];
      renderList(); return;
    }
    // 2.10: no category toggle

    const item = e.target.closest(".item"); if (!item || e.target.classList.contains("rename")) return;
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "rename") return startRename(item.dataset.id);
    if (act === "duplicate") return duplicatePrompt(item.dataset.id);
    if (act === "copybuiltin") return copyBuiltin(item.dataset.id);
    if (act === "delete") return deletePrompt(item.dataset.id);
    if (act === "fav") return toggleFavorite(item.dataset.id);
    S.cursor = S.flatItems.findIndex((p) => p.id === item.dataset.id);
    if (item.dataset.role) S.activeRole = item.dataset.role;
    if (item.dataset.cat) S.activeCat = item.dataset.cat;
    openPrompt(item.dataset.id);
  });
  $("#list").addEventListener("dblclick", (e) => {
    const item = e.target.closest(".item");
    if (item && !e.target.closest(".rename, [data-act]")) {
      const p = S.flatItems.find((x) => x.id === item.dataset.id);
      if (p && p.builtin) return copyBuiltin(p.id);
      startRename(item.dataset.id);
    }
  });
  $("#list").addEventListener("keydown", (e) => {
    if (e.target.classList.contains("rename")) {
      if (e.key === "Enter") { e.preventDefault(); finishRename(e.target.value); $("#list").focus(); }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); S.renamingId = null; renderList(); $("#list").focus(); }
      return;
    }
    if (e.target !== $("#list") || !S.flatItems.length) return;
    const n = S.flatItems.length, move = { ArrowDown: 1, ArrowUp: -1, PageDown: 8, PageUp: -8 }[e.key];
    let to = null;
    if (move) to = Math.max(0, Math.min(n - 1, S.cursor + move));
    else if (e.key === "Home") to = 0; else if (e.key === "End") to = n - 1;
    if (to != null) {
      e.preventDefault(); S.cursor = to; renderList();
      $(`#opt-${to}`)?.scrollIntoView({ block: "nearest" });
      openPromptSoon(S.flatItems[to].id); return;
    }
    // Left/Right: collapse/expand around current
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      const p = S.flatItems[S.cursor]; if (!p) return;
      e.preventDefault();
      if (e.key === "ArrowLeft" && p.category_id && S.expanded[p.category_id]) {
        S.expanded[p.category_id] = false; renderList();
      } else if (e.key === "ArrowRight" && p.category_id && !S.expanded[p.category_id]) {
        S.expanded[p.category_id] = true; if (p.role_id) S.expanded[p.role_id] = true; renderList();
      }
      return;
    }
    const p = S.flatItems[S.cursor]; if (!p) return;
    if (e.key === "Enter") { e.preventDefault(); openPrompt(p.id).then(() => editor.focus()); }
    else if (e.key === "Delete" && !p.builtin) { e.preventDefault(); deletePrompt(p.id); }
    else if (e.key === "F2" && !p.builtin) { e.preventDefault(); e.stopPropagation(); startRename(p.id); }
  });
  const openPromptSoon = debounce((id) => openPrompt(id), 90);
  $("#list").addEventListener("focusout", (e) => { if (e.target.classList.contains("rename")) finishRename(e.target.value); });

  // ---------------------------------------------------------------- 2.12.7 library DnD (prompt→role move · role reorder)
  const MIME_PROMPT = "application/x-pb-prompt";
  const MIME_ROLE = "application/x-pb-role";
  const dndState = { kind: "", id: "", suppressClick: false };
  function clearRoleDropMarks() {
    $$(".tree-role.pb-drop-role, .tree-role.pb-drop-before, .tree-role.pb-drop-after, .role-row.pb-drop-role, .pb-role-dragging, .pb-dragging").forEach((el) => {
      el.classList.remove("pb-drop-role", "pb-drop-before", "pb-drop-after", "pb-role-dragging", "pb-dragging");
    });
  }
  function roleIdsInDom() {
    return $$("#list .tree-role[data-role-id]").map((el) => el.dataset.roleId).filter(Boolean);
  }
  $("#list").addEventListener("click", (e) => {
    if (dndState.suppressClick) {
      e.preventDefault(); e.stopPropagation();
      dndState.suppressClick = false;
    }
  }, true);
  $("#list").addEventListener("dragstart", (e) => {
    if (S.flatMode) { e.preventDefault(); return; }
    const leaf = e.target.closest(".tree-leaf[data-pb-drag='prompt']");
    const roleRow = e.target.closest(".role-row[data-pb-drag='role']");
    const builtin = e.target.closest(".tree-leaf[data-pb-drag='builtin']");
    if (builtin) {
      e.preventDefault();
      toast("内置提示词请先复制后编辑", { type: "warn" });
      return;
    }
    if (leaf && !e.target.closest(".item-actions, .rename, button")) {
      dndState.kind = "prompt"; dndState.id = leaf.dataset.id;
      e.dataTransfer.setData(MIME_PROMPT, leaf.dataset.id);
      e.dataTransfer.setData("text/plain", leaf.dataset.id);
      e.dataTransfer.effectAllowed = "move";
      leaf.classList.add("pb-dragging");
      return;
    }
    if (roleRow && !e.target.closest(".tree-acts, button")) {
      const rid = roleRow.dataset.roleId || roleRow.dataset.toggleRole;
      dndState.kind = "role"; dndState.id = rid;
      e.dataTransfer.setData(MIME_ROLE, rid);
      e.dataTransfer.setData("text/plain", rid);
      e.dataTransfer.effectAllowed = "move";
      const tr = roleRow.closest(".tree-role");
      if (tr) tr.classList.add("pb-role-dragging");
      return;
    }
    e.preventDefault();
  });
  $("#list").addEventListener("dragend", () => {
    if (dndState.kind) dndState.suppressClick = true;
    dndState.kind = ""; dndState.id = "";
    clearRoleDropMarks();
  });
  $("#list").addEventListener("dragover", (e) => {
    if (S.flatMode) return;
    const tr = e.target.closest(".tree-role[data-role-id]");
    if (!tr) return;
    const types = e.dataTransfer.types || [];
    const isPrompt = dndState.kind === "prompt" || [...types].includes(MIME_PROMPT);
    const isRole = dndState.kind === "role" || [...types].includes(MIME_ROLE);
    if (!isPrompt && !isRole) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    clearRoleDropMarks();
    if (isRole) {
      const rect = tr.getBoundingClientRect();
      const before = (e.clientY - rect.top) < rect.height / 2;
      tr.classList.add(before ? "pb-drop-before" : "pb-drop-after");
    } else {
      tr.classList.add("pb-drop-role");
    }
  });
  $("#list").addEventListener("dragleave", (e) => {
    const tr = e.target.closest(".tree-role");
    if (tr && !tr.contains(e.relatedTarget)) {
      tr.classList.remove("pb-drop-role", "pb-drop-before", "pb-drop-after");
    }
  });
  $("#list").addEventListener("drop", async (e) => {
    if (S.flatMode) return;
    const tr = e.target.closest(".tree-role[data-role-id]");
    if (!tr) return;
    e.preventDefault();
    const targetRole = tr.dataset.roleId;
    const promptId = e.dataTransfer.getData(MIME_PROMPT) || (dndState.kind === "prompt" ? dndState.id : "");
    const roleId = e.dataTransfer.getData(MIME_ROLE) || (dndState.kind === "role" ? dndState.id : "");
    const wasRole = dndState.kind === "role" || (!!roleId && !promptId);
    clearRoleDropMarks();
    if (wasRole && roleId) {
      const ids = roleIdsInDom().filter((id) => id !== roleId);
      const rect = tr.getBoundingClientRect();
      const before = (e.clientY - rect.top) < rect.height / 2;
      let idx = ids.indexOf(targetRole);
      if (idx < 0) idx = ids.length;
      if (!before) idx += 1;
      ids.splice(idx, 0, roleId);
      const r = await call("reorder_roles", ids);
      if (r && r.ok) { await refreshList(); toast("已调整分组顺序", { type: "info", ms: 1400 }); }
      else toast((r && r.error) || "调整顺序失败", { type: "error" });
      return;
    }
    if (promptId && targetRole) {
      const r = await call("move_prompt_to_role", promptId, targetRole);
      if (r && r.ok) {
        S.expanded[targetRole] = true;
        S.activeRole = targetRole;
        await refreshList();
        const moved = r.prompt;
        if (moved) {
          S.cursor = S.flatItems.findIndex((p) => p.id === moved.id);
          await openPrompt(moved.id);
        }
        const roleName = ((S.tree.roles || []).find((x) => x.id === targetRole) || {}).name || "角色";
        toast(`已移到「${roleName}」`);
      } else {
        toast((r && r.error) || "无法移动", { type: "warn" });
      }
    }
  });


  function startRename(id) { S.renamingId = id; renderList(); }
  async function finishRename(name) {
    const id = S.renamingId; if (!id) return; S.renamingId = null;
    name = (name || "").trim();
    if (name) {
      const r = await call("rename_prompt", id, name);
      if (r && r.ok && S.cur && S.cur.id === id) { S.cur.name = r.prompt.name; title.value = r.prompt.name; syncTitleWidth(); }
      if (r && r.prompt && r.prompt._copied_from_builtin) {
        toast("已复制为可编辑副本"); await refreshList(); await openPrompt(r.prompt.id); return;
      }
    }
    refreshList();
  }
  async function deletePrompt(id) {
    const p = S.flatItems.find((x) => x.id === id) || S.list.find((x) => x.id === id); if (!p) return;
    if (S.cur && S.cur.id === id) await flushSave();
    const r = await call("delete_prompt", id);
    if (!r || !r.ok) return toast("删除失败", { type: "error" });
    const wasCur = S.cur && S.cur.id === id;
    if (wasCur) S.cur = null;
    await refreshList();
    if (!S.cur) { if (S.flatItems.length) openPrompt(S.flatItems[Math.min(S.cursor, S.flatItems.length - 1)].id); else showEmptyEditor(); }
    toast(r.hidden_builtin ? `已隐藏内置「${p.name}」` : `已删除「${p.name}」`, { action: "撤销", onAction: async () => {
      const rr = await call("restore_prompt", r.prompt, r.index);
      if (rr && rr.ok) { await refreshList(); await openPrompt(rr.prompt.id); toast("已恢复", { ms: 1400 }); }
      else toast("恢复失败", { type: "error" });
    } });
  }
  async function duplicatePrompt(id) {
    await flushSave();
    const r = await call("duplicate_prompt", id);
    if (!r || !r.ok) return toast("复制失败", { type: "error" });
    S.query = ""; $("#search").value = "";
    await refreshList(); await openPrompt(r.prompt.id);
    toast(`已创建「${r.prompt.name}」`);
  }
  async function copyBuiltin(id) {
    await flushSave();
    const r = await call("copy_builtin", id);
    if (!r || !r.ok) return toast("复制失败", { type: "error" });
    await refreshList(); await openPrompt(r.prompt.id);
    toast(`已复制「${r.prompt.name}」，可自由编辑`);
  }
  async function newPrompt() {
    await flushSave();
    const p = await call("create_prompt", "", null, S.activeRole || "", "");
    if (!p) return;
    S.query = ""; $("#search").value = "";
    if (S.activeRole) S.expanded[S.activeRole] = true;
    if (S.activeRole) S.expanded[S.activeRole] = true;
    await refreshList(); await openPrompt(p.id);
    title.focus(); title.select();
  }
  async function newRole() {
    const name = prompt("新角色名称", "我的角色");
    if (!name) return;
    const r = await call("create_role", name.trim());
    if (r && r.ok) { S.expanded[r.role.id] = true; S.activeRole = r.role.id; await refreshList(); toast(`已创建角色「${r.role.name}」`); }
  }
  async function addCategory(roleId) {
    const name = prompt("新分类名称", "新分类");
    if (!name) return;
    const r = await call("create_category", roleId, name.trim());
    if (r && r.ok) { S.expanded[roleId] = true; S.expanded[r.category.id] = true; S.activeCat = r.category.id; S.activeRole = roleId; await refreshList(); toast(`已创建分类「${r.category.name}」`); }
  }
  async function renameRole(id) {
    const role = (S.tree.roles || []).find((r) => r.id === id); if (!role) return;
    const name = prompt("重命名角色", role.name); if (!name || name === role.name) return;
    const r = await call("rename_role", id, name.trim());
    if (r && r.ok) { await refreshList(); toast("已重命名"); } else toast((r && r.error) || "无法重命名", { type: "warn" });
  }
  async function deleteRole(id) {
    if (!(await confirmDialog({ title: "删除角色？", message: "其下提示词将移到「我的提示 › 未分类」。", ok: "删除", danger: true }))) return;
    const r = await call("delete_role", id);
    if (r && r.ok) { await refreshList(); toast(`已删除，移动 ${r.moved || 0} 个提示词`); } else toast((r && r.error) || "无法删除", { type: "error" });
  }
  let _roleSysId = "";
  async function openRoleSysPrompt(id) {
    const r = await call("get_role_system_prompt", id);
    if (!r || !r.ok) return toast((r && r.error) || "无法打开", { type: "error" });
    _roleSysId = id;
    const title = $("#roleSysTitle");
    if (title) title.textContent = `系统提示 · ${r.name || ""}`;
    const ed = $("#roleSysEditor"); if (ed) ed.value = r.system_prompt || "";
    openModal("roleSysOverlay", "#roleSysSave");
    setTimeout(() => ed && ed.focus(), 30);
  }
  $("#roleSysSave")?.addEventListener("click", async () => {
    if (!_roleSysId) return;
    const text = ($("#roleSysEditor")?.value) || "";
    const r = await call("set_role_system_prompt", _roleSysId, text);
    if (r && r.ok) {
      toast("已保存角色系统提示");
      closeModal("roleSysOverlay");
      await refreshList();
      // refresh chip / preview if current prompt in this role
      if (S.cur && S.cur.role_id === _roleSysId) { runAnalyze.flush(); updateRoleSysUI(); }
    } else toast((r && r.error) || "保存失败", { type: "error" });
  });
  async function renameCategory(id) {
    let cat = null;
    (S.tree.roles || []).forEach((r) => (r.categories || []).forEach((c) => { if (c.id === id) cat = c; }));
    if (!cat) return;
    const name = prompt("重命名分类", cat.name); if (!name || name === cat.name) return;
    const r = await call("rename_category", id, name.trim());
    if (r && r.ok) { await refreshList(); toast("已重命名"); } else toast((r && r.error) || "无法重命名", { type: "warn" });
  }
  async function deleteCategory(id) {
    if (!(await confirmDialog({ title: "删除分类？", message: "其下提示词将移到「我的提示 › 未分类」。", ok: "删除", danger: true }))) return;
    const r = await call("delete_category", id);
    if (r && r.ok) { await refreshList(); toast(`已删除，移动 ${r.moved || 0} 个提示词`); } else toast((r && r.error) || "无法删除", { type: "error" });
  }
  function clearSearch() { $("#search").value = ""; S.query = ""; refreshList(); $("#search").focus(); }
  $("#newBtn").onclick = newPrompt;
  $("#newRoleBtn") && ($("#newRoleBtn").onclick = newRole);
  $("#searchClear").onclick = clearSearch;
  $("#search").addEventListener("input", debounce((e) => { S.query = e.target.value.trim(); S.cursor = 0; refreshList(); }, 100));
  $("#search").addEventListener("keydown", (e) => {
    if (e.key === "Escape" && e.target.value) { e.preventDefault(); e.stopPropagation(); clearSearch(); }
    else if (e.key === "ArrowDown" || e.key === "Enter") {
      if (!S.flatItems.length) return; e.preventDefault();
      S.cursor = 0; renderList(); $("#list").focus(); openPrompt(S.flatItems[0].id);
    }
  });

  // ---------------------------------------------------------------- editor
  const editor = $("#editor"), gutter = $("#gutter"), title = $("#titleInput");
  function syncTitleWidth() {
    /* 2.12.4: measure real pixel width (CJK ≫ 1ch) so titles like「博客文章写作」do not clip. */
    if (!title) return;
    const raw = (title.value || title.placeholder || "未命名");
    const cs = getComputedStyle(title);
    const canvas = syncTitleWidth._c || (syncTitleWidth._c = document.createElement("canvas"));
    const ctx = canvas.getContext("2d");
    ctx.font = [cs.fontStyle, cs.fontWeight, cs.fontSize, cs.fontFamily].filter(Boolean).join(" ");
    const textW = ctx.measureText(raw).width;
    const pad = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0)
      + (parseFloat(cs.borderLeftWidth) || 0) + (parseFloat(cs.borderRightWidth) || 0);
    const caretPad = 10; // caret + slight breathing room
    const minText = Math.max(ctx.measureText(title.placeholder || "未命名").width, ctx.measureText("未命名").width);
    let w = Math.ceil(Math.max(textW, minText) + pad + caretPad);
    w = Math.max(w, 48);
    const left = title.closest(".editor-head-left") || title.parentElement;
    const head = title.closest(".editor-head");
    if (left && head) {
      /* Cap against head's 58% budget — NOT left.clientWidth (that freezes growth). */
      const save = left.querySelector(".save-state");
      const gap = 6;
      const saveW = save ? save.offsetWidth + gap : 0;
      const copyBtn = left.querySelector("#copyBuiltinBtn");
      const extraW = (copyBtn && !copyBtn.classList.contains("hidden")) ? (copyBtn.offsetWidth + gap) : 0;
      const maxLeft = Math.floor(head.clientWidth * 0.58);
      const avail = Math.max(48, maxLeft - saveW - extraW);
      if (avail > 24) w = Math.min(w, avail);
    }
    title.style.width = w + "px";
    const needsEllipsis = textW + pad + caretPad > w + 0.5;
    title.style.overflow = "hidden";
    title.style.textOverflow = needsEllipsis ? "ellipsis" : "clip";
  }


  async function openPrompt(id) {
    if (S.cur && S.cur.id === id) return;
    await flushSave();
    const p = await call("get_prompt", id);
    if (!p) { toast("提示词不存在", { type: "error" }); return refreshList(); }
    S.cur = {
      id: p.id, name: p.name, body: p.body,
      test_values: p.test_values || {}, last_values: p.last_values || {},
      tags: p.tags || [], keywords: p.keywords || [], summary: p.summary || "",
      favorite: !!p.favorite, pinned: !!p.pinned,
      builtin: !!p.builtin, system: !!p.system,
      role_id: p.role_id || "", category_id: p.category_id || "",
      archived: !!p.archived, last_ai_run: p.last_ai_run || null,
      cases: Array.isArray(p.cases) ? p.cases : [],
    };
    if (p.role_id) { S.activeRole = p.role_id; S.expanded[p.role_id] = true; }
    if (p.role_id) { S.activeRole = p.role_id; S.expanded[p.role_id] = true; }
    const hasTest = Object.keys(S.cur.test_values).length > 0;
    S.values = { ...(hasTest ? S.cur.test_values : S.cur.last_values) }; S.valuesDirty = false; S.varSig = "";
    S.fromLast = !hasTest && Object.keys(S.cur.last_values).length > 0;
    S.focusFormOnRender = S.tab === "form" && document.activeElement !== $("#list");
    title.value = p.name; syncTitleWidth(); editor.value = p.body; editor.scrollTop = 0;
    // builtins: read-only body/name unless user clicks 复制后编辑
    editor.readOnly = !!p.builtin; title.readOnly = !!p.builtin;
    const cbb = $("#copyBuiltinBtn"); if (cbb) cbb.classList.toggle("hidden", !p.builtin);
    setEditorEnabled(true); setSaveState(p.builtin ? "" : "saved");
    if (p.builtin) { const st = $("#saveState"); st.className = "save-state"; st.textContent = "内置 · 只读"; }
    syncFlagsUI(); renderTagsUI(); renderKwUI();
    S.mmResults = (p.last_ai_run && p.last_ai_run.results) ? p.last_ai_run.results.map((x) => ({ ...x })) : null;
    S.mmAt = (p.last_ai_run && p.last_ai_run.at) || "";
    S.mmRendered = (p.last_ai_run && p.last_ai_run.rendered_preview) || "";
    renderList(); updateCrumb(); updateGutter(); updateEditorHL(); updateCursor(); runAnalyze.flush(); syncMdToolbar(); updateMdLive();
    setValuesState();
  }
  function showEmptyEditor() {
    S.cur = null; title.value = ""; syncTitleWidth(); editor.value = ""; setEditorEnabled(false);
    editor.readOnly = false; title.readOnly = false;
    const cbb = $("#copyBuiltinBtn"); if (cbb) cbb.classList.add("hidden");
    const crumb = $("#crumb"); if (crumb) crumb.hidden = true;
    const mr = $("#metaRow"); if (mr) mr.hidden = true;
    const tr = $("#tagsRow"); if (tr) tr.hidden = true;
    S.analysis = null; S.varSig = ""; updateGutter(); updateEditorHL(); renderSide(); setSaveState(""); syncMdToolbar(); updateMdLive();
    S.mmResults = null;
  }
  function renderEditorEmpty() {
    const k = (keys, label) => `<span>${keys.map((x) => `<kbd>${x}</kbd>`).join(" ")}</span><span>${label}</span>`;
    $("#editorEmpty").innerHTML = `<div class="empty welcome"><div class="empty-ico">${I("edit", 22)}</div>
      <div class="empty-title">${S.list.length ? "选择左侧的提示词开始编辑" : "创建你的第一个提示词"}</div>
      <div>提示词里需要每次替换的地方写成 <code>{{变量}}</code>，右侧会自动生成表单。</div>
      <div class="empty-actions"><button class="btn primary sm" data-ee="new">${I("plus", 14)}新建提示词</button><button class="btn secondary sm" data-ee="onb">${I("sparkles", 14)}查看新手引导</button></div>
      <div class="keys">${k(["Ctrl", "N"], "新建")}${k(["/", "/"], "在任意输入框唤醒浮框")}${k(["F1"], "快捷键与语法")}</div></div>`;
  }
  $("#editorEmpty").addEventListener("click", (e) => {
    const a = e.target.closest("[data-ee]")?.dataset.ee;
    if (a === "new") newPrompt(); else if (a === "onb") openOnboarding();
  });
  function setEditorEnabled(on) {
    editor.disabled = !on; title.disabled = !on;
    ["#copyBtn", "#copyResultMenuBtn", "#saveValuesBtn", "#resetValuesBtn", "#insertBtn", "#syntaxBtn", "#revBtn", "#archBtn", "#favBtn", "#pinBtn", "#tagsInput", "#editorMoreBtn"].forEach((s) => { const el = $(s); if (el) el.disabled = !on; });
    const mr = $("#metaRow"); if (mr) mr.hidden = !on;
    const tr = $("#tagsRow"); if (tr) tr.hidden = !on;
    $("#editorEmpty").classList.toggle("hidden", on);
    if (!on) renderEditorEmpty();
    syncMdToolbar();
    if (on) updateMdLive(); else { const pane = $("#mdLivePreview"); if (pane) pane.innerHTML = ""; }
  }
  function setSaveState(st) {
    const el = $("#saveState");
    el.className = "save-state" + (st === "dirty" ? " dirty" : st === "error" ? " error" : "");
    el.innerHTML = st === "dirty" ? "● 未保存" : st === "saving" ? "保存中…" : st === "saved" ? `${I("check", 12)}已保存` : st === "error" ? `${I("alert", 12)}保存失败` : "";
  }
  const autoSave = debounce(() => doSave(), 500);
  async function doSave() {
    if (!S.cur || !S.dirty) return;
    const id = S.cur.id, body = editor.value, name = title.value.trim() || S.cur.name;
    S.dirty = false; setSaveState("saving");
    const r = await call("save_prompt", id, { name, body });
    if (r && r.ok) {
      if (r.prompt && r.prompt._copied_from_builtin) {
        toast("内置提示已复制为可编辑副本");
        await refreshList(); await openPrompt(r.prompt.id); return;
      }
      if (S.cur && S.cur.id === id) { S.cur.body = body; S.cur.name = r.prompt.name; if (!S.dirty) setSaveState("saved"); }
      refreshList();
    } else { S.dirty = true; setSaveState("error"); }
  }
  async function flushSave() { autoSave.cancel(); await doSave(); }
  function markDirty() { if (!S.cur) return; S.dirty = true; setSaveState("dirty"); autoSave(); }
  // the host calls this before quitting / restarting so no keystroke is lost
  window.__pbFlush = async () => { await flushSave(); return true; };

  editor.addEventListener("input", () => { markDirty(); scheduleGutter(); scheduleEditorHL(); runAnalyze(); scheduleMdLive(); });
  title.addEventListener("input", () => { markDirty(); syncTitleWidth(); });
  title.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); editor.focus(); } });
  const editorHL = $("#editorHL");
  editor.addEventListener("scroll", () => {
    gutter.scrollTop = editor.scrollTop;
    if (editorHL) { editorHL.scrollTop = editor.scrollTop; editorHL.scrollLeft = editor.scrollLeft; }
  });
  ["keyup", "click", "select"].forEach((ev) => editor.addEventListener(ev, updateCursor));
  editor.addEventListener("keydown", (e) => {
    if (e.key === "Tab" && !e.ctrlKey && !e.altKey && !e.shiftKey) { e.preventDefault(); document.execCommand("insertText", false, "  "); }
  });

  function updateCursor() {
    const pos = editor.selectionStart, before = editor.value.slice(0, pos);
    const line = before.split("\n").length, col = pos - before.lastIndexOf("\n");
    $("#sbCursor").textContent = `行 ${line}，列 ${col}`;
  }
  // Gutter: line numbers mirror wrapped lines via a hidden measuring element.
  const measure = document.createElement("div");
  measure.style.cssText = "position:absolute;visibility:hidden;left:-9999px;top:0;white-space:pre-wrap;overflow-wrap:anywhere;font-family:var(--mono);font-size:12.5px;line-height:1.6;";
  document.body.appendChild(measure);
  const rowCache = new Map(); let rowCacheWidth = 0;
  function updateGutter() {
    const lines = editor.value.split("\n");
    const marks = {};
    (S.analysis?.issues || []).forEach((i) => { if (i.line && i.level !== "info") marks[i.line] = marks[i.line] === "err" ? "err" : (i.level === "error" ? "err" : "warn"); });
    const cs = getComputedStyle(editor);
    const width = Math.round(editor.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight));
    if (width !== rowCacheWidth) { rowCache.clear(); rowCacheWidth = width; measure.style.width = width + "px"; }
    if (rowCache.size > 5000) rowCache.clear();
    const lh = 12.5 * 1.6;
    const todo = [...new Set(lines.filter((l) => l.length > 20 && !rowCache.has(l)))];
    if (todo.length) {
      measure.innerHTML = todo.map((l) => `<div>${esc(l)}</div>`).join("");
      const kids = measure.children;
      for (let k = 0; k < todo.length; k++) rowCache.set(todo[k], Math.max(1, Math.round(kids[k].offsetHeight / lh)));
      measure.innerHTML = "";
    }
    const parts = new Array(lines.length);
    for (let idx = 0; idx < lines.length; idx++) {
      const l = lines[idx], rows = l.length > 20 ? rowCache.get(l) || 1 : 1;
      const n = idx + 1, cls = marks[n] ? ` class="${marks[n]}"` : "";
      parts[idx] = `<span${cls}>${n}</span>` + "\n".repeat(rows);
    }
    gutter.innerHTML = parts.join("");
    gutter.scrollTop = editor.scrollTop;
  }
  let gutterRaf = 0;
  function scheduleGutter() { if (!gutterRaf) gutterRaf = requestAnimationFrame(() => { gutterRaf = 0; updateGutter(); updateEditorHL(); }); }
  window.addEventListener("resize", debounce(() => { updateGutter(); syncTitleWidth(); if (!$("#insertMenu")?.classList.contains("hidden")) placeInsertMenu(); }, 100));


  // 2.12.1: lightweight {{var}} highlight mirror under transparent textarea
  const VAR_HL_RE = /\\\{\{|(\{\{[^{}]*\}\})/g;
  function buildEditorHL(text) {
    if (!text) return "";
    let out = "", last = 0, m;
    VAR_HL_RE.lastIndex = 0;
    while ((m = VAR_HL_RE.exec(text))) {
      out += esc(text.slice(last, m.index));
      if (m[1]) {
        const tok = m[1];
        const opt = tok.includes("|") ? " opt" : "";
        out += `<mark class="v${opt}">${esc(tok)}</mark>`;
      } else {
        out += esc(m[0]); // escaped \{{ — plain
      }
      last = m.index + m[0].length;
    }
    out += esc(text.slice(last));
    // trailing newline: pre collapses final \n; keep scroll parity with textarea
    if (text.endsWith("\n")) out += "\n";
    return out;
  }
  function updateEditorHL() {
    if (!editorHL) return;
    const on = !editor.disabled && S.cur;
    if (!on) { editorHL.innerHTML = ""; return; }
    editorHL.innerHTML = buildEditorHL(editor.value);
    editorHL.scrollTop = editor.scrollTop;
    editorHL.scrollLeft = editor.scrollLeft;
  }
  let hlRaf = 0;
  function scheduleEditorHL() {
    if (!hlRaf) hlRaf = requestAnimationFrame(() => { hlRaf = 0; updateEditorHL(); });
  }

  function jumpTo(line, col) {
    if (!line) return;
    const lines = editor.value.split("\n");
    let pos = 0; for (let i = 0; i < line - 1 && i < lines.length; i++) pos += lines[i].length + 1;
    pos += Math.max(0, (col || 1) - 1);
    editor.focus(); editor.setSelectionRange(pos, pos);
    editor.scrollTop = Math.max(0, (line - 4) * 12.5 * 1.6);
    updateCursor();
  }

  // ---------------------------------------------------------------- insert-variable menu
  // Each snippet: `name` is selected after inserting so it can be typed over right away;
  // if text is selected and looks like a name, it becomes the variable name.
  const SNIPPETS = [
    { icon: "textCursor", title: "单行文本", code: "{{名称}}", desc: "必填，生成单行输入框", name: "名称", make: (n) => `{{${n}}}` },
    { icon: "textDefault", title: "带默认值（可选填）", code: "{{名称|默认值}}", desc: "留空时用默认值；{{名称|}} 表示默认为空", name: "名称", make: (n) => `{{${n}|默认值}}` },
    { icon: "textarea", title: "多行文本", code: "{{名称:多行}}", desc: "适合粘贴长文本、代码、资料", name: "名称", make: (n) => `{{${n}:多行}}` },
    { icon: "num", title: "数字", code: "{{字数:数字|300}}", desc: "校验数字，带 −/＋ 按钮", name: "字数", make: (n) => `{{${n}:数字|300}}` },
    { icon: "select", title: "下拉选择", code: "{{语气:正式/轻松/幽默|正式}}", desc: "选项用 / 分隔，| 后是默认选项", name: "语气", make: (n) => `{{${n}:正式/轻松/幽默|正式}}` },
    { icon: "radio", title: "单选", code: "{{优先级:单选:高/中/低|中}}", desc: "单选按钮组，选项用 / 分隔", name: "优先级", make: (n) => `{{${n}:单选:高/中/低|中}}` },
    { icon: "checkSquare", title: "多选", code: "{{标签:多选:A/B/C}}", desc: "多选框，渲染时用顿号连接", name: "标签", make: (n) => `{{${n}:多选:A/B/C}}` },
    { icon: "braces", title: "原样输出 {{", code: "\\{{", desc: "写字面量花括号，不当作变量", raw: "\\{{" },
  ];
  const NAME_OK = /^[^\s{}|:：\\/]{1,24}$/;
  function renderInsertMenu() {
    const vars = (S.analysis?.variables || []).slice(0, 12);
    const menu = $("#insertMenu");
    menu.innerHTML = `<div class="menu-label">变量类型</div>` +
      SNIPPETS.map((s, i) => {
        const ic = I(s.icon, 15) || I("braces", 15);
        return `<button class="ins" role="menuitem" data-sn="${i}"><span class="ic" data-icon="${esc(s.icon)}" data-size="15">${ic}</span><span class="ins-title">${esc(s.title)}</span><span class="ins-code">${esc(s.code)}</span><span class="ins-desc">${esc(s.desc)}</span></button>`;
      }).join("") +
      (vars.length ? `<div class="menu-sep"></div><div class="menu-label">再次插入已有变量</div>` +
        vars.map((v) => `<button role="menuitem" data-var-name="${esc(v.name)}"><span class="ic" data-icon="braces" data-size="14">${I("braces", 14)}</span><span class="ins-var">{{${esc(v.name)}}}</span></button>`).join("") : "") +
      `<div class="menu-foot">选中文字再插入，会把它作为变量名 · <kbd>Ctrl</kbd>+<kbd>I</kbd></div>`;
    if (window.PBIcons) window.PBIcons.fill(menu);
  }
  let menuSel = null;   // editor selection remembered while the menu has focus
  function placeInsertMenu() {
    /* 2.12.4: fixed placement so #editorPanel overflow cannot clip the full type list */
    const btn = $("#insertBtn"), menu = $("#insertMenu");
    if (!btn || !menu) return;
    const r = btn.getBoundingClientRect();
    const mw = Math.min(340, window.innerWidth - 16);
    let left = Math.min(r.right - mw, window.innerWidth - mw - 8);
    left = Math.max(8, left);
    menu.style.position = "fixed";
    menu.style.zIndex = "120";
    menu.style.width = mw + "px";
    menu.style.left = left + "px";
    menu.style.right = "auto";
    // measure after visible
    const approxH = Math.min(0.62 * window.innerHeight, menu.scrollHeight || 420);
    const spaceBelow = window.innerHeight - r.bottom - 10;
    const spaceAbove = r.top - 10;
    const flip = spaceBelow < Math.min(approxH, 260) && spaceAbove > spaceBelow;
    const maxH = Math.max(160, Math.min(0.62 * window.innerHeight, flip ? spaceAbove : spaceBelow));
    menu.style.maxHeight = maxH + "px";
    if (flip) {
      menu.style.top = "auto";
      menu.style.bottom = (window.innerHeight - r.top + 6) + "px";
    } else {
      menu.style.top = (r.bottom + 6) + "px";
      menu.style.bottom = "auto";
    }
  }
  function clearInsertMenuPos() {
    const menu = $("#insertMenu"); if (!menu) return;
    menu.style.position = ""; menu.style.zIndex = ""; menu.style.width = "";
    menu.style.left = ""; menu.style.right = ""; menu.style.top = "";
    menu.style.bottom = ""; menu.style.maxHeight = "";
  }
  function openInsertMenu() {
    if (editor.disabled) return;
    menuSel = [editor.selectionStart, editor.selectionEnd];
    renderInsertMenu();
    const menu = $("#insertMenu");
    menu.classList.remove("hidden"); $("#insertBtn").setAttribute("aria-expanded", "true");
    placeInsertMenu();
    // second pass after layout for accurate scrollHeight / flip
    requestAnimationFrame(() => { placeInsertMenu(); menu.querySelector("button")?.focus(); });
  }
  function closeInsertMenu(refocus) {
    if ($("#insertMenu").classList.contains("hidden")) return;
    $("#insertMenu").classList.add("hidden"); $("#insertBtn").setAttribute("aria-expanded", "false");
    clearInsertMenuPos();
    if (refocus) { editor.focus(); if (menuSel) editor.setSelectionRange(menuSel[0], menuSel[1]); }
  }
  function insertSnippet(sn, varName) {
    const [a, b] = menuSel || [editor.selectionStart, editor.selectionEnd];
    closeInsertMenu(false);
    editor.focus();
    const selected = editor.value.slice(a, b).trim();
    const useSel = !varName && !(sn && sn.raw) && a !== b && NAME_OK.test(selected);
    const name = useSel ? selected : sn && sn.name;
    const text = varName ? `{{${varName}}}` : sn.raw ? sn.raw : sn.make(name);
    // a name-like selection becomes the variable name; any other selection is kept and we insert after it
    const at = useSel ? a : b;
    editor.setSelectionRange(at, useSel ? b : b);
    document.execCommand("insertText", false, text);
    if (!varName && !sn.raw && !useSel) editor.setSelectionRange(at + 2, at + 2 + name.length);
    updateCursor();
  }
  $("#insertBtn").onclick = (e) => { e.stopPropagation(); $("#insertMenu").classList.contains("hidden") ? openInsertMenu() : closeInsertMenu(true); };
  $("#insertBtn").addEventListener("mousedown", () => { if (document.activeElement === editor) menuSel = [editor.selectionStart, editor.selectionEnd]; });
  $("#insertMenu").addEventListener("click", (e) => {
    e.stopPropagation();
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.sn != null) insertSnippet(SNIPPETS[+b.dataset.sn]);
    else if (b.dataset.varName) insertSnippet(null, b.dataset.varName);
  });
  function menuKeys(menu, e, onEsc) {
    const items = $$("button", menu); const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); const n = items.length; items[(i + (e.key === "ArrowDown" ? 1 : -1) + n) % n].focus(); }
    else if (e.key === "Home") { e.preventDefault(); items[0].focus(); }
    else if (e.key === "End") { e.preventDefault(); items[items.length - 1].focus(); }
    else if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); e.stopPropagation(); onEsc(); }
  }
  $("#insertMenu").addEventListener("keydown", (e) => menuKeys($("#insertMenu"), e, () => closeInsertMenu(true)));
  $("#syntaxBtn").onclick = () => openHelp("syntax");

  // ---------------------------------------------------------------- 2.12.7 Markdown toolbar + live source preview
  const MD_SPLIT_KEY = "pb.editor.mdSplit";
  const MD_PREVIEW_KEY = "pb.editor.mdPreview";
  function mdToolbarEnabled() {
    return !!(S.cur && !editor.disabled && !editor.readOnly);
  }
  function syncMdToolbar() {
    const on = mdToolbarEnabled();
    $$("#mdToolbar .md-tool, #mdPreviewToggle").forEach((b) => { b.disabled = !S.cur || editor.disabled || (b.id !== "mdPreviewToggle" && editor.readOnly); });
    // preview toggle allowed for builtins (read-only source still previewable)
    const tog = $("#mdPreviewToggle");
    if (tog) tog.disabled = !S.cur || editor.disabled;
  }
  function updateMdLive() {
    const pane = $("#mdLivePreview");
    if (!pane) return;
    if (!S.cur) { pane.innerHTML = ""; return; }
    const src = editor.value || "";
    try {
      pane.innerHTML = (window.MiniMD && window.MiniMD.render) ? window.MiniMD.render(src) : esc(src).replace(/\n/g, "<br>");
    } catch (err) {
      pane.textContent = src;
    }
  }
  const scheduleMdLive = debounce(updateMdLive, 140);
  function applyMdSplitHeight(pct) {
    const stack = $("#editorStack");
    if (!stack) return;
    const n = Math.max(18, Math.min(65, Number(pct) || 38));
    stack.style.setProperty("--md-preview-h", n + "%");
    try { localStorage.setItem(MD_SPLIT_KEY, String(n)); } catch (_) {}
  }
  function loadMdSplit() {
    let n = 38;
    try { n = parseFloat(localStorage.getItem(MD_SPLIT_KEY)) || 38; } catch (_) {}
    applyMdSplitHeight(n);
  }
  function setMdPreviewVisible(show) {
    const stack = $("#editorStack");
    const tog = $("#mdPreviewToggle");
    if (!stack) return;
    stack.classList.toggle("md-preview-collapsed", !show);
    if (tog) {
      tog.setAttribute("aria-pressed", show ? "true" : "false");
      const ic = tog.querySelector(".ic") || tog.querySelector("i");
      tog.innerHTML = `${I(show ? "eye" : "eyeOff", 14)}预览`;
      if (window.PBIcons) window.PBIcons.fill(tog);
    }
    try { localStorage.setItem(MD_PREVIEW_KEY, show ? "1" : "0"); } catch (_) {}
    if (show) updateMdLive();
  }
  function loadMdPreviewPref() {
    let show = true;
    try { show = localStorage.getItem(MD_PREVIEW_KEY) !== "0"; } catch (_) {}
    setMdPreviewVisible(show);
  }
  function mdReplaceSelection(text, selectInnerStart, selectInnerLen) {
    if (!S.cur || editor.disabled || editor.readOnly) return;
    const a = editor.selectionStart, b = editor.selectionEnd;
    editor.focus();
    editor.setSelectionRange(a, b);
    document.execCommand("insertText", false, text);
    if (selectInnerStart != null) {
      const s = a + selectInnerStart;
      editor.setSelectionRange(s, s + (selectInnerLen || 0));
    }
    markDirty(); scheduleGutter(); scheduleEditorHL(); runAnalyze(); updateMdLive(); updateCursor();
  }
  function mdWrap(before, after, placeholder) {
    if (!S.cur || editor.disabled || editor.readOnly) return;
    const a = editor.selectionStart, b = editor.selectionEnd;
    const sel = editor.value.slice(a, b);
    const inner = sel || placeholder || "";
    mdReplaceSelection(before + inner + after, before.length, inner.length);
  }
  function mdPrefixLines(prefixFn) {
    if (!S.cur || editor.disabled || editor.readOnly) return;
    const a = editor.selectionStart, b = editor.selectionEnd;
    const val = editor.value;
    const lineStart = val.lastIndexOf("\n", a - 1) + 1;
    const lineEnd = b === a ? (val.indexOf("\n", b) === -1 ? val.length : val.indexOf("\n", b)) : b;
    const block = val.slice(lineStart, Math.max(lineEnd, a));
    const lines = block.split("\n");
    const next = lines.map((ln, i) => prefixFn(ln, i)).join("\n");
    editor.focus();
    editor.setSelectionRange(lineStart, lineStart + block.length);
    document.execCommand("insertText", false, next);
    markDirty(); scheduleGutter(); scheduleEditorHL(); runAnalyze(); updateMdLive(); updateCursor();
  }
  function applyMdAction(act) {
    if (act === "h2") {
      mdPrefixLines((ln) => {
        const t = ln.replace(/^#{1,6}\s+/, "");
        return "## " + (t || "标题");
      });
      return;
    }
    if (act === "bold") return mdWrap("**", "**", "粗体");
    if (act === "italic") return mdWrap("*", "*", "斜体");
    if (act === "strike") return mdWrap("~~", "~~", "删除线");
    if (act === "code") return mdWrap("`", "`", "代码");
    if (act === "codeblock") return mdWrap("```\n", "\n```", "code");
    if (act === "ul") return mdPrefixLines((ln) => (/^\s*[-*+]\s/.test(ln) ? ln : "- " + (ln || "列表项")));
    if (act === "ol") return mdPrefixLines((ln, i) => (/^\s*\d+\.\s/.test(ln) ? ln : `${i + 1}. ` + (ln || "列表项")));
    if (act === "quote") return mdPrefixLines((ln) => (/^\s*>\s/.test(ln) ? ln : "> " + (ln || "引用")));
    if (act === "link") {
      const a = editor.selectionStart, b = editor.selectionEnd;
      const sel = editor.value.slice(a, b) || "链接文字";
      mdReplaceSelection(`[${sel}](https://)`, 1, sel.length);
      return;
    }
    if (act === "table") {
      const tbl = "| 列1 | 列2 |\n| --- | --- |\n|  |  |\n|  |  |";
      mdReplaceSelection(tbl, 0, 0);
      return;
    }
    if (act === "hr") return mdReplaceSelection("\n---\n", 1, 3);
  }
  const mdTb = $("#mdToolbar");
  if (mdTb) {
    mdTb.addEventListener("mousedown", (e) => {
      const btn = e.target.closest(".md-tool");
      if (btn && document.activeElement === editor) {
        // keep selection
        e.preventDefault();
      }
    });
    mdTb.addEventListener("click", (e) => {
      const btn = e.target.closest(".md-tool");
      if (btn && btn.dataset.md) applyMdAction(btn.dataset.md);
    });
  }
  $("#mdPreviewToggle")?.addEventListener("click", () => {
    const stack = $("#editorStack");
    const show = stack && stack.classList.contains("md-preview-collapsed");
    setMdPreviewVisible(!!show);
  });
  // prevent lower pane from stealing focus awkwardly
  $("#mdLivePreview")?.addEventListener("mousedown", (e) => { e.preventDefault(); });
  // horizontal splitter
  (function wireMdSplit() {
    const handle = $("#splitMd");
    const stack = $("#editorStack");
    if (!handle || !stack) return;
    let dragging = false;
    handle.addEventListener("mousedown", (e) => {
      if (stack.classList.contains("md-preview-collapsed")) return;
      dragging = true; handle.classList.add("dragging");
      e.preventDefault();
      const onMove = (ev) => {
        if (!dragging) return;
        const rect = stack.getBoundingClientRect();
        const fromBottom = rect.bottom - ev.clientY;
        const pct = (fromBottom / rect.height) * 100;
        applyMdSplitHeight(pct);
      };
      const onUp = () => {
        dragging = false; handle.classList.remove("dragging");
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    });
    handle.addEventListener("dblclick", () => applyMdSplitHeight(38));
  })();
  loadMdSplit();
  loadMdPreviewPref();


  // ---------------------------------------------------------------- analysis
  let analyzeSeq = 0;
  const runAnalyze = debounce(async () => {
    if (!S.cur) return;
    const seq = ++analyzeSeq, id = S.cur.id;
    const r = await call("analyze", editor.value, S.values);
    if (!r || seq !== analyzeSeq || !S.cur || S.cur.id !== id) return;
    S.analysis = r; renderSide(); scheduleGutter();
  }, 120);

  function varSignature(vars) { return JSON.stringify(vars.map((v) => [v.name, v.control, v.options, v.default, v.required])); }

  function renderSide() {
    const a = S.analysis;
    const vars = a?.variables || [];
    $("#sbVars").textContent = vars.length;
    $("#sbReq").textContent = vars.filter((v) => v.required).length;
    $("#sbChars").textContent = a ? a.stats.template.chars : 0;
    $("#sbLines").textContent = a ? a.stats.template.lines : 0;
    $("#badgeForm").textContent = vars.length;
    const bd = $("#badgeDebug"), c = a?.issue_counts || { error: 0, warn: 0, info: 0 };
    bd.textContent = c.error + c.warn || c.info || 0;
    bd.className = "badge" + (c.error ? " err" : c.warn ? " warn" : "");
    const sig = varSignature(vars);
    if (sig !== S.varSig || !S.cur) { S.varSig = sig; renderForm(); } else updateFormValidity();
    renderPreview(); renderDebug();
  }

  // ---------------------------------------------------------------- form tab
  function renderForm() {
    const el = $("#tab-form"), vars = S.analysis?.variables || [];
    if (!S.cur) { el.innerHTML = emptyState("list", "未选择提示词", "选择或新建一个提示词后，这里会显示它的变量表单。"); return; }
    if (!vars.length) {
      el.innerHTML = emptyState("braces", "这个提示词还没有变量",
        "把正文中需要每次替换的地方写成 <code>{{变量}}</code>，这里会自动生成表单。",
        `<button class="btn secondary sm" data-act="insert">${I("braces", 14)}插入变量</button><button class="btn ghost sm" data-act="syntax">语法说明</button>`)
        + renderCasesPanel();
      bindCasesPanel(el);
      return;
    }
    const banner = S.fromLast ? `<div class="form-note">${I("undo", 14)}<span>已填入上次使用的值</span><span class="spacer"></span><a href="#" data-act="clear-last">清空</a></div>` : "";
    el.innerHTML = banner + vars.map((v, i) => {
      const val = S.values[v.name] ?? "";
      const ph = v.default != null ? `默认：${v.default === "" ? "（空）" : v.default}` : `请输入${v.name}`;
      const fid = `f-${i}`;
      let ctl;
      if (v.control === "select") {
        const first = v.default != null ? `<option value="">（默认：${esc(v.default || "空")}）</option>` : `<option value="">请选择…</option>`;
        ctl = `<select class="select" id="${fid}" data-var="${i}">${first}${v.options.map((o) => `<option${o === val ? " selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
      } else if (v.control === "radio") {
        const cur = val || (v.default != null ? v.default : "");
        ctl = `<div class="choice-group" role="radiogroup" aria-labelledby="${fid}-lab" id="${fid}" data-var="${i}" data-choice="radio">` +
          (v.options || []).map((o, j) => `<label class="choice"><input type="radio" name="r-${i}" value="${esc(o)}" data-var="${i}"${o === cur ? " checked" : ""}>${esc(o)}</label>`).join("") +
          `</div>`;
      } else if (v.control === "multiselect") {
        const sel = new Set(String(val || "").split(/[、,/，]/).map((s) => s.trim()).filter(Boolean));
        ctl = `<div class="choice-group" id="${fid}" data-var="${i}" data-choice="multi">` +
          (v.options || []).map((o) => `<label class="choice"><input type="checkbox" value="${esc(o)}" data-var="${i}"${sel.has(o) ? " checked" : ""}>${esc(o)}</label>`).join("") +
          `</div>`;
      } else if (v.control === "multiline") {
        ctl = `<textarea class="textarea" id="${fid}" rows="4" data-var="${i}" placeholder="${esc(ph)}" spellcheck="false">${esc(val)}</textarea>`;
      } else if (v.control === "number") {
        ctl = `<div class="num-wrap"><input class="input" id="${fid}" data-var="${i}" value="${esc(val)}" placeholder="${esc(ph)}" spellcheck="false" inputmode="decimal" autocomplete="off">
          <button class="num-btn" tabindex="-1" data-step="-1" data-for="${i}" aria-label="减 1">−</button><button class="num-btn" tabindex="-1" data-step="1" data-for="${i}" aria-label="加 1">＋</button></div>`;
      } else {
        ctl = `<input class="input" id="${fid}" data-var="${i}" value="${esc(val)}" placeholder="${esc(ph)}" spellcheck="false" autocomplete="off">`;
      }
      const tags = `<span class="tag ${v.required ? "req" : "opt"}">${v.required ? "必填" : "可选"}</span>` + (v.control !== "text" ? `<span class="tag ctl">${esc(v.control_label)}</span>` : "");
      return `<div class="field"><label class="field-label" id="${fid}-lab" for="${fid}"><span class="name">${esc(v.name)}</span>${tags}</label>${ctl}
        <div class="field-msg" data-msg="${i}" aria-live="polite"></div>
        ${v.count > 1 ? `<div class="field-hint">在正文中出现 ${v.count} 次</div>` : ""}</div>`;
    }).join("") + `<div class="form-keys"><span><kbd>Tab</kbd> 下一项</span><span><kbd>Ctrl</kbd>+<kbd>Enter</kbd> 复制结果</span></div>`
      + renderCasesPanel();
    bindCasesPanel(el);
    updateFormValidity();
    if (S.focusFormOnRender) { S.focusFormOnRender = false; focusFirstField(); }
  }

  function renderCasesPanel() {
    const cases = (S.cur && S.cur.cases) || [];
    const rows = cases.length
      ? cases.map((c) => {
          const nvars = Object.keys(c.values || {}).length;
          const pass = c.last_run && (c.last_run.match === 'pass' || c.last_run.ok === true);
          const badge = c.last_run
            ? (pass ? `<span class="tag ok">通过</span>` : `<span class="tag warn">未匹配</span>`)
            : "";
          return `<div class="case-row" data-case-id="${esc(c.id)}">
            <div class="case-main"><div class="case-name">${esc(c.name || "用例")}${badge}</div>
              <div class="case-meta muted small">${nvars} 个变量${c.expect ? " · 有期望" : ""}${c.notes ? " · " + esc(c.notes) : ""}</div></div>
            <div class="case-acts">
              <button type="button" class="btn ghost sm" data-case-act="fill" title="填入表单">填入</button>
              <button type="button" class="btn ghost sm" data-case-act="run" title="跑测">跑测</button>
              <button type="button" class="btn ghost sm" data-case-act="edit" title="编辑">编辑</button>
              <button type="button" class="btn ghost sm" data-case-act="del" title="删除">${I("trash", 12)}</button>
            </div></div>`;
        }).join("")
      : `<div class="muted small">暂无用例。填好表单后点「保存为用例」。</div>`;
    return `<div class="cases-panel" id="casesPanel">
      <div class="cases-head"><strong>用例 / 黄金样例</strong>
        <span class="spacer"></span>
        <button type="button" class="btn secondary sm" data-case-act="save-current" title="将当前表单值存为用例">保存为用例</button>
      </div>
      <div class="cases-list">${rows}</div>
      <div class="case-run-out hidden" id="caseRunOut"></div>
    </div>`;
  }
  function bindCasesPanel(root) {
    root.querySelectorAll("[data-case-act]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault(); e.stopPropagation();
        const act = btn.dataset.caseAct;
        const row = btn.closest("[data-case-id]");
        const cid = row ? row.dataset.caseId : "";
        handleCaseAct(act, cid);
      });
    });
  }
  let _editCaseId = "";
  async function handleCaseAct(act, cid) {
    if (!S.cur) return;
    if (act === "save-current") {
      if ((S.cur.cases || []).length >= 10) return toast("最多 10 个用例", { type: "warn" });
      _editCaseId = "";
      $("#caseTitle").textContent = "新建用例";
      $("#caseName").value = `用例 ${(S.cur.cases || []).length + 1}`;
      $("#caseExpect").value = "";
      $("#caseNotes").value = "";
      $("#caseValsHint").textContent = `将保存当前表单中 ${Object.keys(S.values).filter((k) => (S.values[k] || "").trim()).length} 个已填变量。`;
      openModal("caseOverlay", "#caseSave");
      return;
    }
    const c = ((S.cur.cases || []).find((x) => x.id === cid)) || null;
    if (act === "fill") {
      if (!c) return;
      S.values = { ...(c.values || {}) };
      S.valuesDirty = true; S.fromLast = false; setValuesState();
      runAnalyze.flush();
      toast(`已填入「${c.name}」`);
      return;
    }
    if (act === "edit") {
      if (!c) return;
      _editCaseId = c.id;
      $("#caseTitle").textContent = "编辑用例";
      $("#caseName").value = c.name || "";
      $("#caseExpect").value = c.expect || "";
      $("#caseNotes").value = c.notes || "";
      $("#caseValsHint").textContent = "保存时用当前表单变量值覆盖本用例的 values。";
      openModal("caseOverlay", "#caseSave");
      return;
    }
    if (act === "del") {
      if (!c) return;
      if (!(await confirmDialog({ title: "删除用例？", message: `删除「${c.name}」不可恢复。`, ok: "删除", danger: true }))) return;
      const r = await call("delete_case", S.cur.id, cid);
      if (r && r.ok) { S.cur.cases = r.cases || []; renderForm(); toast("已删除用例"); }
      else toast((r && r.error) || "删除失败", { type: "error" });
      return;
    }
    if (act === "run") {
      if (!c) return;
      const out = $("#caseRunOut");
      if (out) { out.classList.remove("hidden"); out.innerHTML = `<div class="muted small">跑测中…</div>`; }
      const r = await call("run_case", S.cur.id, cid, applyRoleSysEnabled());
      if (!r || !r.ok) {
        if (out) out.innerHTML = `<div class="issue error">${esc((r && r.error) || "跑测失败")}</div>`;
        return toast((r && r.error) || "跑测失败", { type: "error" });
      }
      if (r.cases) S.cur.cases = r.cases;
      const matchLabel = r.soft_match == null ? "（无期望，仅展示）" : (r.soft_match ? "✓ 软匹配通过" : "✗ 未匹配期望");
      const aiBlock = r.used_ai
        ? `<div class="case-cmp"><div class="k">AI 输出</div><pre>${esc(r.output || "")}</pre></div>`
        : `<div class="muted small">${esc(r.ai_error || "未配置 AI：仅对比渲染结果与期望（可手动核对）")}</div>`;
      if (out) out.innerHTML = `<div class="case-run-head"><strong>${esc(c.name)}</strong> · ${matchLabel}</div>
        <div class="case-cmp"><div class="k">渲染预览</div><pre>${esc((r.rendered || "").slice(0, 2000))}</pre></div>
        ${r.expect ? `<div class="case-cmp"><div class="k">期望</div><pre>${esc(r.expect)}</pre></div>` : ""}
        ${aiBlock}`;
      renderForm();
      // restore run out after re-render
      const out2 = $("#caseRunOut");
      if (out2) { out2.classList.remove("hidden"); out2.innerHTML = out ? out.innerHTML : ""; }
      toast(r.used_ai ? (r.soft_match ? "跑测通过" : "跑测完成（未匹配）") : "已渲染对比");
    }
  }
  $("#caseSave")?.addEventListener("click", async () => {
    if (!S.cur) return;
    const payload = {
      id: _editCaseId || undefined,
      name: ($("#caseName")?.value || "").trim() || "用例",
      values: { ...S.values },
      expect: ($("#caseExpect")?.value || ""),
      notes: ($("#caseNotes")?.value || ""),
    };
    const r = await call("save_case", S.cur.id, payload);
    if (r && r.ok) {
      S.cur.cases = r.cases || [];
      closeModal("caseOverlay");
      renderForm();
      toast(_editCaseId ? "用例已更新" : "用例已保存");
    } else toast((r && r.error) || "保存失败", { type: "error" });
  });

  function readFormValue(i) {
    const v = S.analysis?.variables?.[i]; if (!v) return "";
    if (v.control === "radio") {
      const el = $(`input[type=radio][data-var="${i}"]:checked`, $("#tab-form"));
      return el ? el.value : "";
    }
    if (v.control === "multiselect") {
      return $$(`input[type=checkbox][data-var="${i}"]:checked`, $("#tab-form")).map((x) => x.value).join("、");
    }
    // prefer non-choice control with data-var (skip radios/checkboxes already handled)
    const el = $(`select[data-var="${i}"], textarea[data-var="${i}"], input.input[data-var="${i}"]`, $("#tab-form"));
    return el ? el.value : "";
  }
  function focusFirstField() {
    const a = S.analysis; if (!a) return;
    const fields = [];
    const seen = new Set();
    $$("[data-var]", $("#tab-form")).forEach((f) => {
      const i = f.dataset.var; if (seen.has(i)) return; seen.add(i);
      const v = a.variables[+i];
      if (v && (v.control === "radio" || v.control === "multiselect")) {
        const g = $(`.choice-group[data-var="${i}"]`, $("#tab-form"));
        fields.push(g ? ($("input", g) || g) : f);
      } else fields.push(f);
    });
    const empty = fields.find((f) => {
      const i = f.dataset?.var ?? f.closest?.("[data-var]")?.dataset?.var;
      const v = a.variables[+i]; return v && v.required && !(S.values[v.name] || "").trim();
    });
    const el = empty || fields[0];
    const ae = document.activeElement;
    if (el && ae !== editor && ae !== title && ae !== $("#list") && ae !== $("#search")) { el.focus(); if (el.select && el.tagName === "INPUT" && el.type !== "radio" && el.type !== "checkbox") el.select(); }
  }
  $("#tab-form").addEventListener("input", (e) => {
    const idx = e.target.dataset.var; if (idx == null) return;
    const v = S.analysis.variables[+idx]; if (!v) return;
    if (v.control === "radio" || v.control === "multiselect") return; // handled on change
    S.values[v.name] = e.target.value; S.valuesDirty = true; e.target.dataset.touched = "1";
    setValuesState(); validateField(e.target); runAnalyze();
  });
  $("#tab-form").addEventListener("change", (e) => {
    const idx = e.target.dataset.var; if (idx == null) return;
    const v = S.analysis.variables[+idx]; if (!v) return;
    if (e.target.tagName === "SELECT" || v.control === "radio" || v.control === "multiselect") {
      e.target.dataset.touched = "1";
      S.values[v.name] = readFormValue(+idx); S.valuesDirty = true;
      setValuesState();
      const group = e.target.closest(".choice-group") || e.target;
      validateField(group); runAnalyze();
    }
  });
  // show "required" errors only after the user moved on to another field (not when a dialog / window steals focus)
  $("#tab-form").addEventListener("focusout", (e) => {
    if (!e.target.dataset || e.target.dataset.var == null) return;
    if (!e.relatedTarget || !$("#tab-form").contains(e.relatedTarget)) return;
    e.target.dataset.touched = "1"; validateField(e.target);
  });
  $("#tab-form").addEventListener("click", (e) => {
    const b = e.target.closest(".num-btn");
    if (b) {
      const el = $(`[data-var="${b.dataset.for}"]`, $("#tab-form")); if (!el) return;
      const v = S.analysis.variables[+b.dataset.for];
      const base = parseFloat(String(el.value || (v.default ?? "0")).replace(/,/g, "")) || 0;
      el.value = String(base + +b.dataset.step); el.dispatchEvent(new Event("input", { bubbles: true })); el.focus();
      return;
    }
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "clear-last") { e.preventDefault(); S.fromLast = false; resetValues(); }
    else if (act === "insert") { editor.focus(); editor.setSelectionRange(editor.value.length, editor.value.length); openInsertMenu(); }
    else if (act === "syntax") openHelp("syntax");
  });
  function fieldError(v, raw) {
    const val = String(raw ?? "");
    if (v.required && !val.trim()) return "必填项，请填写";
    if (val.trim() && v.control === "number" && !/^[-+]?(\d{1,3}(,\d{3})+|\d+)?(\.\d+)?$/.test(val.trim())) return "请输入数字，例如 300 或 1.5";
    if (val.trim() && v.control === "number" && !/\d/.test(val)) return "请输入数字";
    if (val && (v.control === "select" || v.control === "radio") && v.options.length && !v.options.includes(val)) return "不在选项中";
    if (val.trim() && v.control === "multiselect" && v.options.length) {
      const bad = val.split(/[、,/，]/).map((s) => s.trim()).filter(Boolean).filter((x) => !v.options.includes(x));
      if (bad.length) return "含无效选项：" + bad.join("、");
    }
    return "";
  }
  function validateField(el) {
    const a = S.analysis; if (!a) return;
    const i = +el.dataset.var, v = a.variables[i]; if (!v) return;
    const group = el.classList?.contains("choice-group") ? el : (el.closest?.(".choice-group") || el);
    const touched = el.dataset.touched || group.dataset?.touched;
    const raw = (v.control === "radio" || v.control === "multiselect") ? readFormValue(i) : (el.value ?? "");
    const msg = touched ? fieldError(v, raw) : "";
    const mark = (v.control === "radio" || v.control === "multiselect") ? group : el;
    mark.classList.toggle("invalid", !!msg);
    mark.setAttribute("aria-invalid", msg ? "true" : "false");
    if (touched) group.dataset.touched = "1";
    const m = $(`[data-msg="${i}"]`, $("#tab-form")); if (m) m.innerHTML = msg ? `${I("alert", 12)}${esc(msg)}` : "";
  }
  function updateFormValidity() {
    const seen = new Set();
    $$("[data-var]", $("#tab-form")).forEach((el) => {
      const i = el.dataset.var; if (seen.has(i)) return; seen.add(i);
      const v = S.analysis?.variables?.[+i];
      if (v && (v.control === "radio" || v.control === "multiselect")) {
        const g = $(`.choice-group[data-var="${i}"]`, $("#tab-form")) || el;
        validateField(g);
      } else validateField(el);
    });
  }
  function setValuesState() {
    const el = $("#valuesState");
    if (!S.cur) { el.textContent = ""; return; }
    const n = Object.values(S.values).filter((x) => x !== "" && x != null).length;
    el.textContent = S.valuesDirty ? `● 测试值未保存（${n} 项）` : (n ? `已保存 ${n} 项测试值` : "");
  }
  $("#saveValuesBtn").onclick = async () => {
    if (!S.cur) return;
    const names = new Set((S.analysis?.variables || []).map((v) => v.name));
    const vals = {}; Object.entries(S.values).forEach(([k, v]) => { if (names.has(k) && v !== "") vals[k] = v; });
    const r = await call("save_test_values", S.cur.id, vals);
    if (r && r.ok) { S.cur.test_values = vals; S.values = { ...vals }; S.valuesDirty = false; setValuesState(); runAnalyze(); toast(`已保存 ${r.count} 项测试值`); }
  };
  function resetValues() { S.values = {}; S.valuesDirty = true; S.varSig = ""; S.fromLast = false; setValuesState(); runAnalyze.flush(); }
  $("#resetValuesBtn").onclick = resetValues;

  // ---------------------------------------------------------------- preview tab
  const SEG_TITLE = { value: "已填写", default: "使用默认值", missing: "必填变量未填写" };
  function applyRoleSysEnabled() {
    if (S.settings && typeof S.settings.apply_role_system_prompt === "boolean")
      return !!S.settings.apply_role_system_prompt;
    return true;
  }
  function currentRoleSystemPrompt() {
    if (!S.cur) return "";
    const role = (S.tree.roles || []).find((r) => r.id === S.cur.role_id);
    return ((role && role.system_prompt) || "").trim();
  }
  function updateRoleSysUI() {
    const on = applyRoleSysEnabled();
    const sp = currentRoleSystemPrompt();
    const tog = $("#applyRoleSysToggle");
    if (tog && tog.checked !== on) tog.checked = on;
    const chip = $("#roleSysChip");
    if (chip) chip.classList.toggle("hidden", !(on && sp));
    const setEl = $("#setApplyRoleSys");
    if (setEl && setEl.checked !== on) setEl.checked = on;
  }
  function withRoleSystem(bodyText) {
    const sp = applyRoleSysEnabled() ? currentRoleSystemPrompt() : "";
    if (!sp) return { text: bodyText || "", applied: false };
    return { text: sp + "\n\n---\n\n" + (bodyText || ""), applied: true };
  }
  function renderPreview() {
    const a = S.analysis, base = a ? a.rendered : "";
    const missing = new Set(a?.missing || []);
    const marks = S.previewMarks !== false;
    updateRoleSysUI();
    if (!S.cur) { $("#previewText").innerHTML = ""; $("#previewInfo").textContent = ""; $("#previewMd").innerHTML = ""; return; }
    const wrapped = withRoleSystem(base);
    const txt = wrapped.text;
    let html = "";
    if (wrapped.applied) {
      const sp = currentRoleSystemPrompt();
      html += `<div class="pv-role-sys"><div class="pv-role-sys-h">角色设定</div><pre class="pv-role-sys-b">${esc(sp)}</pre><div class="pv-role-sys-sep">---</div></div>`;
    }
    html += (a?.segments || []).map((g) => g.k === "text" || (!marks && g.k !== "missing") ? esc(g.t)
      : `<span class="pv ${g.k === "missing" ? "hole" : g.k}" title="${esc(g.v)}：${SEG_TITLE[g.k]}（点击填写）" data-v="${esc(g.v)}">${esc(g.t) || "<i>∅</i>"}</span>`).join("");
    $("#previewText").innerHTML = html || `<span class="muted">（正文为空）</span>`;
    if (S.previewView === "md") $("#previewMd").innerHTML = window.MiniMD.render(txt);
    const st = a?.stats.rendered;
    $("#previewInfo").textContent = st ? `${st.chars} 字符 · 约 ${st.tokens} tokens · ${st.lines} 行` + (missing.size ? ` · ${missing.size} 个必填未填` : "") + (wrapped.applied ? " · 含角色设定" : "") : "";
  }
  $("#previewText").addEventListener("click", (e) => {
    const sg = e.target.closest(".pv"); if (!sg || !S.analysis) return;
    focusVar(sg.dataset.v);
  });
  function focusVar(name) {
    const idx = S.analysis.variables.findIndex((v) => v.name === name); if (idx < 0) return;
    setTab("form"); const el = $(`[data-var="${idx}"]`, $("#tab-form")); if (el) { el.focus(); el.scrollIntoView({ block: "center" }); }
  }
  $("#markToggle").onchange = (e) => { S.previewMarks = e.target.checked; renderPreview(); };
  $("#applyRoleSysToggle")?.addEventListener("change", async (e) => {
    const on = !!e.target.checked;
    S.settings = S.settings || {};
    S.settings.apply_role_system_prompt = on;
    await saveSettings({ apply_role_system_prompt: on });
    renderPreview();
  });
  $$("#tab-preview .seg button").forEach((b) => b.onclick = () => {
    S.previewView = b.dataset.view;
    $$("#tab-preview .seg button").forEach((x) => x.classList.toggle("active", x === b));
    $("#previewText").classList.toggle("hidden", S.previewView !== "text");
    $("#previewMd").classList.toggle("hidden", S.previewView !== "md");
    renderPreview();
  });

  // ---------------------------------------------------------------- debug tab
  const LV = { error: ["alert", "错误"], warn: ["alert", "警告"], info: ["info", "提示"] };
  const DEBUG_SEC_KEY = "pb.debug.sections";
  function debugSecState() {
    let st = { check: null, vars: null, usage: false, mm: true }; // null = auto
    try {
      const raw = JSON.parse(localStorage.getItem(DEBUG_SEC_KEY) || "{}");
      if (raw && typeof raw === "object") st = Object.assign(st, raw);
    } catch (_) {}
    return st;
  }
  function setDebugSec(id, open) {
    const st = debugSecState();
    st[id] = !!open;
    try { localStorage.setItem(DEBUG_SEC_KEY, JSON.stringify(st)); } catch (_) {}
  }
  function debugSecOpen(id, autoOpen) {
    const st = debugSecState();
    if (st[id] === null || st[id] === undefined) return !!autoOpen;
    return !!st[id];
  }
  function dbgSec(id, title, summary, bodyHtml, autoOpen) {
    const open = debugSecOpen(id, autoOpen);
    return `<div class="dbg-sec${open ? " open" : ""}" data-sec="${id}">
      <button type="button" class="dbg-sec-h" data-dbg="sec-toggle" data-sec="${id}" aria-expanded="${open ? "true" : "false"}">
        <span class="dbg-chev">${I("chevRight", 14)}</span>
        <span class="dbg-sec-title">${title}</span>
        <span class="dbg-sec-sum muted small">${summary || ""}</span>
      </button>
      <div class="dbg-sec-b">${bodyHtml}</div>
    </div>`;
  }

  function renderDebug() {
    const a = S.analysis, el = $("#tab-debug");
    if (!a || !S.cur) { el.innerHTML = emptyState("bug", "未选择提示词", "调试面板会检查语法、列出变量并统计字数。"); return; }
    // Preserve model pick across full re-renders
    const prevPick = new Set([...$$("#mmPick input:checked")].map((x) => x.dataset.tm));
    if (prevPick.size) S.mmPickKeys = [...prevPick];
    const prevJudge = ($("#mmJudgeSel") && $("#mmJudgeSel").value) || S.mmJudgeKey || "";
    if (prevJudge) S.mmJudgeKey = prevJudge;

    const errN = a.issue_counts.error || 0, warnN = a.issue_counts.warn || 0;
    let pillCls = "ok", pillTxt = "OK", pillIcon = "check";
    if (errN) { pillCls = "err"; pillTxt = `${errN} 错误`; pillIcon = "alert"; }
    else if (warnN || !a.ok) { pillCls = "warn"; pillTxt = warnN ? `${warnN} 警告` : "有问题"; pillIcon = "alert"; }
    const top = `<div class="dbg-top">
      <button type="button" class="dbg-pill ${pillCls}" data-dbg="scroll-check" title="查看提示词体检">${I(pillIcon, 13)}${pillTxt}</button>
      <span class="spacer"></span>
      <button class="btn secondary sm" data-dbg="sample" title="按控件类型生成示例值">${I("sparkles", 14)}试填</button>
      <button class="btn ghost sm" data-dbg="clear">清空</button>
    </div>`;

    const issues = a.issues.length
      ? a.issues.map((i, k) => `<button class="issue ${i.level}" data-k="${k}" title="${i.line ? "跳到对应位置" : "去填写"}"><span class="lv" aria-label="${LV[i.level][1]}">${I(LV[i.level][0], 14)}</span><span>${esc(i.message)}</span>${i.line ? `<span class="loc">L${i.line}${i.col ? ":" + i.col : ""}</span>` : ""}</button>`).join("")
      : `<div class="ok-box quiet">${I("check", 14)}体检通过 · 语法与语义均无问题</div>`;
    const checkSum = a.ok ? "语法通过" : (errN ? `${errN} 错误` : `${warnN} 警告`);
    const infoN = a.issue_counts.info || 0;
    const lintSum = a.ok && !infoN ? "体检通过" : (errN ? `${errN} 错误` : (warnN ? `${warnN} 警告` : `${infoN} 提示`));
    const checkSec = dbgSec("check", "体检", lintSum, issues, !a.ok || !!infoN);

    let varsBody;
    if (!a.variables.length) {
      varsBody = `<div class="muted small">没有变量 · <a href="#" data-dbg="insert">插入一个</a></div>`;
    } else {
      varsBody = `<div class="dbg-vars">${a.variables.map((v) => {
        const optTip = v.options.length ? esc(v.options.join(" / ")) : "";
        const def = v.default == null ? "" : (v.default === "" ? "（空）" : String(v.default));
        const lines = [...new Set(v.lines || [])].join(",");
        return `<button type="button" class="dbg-var" data-dbg="var-jump" data-var="${esc(v.name)}" data-line="${lines}" title="${optTip || "定位变量"}">
          <span class="dbg-var-name">${esc(v.name)}${v.count > 1 ? ` <span class="muted">×${v.count}</span>` : ""}</span>
          <span class="tag ctl">${esc(v.control_label || v.control || "")}</span>
          <span class="tag ${v.required ? "req" : "opt"}">${v.required ? "必填" : "可选"}</span>
          ${def ? `<span class="dbg-var-def muted small">${esc(def)}</span>` : ""}
          ${optTip ? `<span class="dbg-var-opts muted small">${optTip}</span>` : ""}
        </button>`;
      }).join("")}</div>`;
    }
    const varsSec = dbgSec("vars", `变量（${a.variables.length}）`, a.variables.length ? "" : "无", varsBody, a.variables.length > 0);

    const t = a.stats.template, r = a.stats.rendered;
    const usageSum = `渲染 ${r.chars} 字 · ≈${r.tokens} tokens`;
    const row = (k, x, y) => `<div class="k">${k}</div><div class="v">${x}</div><div class="v">${y}</div>`;
    const usageBody = `<div class="stats-grid"><div class="h"></div><div class="h" style="text-align:right">模板</div><div class="h" style="text-align:right">渲染</div>
      ${row("字符", t.chars, r.chars)}${row("不含空白", t.chars_no_space, r.chars_no_space)}${row("中文", t.cjk, r.cjk)}${row("词数", t.words, r.words)}${row("行数", t.lines, r.lines)}${row("Token≈", "≈" + t.tokens, "≈" + r.tokens)}</div>
      <div class="muted small" style="margin-top:4px">Token 为粗略估算，不同模型略有差异。</div>`;
    const usageSec = dbgSec("usage", "用量", usageSum, usageBody, false);

    const mm = renderMmSection();
    el.innerHTML = top + checkSec + varsSec + usageSec + mm;
    window.PBIcons && window.PBIcons.fill(el);
    queueMicrotask(() => { mmEnsurePick().catch(() => {}); });
  }

  function mmScoreOf(row) {
    const u = Number(row.user_score || 0), a = Number(row.ai_score || 0);
    if (u > 0 && a > 0) return (u + a) / 2;
    return u || a || 0;
  }
  function mmResultsHtml() {
    const saved = S.mmResults || (S.cur && S.cur.last_ai_run && S.cur.last_ai_run.results) || null;
    if (!saved || !saved.length) return `<div class="muted small" id="mmResults">用当前表单渲染结果并行请求</div>`;
    const sorted = [...saved].sort((a, b) => mmScoreOf(b) - mmScoreOf(a) || (a.latency_ms || 0) - (b.latency_ms || 0));
    return `<div class="mm-grid" id="mmResults">${sorted.map((row, idx) => {
      const err = !row.ok;
      const us = Number(row.user_score || 0);
      const stars = [1,2,3,4,5].map((n) => `<button type="button" data-mm-star="${esc(row.id)}" data-n="${n}" class="${n <= us ? "on" : ""}" title="打 ${n} 分">★</button>`).join("");
      const aiPill = row.ai_score ? `<span class="mm-score-pill ai" title="${esc(row.ai_note || "")}">AI ${row.ai_score}</span>` : "";
      const comb = mmScoreOf(row);
      const combPill = comb ? `<span class="mm-score-pill">综合 ${comb % 1 ? comb.toFixed(1) : comb}</span>` : "";
      return `<div class="mm-card${err ? " err" : ""}" data-mm-id="${esc(row.id)}">
        <div class="mm-h"><span>#${idx + 1} ${esc(row.label || row.model || "")}</span><span>${err ? "失败" : ((row.latency_ms || 0) + " ms")}</span></div>
        <div class="mm-meta">${combPill}${aiPill}<span class="mm-stars">${stars}</span></div>
        <div class="mm-b">${esc(err ? (row.error || "错误") : (row.text || ""))}</div>
      </div>`;
    }).join("")}</div>`;
  }
  function refreshMmResults() {
    const host = $("#mmResultsHost");
    if (!host) return;
    host.innerHTML = mmResultsHtml();
    // show/hide post-result actions
    const has = !!(S.mmResults && S.mmResults.length);
    const post = $("#mmPostActions");
    if (post) post.hidden = !has;
  }
  function updateMmCardScores(id) {
    if (!S.mmResults) return;
    const row = S.mmResults.find((x) => x.id === id);
    if (!row) return;
    const card = $(`.mm-card[data-mm-id="${CSS.escape(id)}"]`);
    if (!card) { refreshMmResults(); return; }
    const us = Number(row.user_score || 0);
    card.querySelectorAll("[data-mm-star]").forEach((b) => b.classList.toggle("on", +b.dataset.n <= us));
    const meta = card.querySelector(".mm-meta");
    if (!meta) return;
    const comb = mmScoreOf(row);
    let combEl = meta.querySelector(".mm-score-pill:not(.ai)");
    if (comb) {
      const txt = `综合 ${comb % 1 ? comb.toFixed(1) : comb}`;
      if (combEl) combEl.textContent = txt;
      else {
        combEl = document.createElement("span");
        combEl.className = "mm-score-pill";
        combEl.textContent = txt;
        meta.insertBefore(combEl, meta.firstChild);
      }
    } else if (combEl) combEl.remove();
  }
  function setMmStatus(msg) {
    const st = $("#mmStatus"); if (st) st.textContent = msg || "";
  }
  function renderMmSection() {
    if (!S.cur) return "";
    const at = (S.mmResults && S.mmAt) || (S.cur.last_ai_run && S.cur.last_ai_run.at) || "";
    const hasResults = !!(S.mmResults && S.mmResults.length) || !!(S.cur.last_ai_run && S.cur.last_ai_run.results && S.cur.last_ai_run.results.length);
    const open = debugSecOpen("mm", true);
    const body = `
      <p class="muted small dbg-mm-hint">用当前表单渲染结果并行请求</p>
      <div class="mm-pick" id="mmPick"><span class="muted small">加载模型中…</span></div>
      <div class="mm-tools">
        <button class="btn primary sm" data-dbg="mm-run" title="用当前表单渲染后的提示词并行请求">开始试跑</button>
        <button class="btn ghost icon sm" data-dbg="mm-load" title="刷新模型列表" aria-label="刷新">${I("refresh", 14)}</button>
        <span class="muted small" id="mmStatus"></span>
        <span class="spacer"></span>
        <span id="mmPostActions" ${hasResults ? "" : "hidden"}>
          <select class="input sm" id="mmJudgeSel" title="评判模型" style="width:auto;min-width:120px;max-width:200px"><option value="">评判模型</option></select>
          <button class="btn ghost sm" data-dbg="mm-judge" title="用评判模型打分">AI 打分</button>
          <button class="btn ghost sm" data-dbg="mm-save" title="保存到本提示词">保存</button>
        </span>
      </div>
      <div id="mmResultsHost">${mmResultsHtml()}</div>`;
    return `<div class="dbg-sec debug-mm${open ? " open" : ""}" data-sec="mm" id="debugMm">
      <button type="button" class="dbg-sec-h" data-dbg="sec-toggle" data-sec="mm" aria-expanded="${open ? "true" : "false"}">
        <span class="dbg-chev">${I("chevRight", 14)}</span>
        <span class="dbg-sec-title">试跑</span>
        <span class="dbg-sec-sum muted small">${at ? esc(at) : ""}</span>
      </button>
      <div class="dbg-sec-b">${body}</div>
    </div>`;
  }

  async function mmEnsurePick() {
    await loadAiData();
    const box = $("#mmPick");
    const jsel = $("#mmJudgeSel");
    if (!box) return;
    const opts = [];
    (AI.profiles || []).forEach((p) => {
      (p.models || [p.default_model].filter(Boolean)).forEach((m) => {
        const key = `${p.id}||${m}`;
        opts.push({ key, label: `${p.name || p.id} · ${m}`, profile_id: p.id, model: m });
      });
    });
    if (!opts.length) {
      box.innerHTML = `<div class="mm-empty"><span class="muted small">尚未配置可用模型（需厂商 + API Key）。</span>
        <button type="button" class="btn secondary sm" data-dbg="mm-settings">${I("settings", 13)}打开 AI 模型设置</button></div>`;
      window.PBIcons && window.PBIcons.fill(box);
      return;
    }
    const prev = new Set(S.mmPickKeys || [...$$("#mmPick input:checked")].map((x) => x.dataset.tm));
    // If DOM already has matching checkboxes and count matches, keep DOM (avoid remount flicker)
    const existing = $$("#mmPick input[data-tm]");
    const existingKeys = existing.map((x) => x.dataset.tm);
    const same = existingKeys.length === opts.length && opts.every((o, i) => existingKeys[i] === o.key);
    if (!same) {
      box.innerHTML = opts.map((o) => {
        const on = prev.size ? prev.has(o.key) : (o.profile_id === AI.defaultId);
        return `<label class="${on ? "on" : ""}"><input type="checkbox" data-tm="${esc(o.key)}" ${on ? "checked" : ""}>${esc(o.label)}</label>`;
      }).join("");
      box.querySelectorAll("input").forEach((inp) => {
        inp.addEventListener("change", () => {
          inp.closest("label").classList.toggle("on", inp.checked);
          S.mmPickKeys = [...$$("#mmPick input:checked")].map((x) => x.dataset.tm);
        });
      });
    } else {
      // sync checked from S.mmPickKeys if set
      if (prev.size) {
        existing.forEach((inp) => {
          const on = prev.has(inp.dataset.tm);
          inp.checked = on;
          inp.closest("label").classList.toggle("on", on);
        });
      }
    }
    S.mmPickKeys = [...$$("#mmPick input:checked")].map((x) => x.dataset.tm);
    if (jsel) {
      const cur = S.mmJudgeKey || jsel.value;
      jsel.innerHTML = `<option value="">评判模型</option>` + opts.map((o) =>
        `<option value="${esc(o.key)}" ${o.key === cur ? "selected" : ""}>${esc(o.label)}</option>`).join("");
      if (!jsel.value && AI.defaultId) {
        const d = opts.find((o) => o.profile_id === AI.defaultId);
        if (d) jsel.value = d.key;
      }
      jsel.onchange = () => { S.mmJudgeKey = jsel.value; };
      S.mmJudgeKey = jsel.value;
    }
  }

  async function mmRun() {
    await mmEnsurePick();
    const boxes = $$("#mmPick input[type=checkbox]:checked");
    const targets = [...boxes].map((x) => parseTarget(x.dataset.tm));
    if (!targets.length) {
      if (!(AI.profiles || []).some((p) => p.has_key)) {
        toast("请先在设置中配置 AI 模型", { type: "warn", action: "去设置", onAction: () => openSettings("ai") });
      } else toast("请至少勾选一个模型", { type: "warn" });
      return;
    }
    const miss = (S.analysis && S.analysis.missing) || [];
    if (miss.length) {
      toast(`有 ${miss.length} 个必填变量未填写，请先在表单补全`, { type: "warn", action: "去填写", onAction: () => focusVar(miss[0]) });
      focusVar(miss[0]);
      return;
    }
    const rendered = (S.analysis && S.analysis.rendered) || "";
    if (!String(rendered).trim()) { toast("请先在表单填好变量（可先一键试填）", { type: "warn" }); setTab("form"); return; }
    S.mmPickKeys = [...boxes].map((x) => x.dataset.tm);
    setMmStatus("试跑中…");
    const r = await call("ai_parallel_test", rendered, targets);
    if (!r || !r.ok) { setMmStatus((r && r.error) || "失败"); toast((r && r.error) || "试跑失败", { type: "error" }); return; }
    S.mmResults = (r.results || []).map((row) => ({
      id: row.id || (row.label || row.model || Math.random().toString(36).slice(2)),
      label: row.label || row.model || "",
      model: row.model || "",
      ok: !!row.ok,
      text: row.text || "",
      error: row.error || "",
      latency_ms: row.latency_ms || 0,
      user_score: 0,
      ai_score: 0,
      ai_note: "",
    }));
    S.mmAt = new Date().toLocaleString("zh-CN", { hour12: false });
    S.mmRendered = String(rendered).slice(0, 400);
    setMmStatus(`完成 ${(S.mmResults).filter((x) => x.ok).length}/${S.mmResults.length}`);
    // Update section summary timestamp without full remount of pick
    const sum = $("#debugMm .dbg-sec-sum"); if (sum) sum.textContent = S.mmAt;
    refreshMmResults();
    await mmEnsurePick();
    const host = $("#mmResultsHost") || $("#debugMm");
    if (host) host.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  async function mmJudge() {
    if (!S.mmResults || !S.mmResults.length) { toast("请先试跑", { type: "warn" }); return; }
    const key = ($("#mmJudgeSel") && $("#mmJudgeSel").value) || S.mmJudgeKey || "";
    if (!key) { toast("请选择评判模型", { type: "warn" }); return; }
    const t = parseTarget(key);
    const rendered = (S.analysis && S.analysis.rendered) || S.mmRendered || "";
    setMmStatus("AI 打分中…");
    const r = await call("ai_judge", rendered, S.mmResults, t.profile_id, t.model);
    if (!r || !r.ok) { setMmStatus((r && r.error) || "打分失败"); toast((r && r.error) || "打分失败", { type: "error" }); return; }
    const byI = {};
    (r.scores || []).forEach((s) => { byI[s.i] = s; });
    S.mmResults.forEach((row, i) => {
      const s = byI[i];
      if (s) { row.ai_score = s.score; row.ai_note = s.note || ""; }
    });
    setMmStatus("AI 打分完成");
    refreshMmResults();
    const host = $("#mmResultsHost") || $("#debugMm");
    if (host) host.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  async function mmSave() {
    if (!S.cur || !S.mmResults) { toast("没有可保存的试跑结果", { type: "warn" }); return; }
    if (S.cur.builtin) {
      toast("内置提示词请先「复制后编辑」再保存试跑", { type: "warn" }); return;
    }
    const run = {
      at: S.mmAt || new Date().toLocaleString("zh-CN", { hour12: false }),
      rendered_preview: S.mmRendered || "",
      results: S.mmResults,
      sort: "score",
    };
    const r = await call("save_ai_run", S.cur.id, run);
    if (r && r.ok) {
      S.cur.last_ai_run = (r.prompt && r.prompt.last_ai_run) || run;
      toast("已保存试跑结果");
    } else toast((r && r.error) || "保存失败", { type: "error" });
  }

  $("#tab-debug").addEventListener("click", async (e) => {
    const dbg = e.target.closest("[data-dbg]")?.dataset.dbg;
    if (dbg === "sec-toggle") {
      const id = e.target.closest("[data-dbg]")?.dataset.sec;
      const sec = id && $(`.dbg-sec[data-sec="${id}"]`);
      if (sec) {
        const open = !sec.classList.contains("open");
        sec.classList.toggle("open", open);
        const btn = sec.querySelector(".dbg-sec-h");
        if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
        setDebugSec(id, open);
      }
      return;
    }
    if (dbg === "scroll-check") {
      const sec = $('.dbg-sec[data-sec="check"]');
      if (sec) {
        sec.classList.add("open");
        setDebugSec("check", true);
        sec.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
      return;
    }
    if (dbg === "var-jump") {
      const btn = e.target.closest("[data-dbg=var-jump]");
      if (!btn) return;
      const name = btn.dataset.var;
      const line = (btn.dataset.line || "").split(",")[0];
      if (name) focusVar(name);
      else if (line) jumpTo(+line, 1);
      return;
    }
    if (dbg === "sample") {
      const vals = await call("sample_values", editor.value); if (!vals) return;
      S.values = vals; S.valuesDirty = true; S.varSig = ""; S.fromLast = false; setValuesState(); runAnalyze.flush();
      toast("已填入示例值，可在「表单」页修改或保存", { type: "info" }); return;
    }
    if (dbg === "clear") return resetValues();
    if (dbg === "insert") { e.preventDefault(); editor.focus(); return openInsertMenu(); }
    if (dbg === "mm-load") { await mmEnsurePick(); return; }
    if (dbg === "mm-settings") { openSettings("ai"); return; }
    if (dbg === "mm-run") { await mmRun(); return; }
    if (dbg === "mm-judge") { await mmJudge(); return; }
    if (dbg === "mm-save") { await mmSave(); return; }
    const star = e.target.closest("[data-mm-star]");
    if (star && S.mmResults) {
      const id = star.dataset.mmStar, n = +star.dataset.n;
      const row = S.mmResults.find((x) => x.id === id);
      if (row) {
        row.user_score = row.user_score === n ? 0 : n;
        // Do NOT full renderDebug — preserve pick & scroll
        S.mmPickKeys = [...$$("#mmPick input:checked")].map((x) => x.dataset.tm);
        updateMmCardScores(id);
      }
      return;
    }
    const it = e.target.closest(".issue"); if (!it) return;
    const i = S.analysis.issues[+it.dataset.k]; if (!i) return;
    if (i.code === "required_empty" || i.code === "number_value" || i.code === "select_value" || i.code === "unfilled_optional") {
      setTab("form"); if (i.var) focusVar(i.var);
    } else if (i.code === "unused_values") {
      setTab("form");
    } else if (i.line) jumpTo(i.line, i.col);
    else if (i.var) { setTab("form"); focusVar(i.var); }
  });

  // ---------------------------------------------------------------- tabs + copy
  const TABS = ["form", "preview", "debug"];
  function setTab(t) {
    const changed = S.tab !== t;
    S.tab = t;
    if (t === "form" && changed) setTimeout(focusFirstField, 0);
    if (t === "preview") setTimeout(renderPreview, 0);
    $$(".tab").forEach((b) => { const on = b.dataset.tab === t; b.classList.toggle("active", on); b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1; });
    TABS.forEach((k) => $("#tab-" + k).classList.toggle("hidden", k !== t));
    const foot = $("#formFoot"); if (foot) foot.hidden = t !== "form";
  }
  $$(".tab").forEach((b) => b.onclick = () => setTab(b.dataset.tab));
  $(".tabs").addEventListener("keydown", (e) => {
    if (!e.target.classList.contains("tab") || (e.key !== "ArrowRight" && e.key !== "ArrowLeft")) return;
    const i = (TABS.indexOf(S.tab) + (e.key === "ArrowRight" ? 1 : 2)) % 3;
    setTab(TABS[i]); $(`.tab[data-tab="${TABS[i]}"]`).focus();
  });
  async function copyResult() {
    if (!S.cur || !S.analysis) return;
    const rr = await call("render_prompt", editor.value, S.values, S.cur.id, S.cur.role_id || "", applyRoleSysEnabled());
    const text = (rr && rr.final) || S.analysis.rendered;
    const r = await call("copy_text", text, S.cur.id, S.values);
    if (r && r.ok) {
      const miss = S.analysis.missing.length;
      const chip = (rr && rr.applied) ? "（含角色设定）" : "";
      if (miss) toast(`已复制${chip}，但有 ${miss} 个必填变量未填写`, { type: "warn", action: "去填写", onAction: () => focusVar(S.analysis.missing[0]) });
      else toast(`已复制到剪贴板${chip}`);
    } else toast("复制失败", { type: "error" });
  }
  const copyBtn = $("#copyBtn"); if (copyBtn) copyBtn.onclick = copyResult;
  $("#copyResultMenuBtn")?.addEventListener("click", () => { toggleEditorMore(false); copyResult(); });

  // ---------------------------------------------------------------- import / export
  function toggleIO(open) {
    $("#ioMenu").classList.toggle("hidden", !open); $("#ioBtn").setAttribute("aria-expanded", String(open));
    if (open) $("#ioMenu button").focus();
  }
  $("#ioBtn").onclick = (e) => { e.stopPropagation(); toggleIO($("#ioMenu").classList.contains("hidden")); };
  $("#ioMenu").addEventListener("keydown", (e) => menuKeys($("#ioMenu"), e, () => { toggleIO(false); $("#ioBtn").focus(); }));
  document.addEventListener("mousedown", (e) => {
    if (!e.target.closest("#ioMenu, #ioBtn")) toggleIO(false);
    if (!e.target.closest("#insertMenu, #insertBtn")) closeInsertMenu(false);
    if (!e.target.closest("#editorMoreMenu, #editorMoreBtn")) toggleEditorMore(false);
    if (!e.target.closest("#sortCompactMenu, #sortCompactBtn, #sortSel")) toggleSortCompact(false);
  });
  $("#ioMenu").addEventListener("click", (e) => { const io = e.target.closest("[data-io]")?.dataset.io; if (io) { toggleIO(false); runIO(io); } });
  async function runIO(io) {
    await flushSave();
    let r;
    if (io === "import-json") {
      r = await call("import_library");
      if (r && r.ok) { toast(`已导入：新增 ${r.added} 个` + (r.replaced ? `，覆盖同 ID ${r.replaced} 个` : "")); await refreshList(); if (!S.cur && S.list.length) openPrompt(S.list[0].id); }
      else if (r && !r.cancelled) toast(r.error || "导入失败", { type: "error" });
    } else if (io === "import-md") {
      r = await call("import_markdown");
      if (r && r.ok) { toast(`已导入 ${r.count} 个 Markdown 文件` + (r.errors.length ? `，${r.errors.length} 个失败` : ""), { type: r.errors.length ? "warn" : "success" }); await refreshList(); if (r.ids[0]) openPrompt(r.ids[0]); }
      else if (r && !r.cancelled) toast((r.errors && r.errors[0]) || r.error || "导入失败", { type: "error" });
    } else if (io === "export-json") {
      r = await call("export_library");
      if (r && r.ok) toast(`已导出 ${r.count} 个提示词`);
      else if (r && !r.cancelled && r.error) toast(r.error, { type: "error" });
    } else if (io === "export-md") {
      if (!S.cur) return toast("请先选择一个提示词", { type: "info" });
      r = await call("export_markdown", S.cur.id);
      if (r && r.ok) toast("已导出 Markdown");
      else if (r && !r.cancelled) toast(r.error || "导出失败", { type: "error" });
    } else if (io === "backup") {
      r = await call("backup_data");
      if (r && r.ok) toast("完整备份已保存");
      else if (r && !r.cancelled) toast(r.error || "备份失败", { type: "error" });
    } else if (io === "restore") {
      const ok = await confirmDialog({ title: "从备份恢复？", message: "将用备份中的提示词、设置、版本与历史覆盖当前数据。当前库会先自动快照。", ok: "恢复", danger: true });
      if (!ok) return;
      r = await call("restore_data_backup");
      if (r && r.ok) { toast(`已恢复 ${r.count} 个文件，建议重启应用`, { type: "info", ms: 5000 }); await refreshList(); if (S.list[0]) openPrompt(S.list[0].id); }
      else if (r && !r.cancelled) toast(r.error || "恢复失败", { type: "error" });
    }
  }

  // ---------------------------------------------------------------- settings
  function quickPill(q) {
    const pill = $("#quickPill"), txt = $("#quickPillText");
    pill.className = "status-pill";
    if (!q || q.enabled === false || q.mode === "off") { txt.textContent = "// 唤醒已暂停"; pill.classList.add("warn"); }
    else if (q.mode === "hook") { txt.textContent = "输入 // 唤醒浮框"; pill.classList.add("ok"); }
    else { txt.textContent = "// 唤醒不可用"; pill.classList.add("err"); }
    if (q) { S.elevated = !!q.elevated; $("#adminChip").classList.toggle("hidden", !q.elevated); }
  }
  function hookNote(q) {
    const lines = [];
    if (!q) return "—";
    const m = { hook: "✓ 键盘钩子已安装（只监听不拦截：所有按键照常输入）", off: "// 唤醒已暂停", error: "✕ 键盘钩子无法安装" };
    lines.push(m[q.mode] || q.mode);
    if (q.error) lines.push("原因：" + q.error);
    if (q.setting_error) lines.push("设置错误：" + q.setting_error);
    if (q.reinstalls) lines.push(`钩子已自动重装 ${q.reinstalls} 次`);
    if (q.popup_mode) lines.push(`浮框模式：${q.popup_mode === "fast" ? "预渲染（秒开）" : "经典"}`);
    if (q.latency_ms != null) lines.push(`浮框弹出耗时（中位数）：${q.latency_ms} ms`);
    const sk = q.skipped || {}, SKN = { elevated: "管理员窗口", excluded: "排除的程序", fullscreen: "全屏程序", menu: "菜单/拖动中", desktop: "桌面/任务栏", no_window: "无前台窗口" };
    const skl = Object.entries(sk).filter(([, n]) => n).map(([k, n]) => `${SKN[k] || k} ${n} 次`);
    if (skl.length) lines.push("输入 // 但未弹出：" + skl.join("，"));
    lines.push(`光标定位：GetGUIThreadInfo → MSAA → ${q.uia ? "UI Automation ✓" : "UI Automation（不可用）"} → 鼠标`);
    if (!q.elevated) lines.push("提示：管理员窗口中默认无法唤醒，可在「启动与权限」中开启「以管理员身份启动」。");
    return lines.map(esc).join("<br>");
  }
  async function refreshQuick() {
    const q = await call("quick_status");
    quickPill(q); $("#hookNote").innerHTML = hookNote(q);
    return q;
  }
  const PRESETS = [["VS Code", "Code.exe"], ["Visual Studio", "devenv.exe"], ["JetBrains IDE", "idea64.exe"], ["Windows 终端", "WindowsTerminal.exe"], ["远程桌面", "mstsc.exe"]];
  const excludeList = () => (S.settings.quick_exclude || "").split(/[,，;；\s]+/).map((x) => x.trim()).filter(Boolean);
  function renderExclude() {
    const list = excludeList(), low = list.map((x) => x.toLowerCase());
    $("#excludeChips").innerHTML = list.map((x, i) => `<span class="chip">${esc(x)}<button data-rm="${i}" aria-label="移除 ${esc(x)}">${I("x", 12)}</button></span>`).join("");
    const pre = PRESETS.filter(([, exe]) => !low.includes(exe.toLowerCase()));
    $("#excludePresets").innerHTML = pre.length ? `<span>常用：</span>` + pre.map(([n, exe]) => `<button data-add="${esc(exe)}" title="${esc(exe)}">＋ ${esc(n)}</button>`).join("") : "";
  }
  async function setExclude(list) {
    const r = await saveSettings({ quick_exclude: list.join(", ") });
    if (r && r.ok) renderExclude();
  }
  function addExclude(raw) {
    let v = (raw || "").trim().replace(/^.*[\\/]/, ""); if (!v) return;
    if (!/\.exe$/i.test(v)) v += ".exe";
    const list = excludeList();
    if (list.some((x) => x.toLowerCase() === v.toLowerCase())) return toast(`${v} 已在列表中`, { type: "info" });
    setExclude([...list, v]).then(() => toast(`已排除 ${v}`));
  }
  $("#excludeChips").addEventListener("click", (e) => { const b = e.target.closest("[data-rm]"); if (b) { const l = excludeList(); const x = l.splice(+b.dataset.rm, 1)[0]; setExclude(l).then(() => toast(`已移除 ${x}`, { type: "info" })); } });
  $("#excludePresets").addEventListener("click", (e) => { const b = e.target.closest("[data-add]"); if (b) addExclude(b.dataset.add); });
  $("#excludeAdd").onclick = () => { addExclude($("#excludeInput").value); $("#excludeInput").value = ""; };
  $("#excludeInput").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("#excludeAdd").click(); } });

  function fillSettings() {
    const s = S.settings;
    $("#setEnabled").checked = !!s.quick_enabled;
    $("#setPreview").checked = !!s.quick_preview;
    $("#setAutostart").checked = !!s.autostart;
    $("#setFullscreen").checked = !!s.quick_skip_fullscreen;
    $$("#setFollow button").forEach((b) => b.classList.toggle("active", b.dataset.v === s.quick_follow));
    $$("#setTheme button").forEach((b) => b.classList.toggle("active", b.dataset.v === s.theme));
    const ALLOWED_SORT = new Set(["recent", "updated", "name"]);
    let sort = s.library_sort || "recent";
    if (!ALLOWED_SORT.has(sort)) sort = "recent";
    const ss = $("#setSort"); if (ss) ss.value = sort;
    renderExclude();
    if (typeof renderAiProfiles === "function") renderAiProfiles();
    const ars = $("#setApplyRoleSys");
    if (ars) ars.checked = s.apply_role_system_prompt !== false;
    updateRoleSysUI();
  }
  async function saveSettings(patch) {
    const r = await call("set_settings", patch);
    if (!r) return;
    if (r.settings) { S.settings = r.settings; fillSettings(); applyTheme(r.settings.theme); }
    if (r.quick) { quickPill(r.quick); $("#hookNote").innerHTML = hookNote(r.quick); }
    if (!r.ok) toast(r.error || "保存失败", { type: "error" });
    return r;
  }
  function settingsSection(sec) {
    $$(".settings-nav button").forEach((b) => b.classList.toggle("active", b.dataset.sec === sec));
    $$(".settings-pane section").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== sec));
    if (sec === "startup") refreshAdmin();
    if (sec === "ai") renderAiProfiles();
  }
  $$(".settings-nav button").forEach((b) => b.onclick = () => settingsSection(b.dataset.sec));
  async function openSettings(sec) {
    S.settings = (await call("get_settings")) || S.settings;
    fillSettings(); refreshQuick(); settingsSection(typeof sec === "string" ? sec : "trigger");
    openModal("settingsOverlay", ".settings-nav button.active");
  }
  $("#settingsBtn").onclick = () => openSettings();
  $("#quickPill").onclick = () => openSettings("trigger");
  $("#adminChip").onclick = () => openSettings("startup");
  $("#setEnabled").onchange = (e) => saveSettings({ quick_enabled: e.target.checked }).then((r) => r && r.ok && toast(e.target.checked ? "已启用 // 唤醒" : "已暂停 // 唤醒", { type: "info", ms: 1600 }));
  $("#setPreview").onchange = (e) => saveSettings({ quick_preview: e.target.checked });
  $("#setAutostart").onchange = (e) => saveSettings({ autostart: e.target.checked }).then((r) => r && r.ok && toast(e.target.checked ? "已开启开机自启" : "已关闭开机自启", { type: "info", ms: 1600 }));
  $("#setFullscreen").onchange = (e) => saveSettings({ quick_skip_fullscreen: e.target.checked });
  const _arsEl = $("#setApplyRoleSys");
  if (_arsEl) _arsEl.onchange = async (e) => {
    await saveSettings({ apply_role_system_prompt: !!e.target.checked });
    renderPreview();
  };
  $$("#setFollow button").forEach((b) => b.onclick = () => saveSettings({ quick_follow: b.dataset.v }));
  $$("#setTheme button").forEach((b) => b.onclick = () => saveSettings({ theme: b.dataset.v }));

  // admin mode
  function renderAdmin(st) {
    S.admin = st;
    const sw = $("#setAdmin"), desc = $("#adminDesc"), co = $("#adminCallout");
    sw.checked = !!(st && st.enabled); sw.disabled = !st || !st.supported;
    co.className = "callout hidden"; co.innerHTML = "";
    if (!st) { desc.textContent = "—"; return; }
    if (!st.supported) { desc.textContent = "当前系统不支持。"; return; }
    if (st.enabled && st.elevated) desc.innerHTML = `${I("check", 12)} 已开启 · 正以管理员身份运行，管理员窗口中也能唤醒。`.replace(/^/, "");
    else if (st.enabled) desc.textContent = "已开启，但当前不是管理员身份。";
    else if (st.elevated) desc.textContent = "当前是手动以管理员身份运行的；开启此项后每次都会这样启动。";
    else desc.textContent = "默认关闭。开启时需要确认一次 UAC。";
    const show = (cls, icon, html, actions = "") => { co.className = "callout " + cls; co.innerHTML = `<span class="ic">${I(icon, 16)}</span><div>${html}${actions ? `<div class="callout-actions">${actions}</div>` : ""}</div>`; };
    if (st.enabled && !st.task) show("warn", "alert", "找不到计划任务（可能被安全软件或系统清理删除）。请关闭后重新开启此选项。");
    else if (st.enabled && !st.elevated) show("info", "info", "重启后生效：提示词 Builder 将以管理员身份运行。", `<button class="btn primary sm" data-restart="1">${I("shield", 14)}以管理员身份重启</button>`);
    else if (!st.enabled && st.elevated) show("info", "info", "如需恢复普通权限，请重启提示词 Builder。", `<button class="btn secondary sm" data-restart="0">以普通身份重启</button>`);
  }
  async function refreshAdmin() { renderAdmin(await call("admin_status")); }
  async function doRestart(elevated) {
    await flushSave();
    const r = await call("restart_app", elevated);
    if (r && !r.ok) toast(r.error || "重启失败", { type: "error" });
  }
  $("#adminCallout").addEventListener("click", (e) => { const b = e.target.closest("[data-restart]"); if (b) doRestart(b.dataset.restart === "1"); });
  $("#setAdmin").onchange = async (e) => {
    const on = e.target.checked, sw = e.target;
    sw.disabled = true;
    const hint = on && !S.elevated ? toast("请在弹出的「用户账户控制」窗口中点「是」", { type: "info", ms: 15000 }) : null;
    const r = await call("set_admin_mode", on);
    if (hint) hint();
    sw.disabled = false;
    if (!r || !r.ok) {
      sw.checked = !on;
      if (r && r.status) renderAdmin(r.status);
      if (r && r.cancelled) toast("已取消：没有在 UAC 窗口中确认", { type: "warn" });
      else if (r) toast(r.error || "设置失败", { type: "error" });
      return;
    }
    renderAdmin(r.status);
    S.settings = (await call("get_settings")) || S.settings; fillSettings();
    if (r.restart) {
      const go = await confirmDialog({
        title: on ? "已开启管理员模式" : "已关闭管理员模式",
        message: on ? "需要重启提示词 Builder 才能以管理员身份运行。\n以后开机自启和打开程序都不会再弹出 UAC。" : "需要重启提示词 Builder 才能恢复普通权限。",
        ok: "立即重启", cancel: "稍后" });
      if (go) doRestart(on);
    } else toast(on ? "已开启管理员模式" : "已关闭管理员模式");
  };

  // about
  $("#aboutOnboarding").onclick = () => { closeModal("settingsOverlay"); openOnboarding(); };
  $("#aboutHelp").onclick = () => { closeModal("settingsOverlay"); openHelp("keys"); };
  $("#aboutData").onclick = async () => { const r = await call("open_data_dir"); if (r && !r.ok) toast(r.error || "无法打开", { type: "error" }); };

  // host → page: settings changed elsewhere (tray pause toggle, popup "在此程序中停用")
  window.__pbSettingsChanged = async () => {
    S.settings = (await call("get_settings")) || S.settings;
    applyTheme(S.settings.theme);
    if (!$("#settingsOverlay").classList.contains("hidden")) fillSettings();
    refreshQuick();
  };

  // ---------------------------------------------------------------- help (F1)
  const KEYS = [
    ["主窗口", [
      [["Ctrl", "N"], "新建提示词"], [["Ctrl", "D"], "复制一份当前提示词"], [["F2"], "重命名"], [["Delete"], "删除（列表中，可撤销）"],
      [["Ctrl", "F"], "全局搜索"], [["↑", "↓"], "在提示词间切换"], [["←", "→"], "折叠 / 展开分类"], [["Ctrl", "S"], "立即保存（平时自动保存）"],
      [["Ctrl", "I"], "插入变量"], [["Ctrl", "Enter"], "复制渲染结果"], [["Ctrl", "1/2/3"], "表单 / 预览 / 调试"], [["Ctrl", ","], "设置"], [["Ctrl", "Shift", "A"], "AI 工作室"], [["F1"], "帮助"]]],
    ["角色 › 分类 › 提示", [
      [["点击箭头"], "展开 / 折叠角色或分类"], [["分类 +"], "在该分类下新建提示词"], [["角色 +"], "新建提示词"],
      [["复制后编辑"], "内置提示词只读，复制后可改"], [["面包屑"], "编辑器顶部显示当前角色 › 分类"]]],
    ["// 浮框（在任意输入框）", [
      [["/", "/"], "唤醒浮框"], [["输入文字"], "搜索名称 / 角色 / 分类"], [["↑", "↓"], "选择"], [["Enter"], "插入 / 有必填变量时填表"],
      [["Shift", "Enter"], "先填表再插入"], [["Ctrl", "Enter"], "立即插入（未填的用默认值）"], [["Tab"], "表单中下一项"], [["Esc"], "返回 / 取消（保留 //）"]]],
    ["生命周期", [
      [["收藏"], "收藏提示词（浮框优先；库内「收藏」页签）"], [["置顶"], "置顶到浮框最前（编辑器 ⋯ 菜单）"], [["版本"], "查看 / 保存 / 还原版本"],
      [["归档"], "软归档，不出现在浮框（库「归档」页签可查看 / 恢复）"]]],
  ];
  const SYNTAX = [
    ["{{变量}}", "必填变量，生成单行输入框"],
    ["{{变量|默认值}}", "可选变量，留空时使用默认值；<code>{{变量|}}</code> 表示默认为空"],
    ["{{变量:多行}}", "多行文本框（也可写 <code>长文本</code> / <code>multiline</code>）"],
    ["{{字数:数字|300}}", "数字输入（<code>number</code>），会校验是否为数字"],
    ["{{语气:正式/轻松/幽默|正式}}", "下拉选择，选项用 <code>/</code> 分隔"],
    ["{{优先级:单选:高/中/低|中}}", "单选按钮组（<code>单选</code> / <code>radio</code>）"],
    ["{{标签:多选:A/B/C}}", "多选框（<code>多选</code> / <code>multiselect</code>），填写值用顿号「、」连接"],
    ["{{变量:单行}}", "显式指定单行输入（默认就是单行）"],
    ["\\{{", "输出字面量 <code>{{</code>，不当作变量"],
    ["{{{变量}}}", "外层多出的花括号原样保留，输出 <code>{值}</code>"],
  ];
  function renderHelp(tab) {
    $$("#helpTabs button").forEach((b) => b.classList.toggle("active", b.dataset.h === tab));
    const kb = (ks) => ks.map((k) => `<kbd>${esc(k)}</kbd>`).join("");
    $("#helpBody").className = "modal-body help";
    $("#helpBody").innerHTML = tab === "keys"
      ? KEYS.map(([h, rows]) => `<h3>${esc(h)}</h3><div class="keys-grid">${rows.map(([k, d]) => `<div class="krow"><span>${esc(d)}</span><span class="k">${kb(k)}</span></div>`).join("")}</div>`).join("")
      : `<div class="syn">${SYNTAX.map(([c, d]) => `<div class="s-code"><code>${esc(c)}</code></div><div class="s-desc">${d}</div>`).join("")}</div>
         <p class="tip-p">冒号也可用全角「：」。同名变量在表单里只出现一次，控件类型与默认值以第一次出现为准。<br>
         编辑器工具栏的「插入变量」可以一键插入以上每种写法；选中文字再插入，会把选中的文字作为变量名。<br>
         「调试」页会提示：括号不配对、变量名为空或非法、同名变量冲突、下拉默认值不在选项内、必填未填写等。</p>`;
  }
  function openHelp(tab = "keys") { renderHelp(tab); openModal("helpOverlay", "#helpTabs button.active"); }
  $$("#helpTabs button").forEach((b) => b.onclick = () => renderHelp(b.dataset.h));
  $("#helpBtn").onclick = () => openHelp("keys");
  $("#helpOnboarding").onclick = () => { closeModal("helpOverlay"); openOnboarding(); };

  // ---------------------------------------------------------------- onboarding (3 steps)
  const ONB = [
    { kicker: "第 1 步 · 唤醒", title: "在任意输入框输入 //",
      text: "在微信、浏览器、Word、记事本……任何能打字的地方，快速连续输入两个斜杠，提示词浮框就会出现在光标旁。选中后 // 会被自动删掉并换成提示词；按 Esc 取消则保留 //。",
      demo: `<div class="onb-demo"><div class="demo-input">帮我写一封请假邮件&nbsp;<span class="demo-slash">//</span><span class="demo-caret"></span></div>
        <div class="demo-pop"><div class="dp-q">${I("search", 12)}搜索提示词…</div><div class="dp-i sel">邮件润色</div><div class="dp-i">翻译成英文</div><div class="dp-i">总结要点</div></div></div>` },
    { kicker: "第 2 步 · 变量", title: "用 {{变量}} 把提示词变成表单",
      text: "需要每次替换的地方写成 {{变量}}。工具栏的「插入变量」可以一键插入单行、多行、数字、下拉等写法；插入时如果有必填项，浮框会先让你填表。",
      demo: `<div class="onb-demo demo-split"><div class="demo-code">把下面的内容翻译成<span class="v">{{语言:英文/日文|英文}}</span>，语气<span class="v">{{语气|正式}}</span>：\n<span class="v">{{原文:多行}}</span></div>
        <div class="demo-form"><div class="df"><div class="df-l">语言 <span class="tag ctl">下拉</span></div><div class="df-c">英文 ▾</div></div><div class="df"><div class="df-l">语气 <span class="tag opt">可选</span></div><div class="df-c">默认：正式</div></div><div class="df"><div class="df-l">原文 <span class="tag req">必填</span></div><div class="df-c" style="height:38px">请输入原文</div></div></div></div>` },
    { kicker: "第 3 步 · 调试", title: "预览和调试，确认无误再用",
      text: "右侧「预览」用颜色标出每个变量填进去的内容；「调试」会检查括号不配对、变量冲突、必填未填写等问题，点一下就能跳到出错位置。「一键试填示例值」可以快速看效果。",
      demo: `<div class="onb-demo demo-issues"><div class="issue error"><span class="lv">${I("alert", 14)}</span><span>第 3 行的 {{原文 缺少右括号 }}</span><span class="loc">L3:1</span></div>
        <div class="issue warn"><span class="lv">${I("alert", 14)}</span><span>必填变量「原文」未填写</span></div>
        <div class="ok-box" style="margin-top:8px">${I("check", 16)}修好后：体检通过 · 语法与语义均无问题，可以直接使用</div></div>` },
  ];
  let onbStep = 0;
  function renderOnb() {
    const s = ONB[onbStep];
    $("#onbStage").innerHTML = `<div class="onb-step onb"><div class="onb-kicker">${s.kicker}</div><h2 id="onbTitle">${esc(s.title)}</h2><p>${esc(s.text)}</p>${s.demo}</div>`;
    $("#onbDots").innerHTML = ONB.map((_, i) => `<span class="${i === onbStep ? "on" : ""}"></span>`).join("");
    $("#onbPrev").classList.toggle("hidden", onbStep === 0);
    $("#onbSkip").classList.toggle("hidden", onbStep === ONB.length - 1);
    $("#onbNext").textContent = onbStep === ONB.length - 1 ? "开始使用" : "下一步";
  }
  function openOnboarding() { onbStep = 0; renderOnb(); openModal("onbOverlay", "#onbNext"); }
  MODAL_CLOSE.onbOverlay = () => call("complete_onboarding");
  $("#onbNext").onclick = () => { if (onbStep < ONB.length - 1) { onbStep++; renderOnb(); $("#onbNext").focus(); } else closeModal("onbOverlay"); };
  $("#onbPrev").onclick = () => { if (onbStep > 0) { onbStep--; renderOnb(); } };
  $("#onbSkip").onclick = () => closeModal("onbOverlay");
  $("#onbOverlay").addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") { e.preventDefault(); $("#onbNext").click(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); $("#onbPrev").click(); }
  });


  $("#copyBuiltinBtn")?.addEventListener("click", () => { if (S.cur) copyBuiltin(S.cur.id); });

  // ---------------------------------------------------------------- lifecycle (2.7)
  function syncFlagsUI() {
    const p = S.cur || {};
    const fav = $("#favBtn"), pin = $("#pinBtn"), arch = $("#archBtn");
    if (fav) { fav.setAttribute("aria-pressed", p.favorite ? "true" : "false"); fav.title = p.favorite ? "取消收藏" : "收藏"; }
    if (pin) {
      pin.setAttribute("aria-pressed", p.pinned ? "true" : "false");
      pin.title = p.pinned ? "取消置顶" : "置顶（浮框优先）";
      pin.innerHTML = p.pinned ? `${I("pin", 14)}取消置顶` : `${I("pin", 14)}置顶`;
    }
    if (arch) arch.innerHTML = p.archived ? `${I("undo", 14)}恢复` : `${I("archive", 14)}归档`;
  }

  /* 2.12.1 t57u: editor 关键词 row removed; keywords[] still used for search / AI import */
  function renderKwUI() { /* no-op: no #kwRow */ }
  async function persistKeywords(keywords) {
    if (!S.cur || S.cur.builtin) return;
    const r = await call("set_keywords", S.cur.id, keywords);
    if (r && r.ok) { S.cur.keywords = r.prompt.keywords || []; refreshList(); }
  }

  function renderTagsUI() {
    const row = $("#tagsRow"); if (row && S.cur) row.hidden = false;
    const mr = $("#metaRow"); if (mr && S.cur) mr.hidden = false;
    const chips = $("#tagsChips"); if (!chips || !S.cur) return;
    const tags = S.cur.tags || [];
    const ro = !!S.cur.builtin;
    chips.innerHTML = tags.map((tg) => `<span class="tag-chip">${esc(tg)}${ro ? "" : `<button data-rm-tag="${esc(tg)}" aria-label="移除标签">${I("x", 10)}</button>`}</span>`).join("");
    const tin = $("#tagsInput"); if (tin) { tin.hidden = ro; tin.disabled = ro; }
  }
  async function persistTags(tags) {
    if (!S.cur) return;
    const r = await call("set_tags", S.cur.id, tags);
    if (r && r.ok) { S.cur.tags = r.prompt.tags || []; S.tags = r.tags || S.tags; renderTagsUI(); renderTagBar(); refreshList(); }
  }
  $("#tagsChips")?.addEventListener("click", (e) => {
    const t = e.target.closest("[data-rm-tag]")?.dataset.rmTag; if (!t || !S.cur) return;
    persistTags((S.cur.tags || []).filter((x) => x !== t));
  });
  $("#tagsInput")?.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || !S.cur) return;
    e.preventDefault();
    const v = ($("#tagsInput").value || "").trim(); if (!v) return;
    $("#tagsInput").value = "";
    const tags = [...(S.cur.tags || [])];
    if (!tags.some((t) => t.toLowerCase() === v.toLowerCase())) tags.push(v);
    persistTags(tags);
  });
  async function toggleFavorite(id) {
    const p = S.list.find((x) => x.id === id) || (S.cur && S.cur.id === id ? S.cur : null);
    if (!p) return;
    const r = await call("set_favorite", id, !p.favorite);
    if (r && r.ok) {
      if (S.cur && S.cur.id === id) { S.cur.favorite = r.prompt.favorite; syncFlagsUI(); }
      refreshList();
    }
  }
  $("#favBtn")?.addEventListener("click", () => S.cur && toggleFavorite(S.cur.id));
  $("#pinBtn")?.addEventListener("click", async () => {
    if (!S.cur) return;
    const r = await call("set_pinned", S.cur.id, !S.cur.pinned);
    if (r && r.ok) { S.cur.pinned = r.prompt.pinned; syncFlagsUI(); refreshList(); toast(S.cur.pinned ? "已置顶" : "已取消置顶", { type: "info", ms: 1400 }); }
  });
  $("#archBtn")?.addEventListener("click", async () => {
    if (!S.cur) return;
    if (S.cur.archived) {
      const r = await call("unarchive_prompt", S.cur.id);
      if (r && r.ok) { toast("已从归档恢复"); setLibScope("all"); await refreshList(); openPrompt(S.cur.id); }
    } else {
      const ok = await confirmDialog({ title: "归档此提示词？", message: "归档后不会出现在 // 浮框中，可在「归档」页签里恢复。", ok: "归档" });
      if (!ok) return;
      await flushSave();
      const r = await call("archive_prompt", S.cur.id);
      if (r && r.ok) { toast("已归档", { action: "撤销", onAction: async () => { await call("unarchive_prompt", S.cur.id); refreshList(); } }); S.cur = null; await refreshList(); showEmptyEditor(); }
    }
  });

  function renderTagBar() {
    const bar = $("#tagBar"); if (!bar) return;
    if (!S.tags.length && !S.tag) { bar.hidden = true; return; }
    bar.hidden = false;
    bar.innerHTML = `<button class="tag-chip${!S.tag ? " active" : ""}" data-tag="">全部</button>` +
      S.tags.map((t) => `<button class="tag-chip${S.tag === t ? " active" : ""}" data-tag="${esc(t)}">${esc(t)}</button>`).join("");
  }
  $("#tagBar")?.addEventListener("click", (e) => {
    const t = e.target.closest("[data-tag]"); if (!t) return;
    S.tag = t.dataset.tag || "";
    refreshList();
  });
  $("#sortSel")?.addEventListener("change", async (e) => {
    const ALLOWED_SORT = new Set(["recent", "updated", "name"]);
    let v = e.target.value;
    if (!ALLOWED_SORT.has(v)) { v = "recent"; e.target.value = v; }
    S.sort = v;
    await saveSettings({ library_sort: S.sort });
    refreshList();
  });
  function syncLibScopeUI() {
    const mode = S.archivedOnly ? "archived" : (S.favOnly ? "fav" : "all");
    [["libScopeAll", "all"], ["libScopeFav", "fav"], ["libScopeArch", "archived"]].forEach(([id, key]) => {
      const el = document.getElementById(id); if (!el) return;
      const on = mode === key;
      el.setAttribute("aria-selected", on ? "true" : "false");
      el.tabIndex = on ? 0 : -1;
    });
  }
  function setLibScope(scope) {
    const wantFav = scope === "fav";
    const wantArch = scope === "archived";
    if (S.favOnly === wantFav && S.archivedOnly === wantArch) { syncLibScopeUI(); return refreshList(); }
    S.favOnly = wantFav;
    S.archivedOnly = wantArch;
    syncLibScopeUI();
    refreshList();
  }
  $("#libScope")?.addEventListener("click", (e) => {
    const tab = e.target.closest("[data-scope]"); if (!tab) return;
    setLibScope(tab.dataset.scope);
  });
  $("#libScope")?.addEventListener("keydown", (e) => {
    const tabs = [...document.querySelectorAll("#libScope [role='tab']")];
    if (!tabs.length) return;
    const cur = tabs.findIndex((t) => t.getAttribute("aria-selected") === "true");
    let next = cur;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (cur + 1) % tabs.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = (cur - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    else return;
    e.preventDefault();
    tabs[next].focus();
    setLibScope(tabs[next].dataset.scope);
  });

  function renderStarters() {
    const el = $("#starters"); if (!el) return;
    if (!S.starters || !S.starters.length) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = `<div class="starters-head"><span>${I("sparkles", 12)}从模板开始</span><span class="spacer"></span>
      <button class="btn ghost sm" id="startersDismiss" title="关闭模板条">不再显示</button></div>` +
      S.starters.map((st) => `<button class="starter-item" data-starter="${esc(st.id)}"><span class="st-name">${esc(st.name)}</span>
        <span class="st-tags">${esc((st.tags || []).join(" · "))}</span></button>`).join("");
  }
  $("#starters")?.addEventListener("click", async (e) => {
    if (e.target.closest("#startersDismiss")) {
      await call("dismiss_starters"); S.starters = []; renderStarters(); return;
    }
    const id = e.target.closest("[data-starter]")?.dataset.starter; if (!id) return;
    const r = await call("create_from_starter", id);
    if (r && r.ok) { toast(`已创建「${r.prompt.name}」`); await refreshList(); openPrompt(r.prompt.id); }
  });

  async function openRevisions() {
    if (!S.cur) return;
    await flushSave();
    S.revSel = null;
    openModal("revOverlay", "#revSave");
    await renderRevisions();
  }
  async function renderRevisions() {
    const list = (await call("list_revisions", S.cur.id)) || [];
    const el = $("#revList");
    if (!list.length) {
      el.innerHTML = emptyState("history", "还没有版本", "保存提示词时会自动留快照，也可点「保存当前版本」。");
      $("#revDetail").innerHTML = "";
      return;
    }
    if (!S.revSel || !list.find((r) => r.id === S.revSel)) S.revSel = list[0].id;
    if (!S.revChecks) S.revChecks = new Set();
    S.revChecks = new Set([...S.revChecks].filter((id) => list.find((r) => r.id === id)));
    el.innerHTML = list.map((r) => `<div class="rev-item${r.id === S.revSel ? " active" : ""}" data-rid="${esc(r.id)}">
      <label class="rev-check" onclick="event.stopPropagation()"><input type="checkbox" data-rev-check="${esc(r.id)}" ${S.revChecks.has(r.id) ? "checked" : ""}></label>
      <div class="rev-item-body"><div>${esc(r.name)}</div><div class="rev-meta">${esc(relTime(r.saved_at))} · ${r.source === "manual" ? "手动" : "自动"}${r.note ? " · " + esc(r.note) : ""}</div></div></div>`).join("");
    el.querySelectorAll("[data-rev-check]").forEach((cb) => {
      cb.addEventListener("change", () => {
        if (cb.checked) S.revChecks.add(cb.dataset.revCheck); else S.revChecks.delete(cb.dataset.revCheck);
        if (S.revChecks.size > 2) {
          const first = [...S.revChecks][0];
          S.revChecks.delete(first);
          const oldCb = el.querySelector(`[data-rev-check="${first}"]`);
          if (oldCb) oldCb.checked = false;
        }
      });
    });
    const rev = list.find((r) => r.id === S.revSel);
    $("#revDetail").innerHTML = rev ? `<div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
      <button class="btn primary sm" id="revRestore">还原此版本</button>
      <button class="btn secondary sm" id="revDiff">与当前对比</button>
      <button class="btn ghost sm" id="revDel">删除快照</button></div>
      <pre>${esc(rev.body)}</pre>` : "";
    $("#revRestore")?.addEventListener("click", async () => {
      const ok = await confirmDialog({ title: "还原此版本？", message: "当前正文会先自动保存一份快照，再还原所选版本。", ok: "还原" });
      if (!ok) return;
      const r = await call("restore_revision", S.cur.id, S.revSel);
      if (r && r.ok) { S.cur = r.prompt; title.value = r.prompt.name; syncTitleWidth(); editor.value = r.prompt.body; S.dirty = false; setSaveState("saved");
        syncFlagsUI(); renderTagsUI(); renderKwUI();
        S.mmResults = (r.prompt.last_ai_run && r.prompt.last_ai_run.results) ? r.prompt.last_ai_run.results.map((x) => ({ ...x })) : null;
        S.mmAt = (r.prompt.last_ai_run && r.prompt.last_ai_run.at) || "";
        S.mmRendered = (r.prompt.last_ai_run && r.prompt.last_ai_run.rendered_preview) || "";
        runAnalyze.flush(); toast("已还原版本"); closeModal("revOverlay"); refreshList(); }
    });
    $("#revDiff")?.addEventListener("click", () => openDiff(S.revSel, "current"));
    $("#revDel")?.addEventListener("click", async () => {
      const r = await call("delete_revision", S.cur.id, S.revSel);
      if (r && r.ok) { toast("已删除快照", { type: "info" }); S.revSel = null; renderRevisions(); }
    });
  }
  $("#revList")?.addEventListener("click", (e) => {
    const id = e.target.closest("[data-rid]")?.dataset.rid; if (!id) return;
    S.revSel = id; renderRevisions();
  });
  $("#revBtn")?.addEventListener("click", openRevisions);
  $("#revSave")?.addEventListener("click", async () => {
    if (!S.cur) return;
    await flushSave();
    const r = await call("save_revision", S.cur.id, "");
    if (r && r.ok) { toast("已保存版本"); renderRevisions(); }
    else toast((r && r.error) || "保存失败", { type: "error" });
  });

  let _lastDiff = null;
  function paintDiffView() {
    const r = _lastDiff; if (!r) return;
    const mode = S.diffMode || "unified";
    $$("#diffModeSeg button").forEach((b) => b.classList.toggle("active", b.dataset.diffMode === mode));
    const head = `<div class="muted small" style="margin-bottom:8px">${esc(r.a.name)} @ ${esc(relTime(r.a.saved_at))} → ${esc(r.b.name)} @ ${esc(relTime(r.b.saved_at))} · 名称${r.name_changed ? "有变更" : "相同"}</div>`;
    if (mode === "split") {
      const left = [], right = [];
      const lines = r.combined_diff || r.diff || [];
      for (const d of lines) {
        if (d.op === "eq") { left.push(`<div class="diff-line eq">  ${esc(d.text)}</div>`); right.push(`<div class="diff-line eq">  ${esc(d.text)}</div>`); }
        else if (d.op === "del") { left.push(`<div class="diff-line del">− ${esc(d.text)}</div>`); right.push(`<div class="diff-line pad">&nbsp;</div>`); }
        else if (d.op === "ins") { left.push(`<div class="diff-line pad">&nbsp;</div>`); right.push(`<div class="diff-line ins">+ ${esc(d.text)}</div>`); }
      }
      $("#diffBody").innerHTML = head + `<div class="diff-split"><div class="diff-pane"><div class="diff-pane-h">旧</div>${left.join("") || "<div class='muted'>无</div>"}</div><div class="diff-pane"><div class="diff-pane-h">新</div>${right.join("") || "<div class='muted'>无</div>"}</div></div>`;
    } else {
      const ud = r.combined_diff || r.diff || [];
      $("#diffBody").innerHTML = head + `<div class="diff-view">${ud.map((d) => `<div class="diff-line ${d.op}">${d.op === "del" ? "− " : d.op === "ins" ? "+ " : "  "}${esc(d.text)}</div>`).join("") || "<div class='muted'>无差异</div>"}</div>`;
    }
  }
  async function openDiff(a, b) {
    if (!S.cur) return;
    const r = await call("compare_revisions", S.cur.id, a, b);
    if (!r || !r.ok) return toast((r && r.error) || "对比失败", { type: "error" });
    _lastDiff = r;
    openModal("diffOverlay");
    paintDiffView();
  }
  $("#diffModeSeg")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-diff-mode]"); if (!b) return;
    S.diffMode = b.dataset.diffMode; paintDiffView();
  });
  $("#revCompareSel")?.addEventListener("click", () => {
    if (!S.cur) return;
    const ids = [...(S.revChecks || [])];
    if (ids.length === 2) return openDiff(ids[0], ids[1]);
    if (ids.length === 1) return openDiff(ids[0], "current");
    if (S.revSel) return openDiff(S.revSel, "current");
    toast("请勾选 1～2 个版本再对比", { type: "warn" });
  });

  $("#setSort")?.addEventListener("change", async (e) => {
    const ALLOWED_SORT = new Set(["recent", "updated", "name"]);
    let v = e.target.value;
    if (!ALLOWED_SORT.has(v)) v = "recent";
    S.sort = v; await saveSettings({ library_sort: S.sort });
    const sel = $("#sortSel"); if (sel) sel.value = S.sort; refreshList();
  });
  $("#setBackup")?.addEventListener("click", () => runIO("backup"));
  $("#setRestore")?.addEventListener("click", () => runIO("restore"));


  // ---------------------------------------------------------------- AI workshop (2.11)
  const AI = { tab: "gen", presets: [], profiles: [], defaultId: "", busy: false };

  async function loadAiData() {
    const [pres, prof] = await Promise.all([call("list_ai_presets"), call("list_ai_profiles")]);
    AI.presets = (pres && Array.isArray(pres) ? pres : (pres && pres.presets) || []) || [];
    if (Array.isArray(pres)) AI.presets = pres;
    if (prof && prof.ok) {
      AI.profiles = prof.profiles || [];
      AI.defaultId = prof.default_profile || (AI.profiles[0] && AI.profiles[0].id) || "";
    }
  }

  function aiProfileOptions(selected) {
    const list = AI.profiles.filter((p) => p.has_key);
    if (!list.length) return `<option value="">（请先在设置中配置 API Key）</option>`;
    return list.map((p) => {
      const models = (p.models && p.models.length) ? p.models : [p.default_model].filter(Boolean);
      return models.map((m) => {
        const v = `${p.id}||${m}`;
        const sel = selected === v || (!selected && p.id === AI.defaultId && m === (p.default_model || models[0])) ? " selected" : "";
        return `<option value="${esc(v)}"${sel}>${esc(p.name)} · ${esc(m)}</option>`;
      }).join("");
    }).join("");
  }

  function parseTarget(v) {
    const [profile_id, model] = String(v || "").split("||");
    return { profile_id, model };
  }

  async function renderAiProfiles() {
    const el = $("#aiProvList"); if (!el) return;
    await loadAiData();
    if (!AI.profiles.length) {
      el.innerHTML = `<div class="note">尚未添加厂商。点击「添加厂商」选择 OpenAI / 通义 / DeepSeek / OpenRouter 等，并填入 API Key。</div>`;
      return;
    }
    el.innerHTML = AI.profiles.map((p) => {
      const def = p.id === AI.defaultId ? `<span class="sys-badge">默认</span>` : "";
      return `<div class="ai-prov-row" data-pid="${esc(p.id)}">
        <div>
          <div><b>${esc(p.name)}</b> ${def} <span class="meta">${esc(p.kind)} · ${esc(p.preset || "")}</span></div>
          <div class="meta">${esc(p.base_url || "（未设 Base URL）")}</div>
          <div class="meta">Key：${p.has_key ? esc(p.api_key_masked || "已保存") : "未设置"} · 默认模型：${esc(p.default_model || "—")}</div>
          <div class="meta">模型：${esc((p.models || []).join(", ") || "—")}</div>
        </div>
        <div class="about-actions" style="flex-direction:column">
          <button class="btn ghost sm" data-ai-edit="${esc(p.id)}">编辑</button>
          <button class="btn ghost sm" data-ai-def="${esc(p.id)}" ${p.id === AI.defaultId ? "disabled" : ""}>设默认</button>
          <button class="btn ghost sm danger" data-ai-del="${esc(p.id)}">删除</button>
        </div>
      </div>`;
    }).join("");
  }

  async function aiEditProfile(existing) {
    await loadAiData();
    const presets = AI.presets.length ? AI.presets : await call("list_ai_presets") || [];
    AI.presets = Array.isArray(presets) ? presets : [];
    const isNew = !existing;
    const presetOpts = AI.presets.map((pr) =>
      `<option value="${esc(pr.id)}" ${(existing ? existing.preset : "openai") === pr.id ? "selected" : ""}>${esc(pr.name)}</option>`).join("");
    let models = Array.isArray(existing && existing.models) ? existing.models.slice() : [];
    let defModel = (existing && existing.default_model) || "";
    const body = document.createElement("div");
    body.innerHTML = `<div class="ai-col" style="gap:10px">
      <label>厂商预设</label><select class="input" id="aipPreset">${presetOpts}</select>
      <label>显示名称</label><input class="input" id="aipName" value="${esc(existing ? existing.name : "")}" placeholder="例如：我的 DeepSeek">
      <label>Base URL</label><input class="input" id="aipUrl" value="${esc(existing ? existing.base_url : "")}" placeholder="https://api.example.com/v1">
      <label>API Key ${existing && existing.has_key ? "（留空则保留原 Key）" : ""}</label>
      <input class="input" id="aipKey" type="password" placeholder="${existing && existing.has_key ? "•••• 已保存" : "sk-..."}" autocomplete="off">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <label style="margin:0">模型列表</label>
        <button type="button" class="btn secondary sm" id="aipFetchModels"><i class="ic" data-icon="refresh" data-size="12"></i>拉取模型</button>
        <span class="meta" id="aipModelsStatus" style="font-size:11px;color:var(--muted)"></span>
      </div>
      <div class="chips" id="aipModelsChips" style="min-height:28px"></div>
      <div style="display:flex;gap:6px;align-items:center">
        <input class="input" id="aipModelAdd" placeholder="手动添加模型 id" style="flex:1;min-width:0">
        <button type="button" class="btn secondary sm" id="aipModelAddBtn">添加</button>
      </div>
      <label>默认模型</label><select class="input" id="aipDefModel"></select>
    </div>`;
    const wrap = document.createElement("div");
    wrap.className = "overlay";
    wrap.innerHTML = `<div class="modal" role="dialog" aria-modal="true"><div class="modal-head"><h2>${isNew ? "添加厂商" : "编辑厂商"}</h2><span class="spacer"></span><button class="btn ghost icon" data-x aria-label="关闭"><i class="ic" data-icon="x"></i></button></div><div class="modal-body"></div><div class="modal-foot"><span class="spacer"></span><button class="btn ghost sm" data-x>取消</button><button class="btn primary sm" data-ok>保存</button></div></div>`;
    wrap.querySelector(".modal-body").appendChild(body);
    document.body.appendChild(wrap);
    window.PBIcons.fill(wrap);

    const statusEl = () => body.querySelector("#aipModelsStatus");
    const syncDefSelect = () => {
      const sel = body.querySelector("#aipDefModel");
      const opts = models.length ? models : [];
      sel.innerHTML = opts.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("")
        || `<option value="">（暂无模型）</option>`;
      if (defModel && opts.includes(defModel)) sel.value = defModel;
      else if (opts.length) { defModel = opts[0]; sel.value = defModel; }
      else { defModel = ""; }
    };
    const renderChips = () => {
      const box = body.querySelector("#aipModelsChips");
      box.innerHTML = models.length
        ? models.map((m) => `<span class="chip" data-model="${esc(m)}">${esc(m)}<button type="button" title="移除" aria-label="移除 ${esc(m)}">×</button></span>`).join("")
        : `<span class="meta" style="font-size:12px;color:var(--faint)">暂无模型 — 可拉取或手动添加</span>`;
      syncDefSelect();
    };
    const setModels = (list, preferred) => {
      const seen = new Set();
      models = [];
      for (const m of list || []) {
        const id = String(m || "").trim();
        if (!id || seen.has(id)) continue;
        seen.add(id);
        models.push(id);
        if (models.length >= 80) break;
      }
      if (preferred && models.includes(preferred)) defModel = preferred;
      else if (!models.includes(defModel)) defModel = models[0] || "";
      renderChips();
    };
    const currentPreset = () => AI.presets.find((x) => x.id === body.querySelector("#aipPreset").value);

    const applyPreset = (forceModels) => {
      const pr = currentPreset();
      if (!pr) return;
      if (isNew || !body.querySelector("#aipName").value.trim()) body.querySelector("#aipName").value = pr.name;
      body.querySelector("#aipUrl").value = pr.base_url || "";
      body.dataset.kind = pr.kind || "openai";
      // Always clear to preset defaults on change (fixes gpt-4o sticking on DeepSeek)
      if (forceModels || isNew) setModels(pr.models || [], (pr.models || [])[0] || "");
    };

    const fetchModels = async ({ silent } = {}) => {
      const st = statusEl();
      st.textContent = "拉取中…";
      const payload = {
        kind: body.dataset.kind || "openai",
        base_url: body.querySelector("#aipUrl").value.trim(),
        api_key: body.querySelector("#aipKey").value,
        preset: body.querySelector("#aipPreset").value,
        profile_id: existing ? existing.id : "",
      };
      const r = await call("list_ai_models", payload);
      if (!r || !r.ok) {
        const pr = currentPreset();
        if (pr && (pr.models || []).length) {
          setModels(pr.models, (pr.models || [])[0]);
          st.textContent = (r && r.error ? `拉取失败：${r.error}；` : "拉取失败；") + "已使用预设模型";
        } else {
          st.textContent = (r && r.error) || "拉取失败";
        }
        if (!silent) toast(st.textContent, { type: "warn" });
        return false;
      }
      setModels(r.models || [], defModel);
      st.textContent = r.source === "preset"
        ? `已使用预设（${(r.models || []).length}）`
        : `已拉取 ${(r.models || []).length} 个模型`;
      return true;
    };

    body.querySelector("#aipPreset").onchange = () => {
      applyPreset(true);
      const key = body.querySelector("#aipKey").value.trim();
      const url = body.querySelector("#aipUrl").value.trim();
      if (key || (existing && existing.has_key)) {
        if (url || (currentPreset() && currentPreset().kind !== "openai")) fetchModels({ silent: true });
      } else {
        statusEl().textContent = "可填写 Key 后拉取最新模型列表";
      }
    };
    body.querySelector("#aipFetchModels").onclick = () => fetchModels();
    body.querySelector("#aipModelsChips").addEventListener("click", (e) => {
      const btn = e.target.closest("button");
      const chip = e.target.closest("[data-model]");
      if (!btn || !chip) return;
      setModels(models.filter((m) => m !== chip.dataset.model), defModel);
    });
    body.querySelector("#aipModelAddBtn").onclick = () => {
      const inp = body.querySelector("#aipModelAdd");
      const id = (inp.value || "").trim();
      if (!id) return;
      if (!models.includes(id)) setModels(models.concat([id]), defModel || id);
      inp.value = "";
    };
    body.querySelector("#aipDefModel").onchange = () => { defModel = body.querySelector("#aipDefModel").value; };

    if (isNew) applyPreset(true);
    else {
      body.dataset.kind = existing.kind || "openai";
      setModels(models.length ? models : ((currentPreset() || {}).models || []), defModel);
      if (existing.has_key) fetchModels({ silent: true });
    }

    const done = await new Promise((resolve) => {
      wrap.addEventListener("click", async (e) => {
        if (e.target.closest("[data-x]")) { wrap.remove(); resolve(false); return; }
        if (e.target.closest("[data-ok]")) {
          defModel = body.querySelector("#aipDefModel").value.trim() || models[0] || "";
          const payload = {
            id: existing ? existing.id : "",
            name: body.querySelector("#aipName").value.trim(),
            preset: body.querySelector("#aipPreset").value,
            kind: body.dataset.kind || "openai",
            base_url: body.querySelector("#aipUrl").value.trim(),
            api_key: body.querySelector("#aipKey").value,
            models: models.slice(),
            default_model: defModel,
            make_default: (function () {
              if (isNew) return !AI.defaultId || AI.profiles.length === 0;
              if (existing && existing.id === AI.defaultId) return true;
              return false;
            })(),
          };
          const r = await call("save_ai_profile", payload);
          wrap.remove();
          if (!r || !r.ok) { toast((r && r.error) || "保存失败", { type: "error" }); resolve(false); return; }
          toast(isNew ? "已添加厂商" : "已更新");
          resolve(true);
        }
      });
    });
    if (done) await renderAiProfiles();
  }

  const aiAddBtn = $("#aiAddProfile");
  if (aiAddBtn) aiAddBtn.onclick = () => aiEditProfile(null);
  const aiProvList = $("#aiProvList");
  if (aiProvList) aiProvList.addEventListener("click", async (e) => {
    const edit = e.target.closest("[data-ai-edit]");
    const del = e.target.closest("[data-ai-del]");
    const def = e.target.closest("[data-ai-def]");
    if (edit) {
      await loadAiData();
      const p = AI.profiles.find((x) => x.id === edit.dataset.aiEdit);
      if (p) aiEditProfile(p);
    } else if (del) {
      const ok = await confirmDialog({ title: "删除厂商配置？", message: "将删除该 API Key 配置（不可恢复）。", ok: "删除", danger: true });
      if (!ok) return;
      await call("delete_ai_profile", del.dataset.aiDel);
      await renderAiProfiles();
      toast("已删除", { type: "info" });
    } else if (def) {
      await call("set_ai_default_profile", def.dataset.aiDef);
      AI.defaultId = def.dataset.aiDef;
      await renderAiProfiles();
    }
  });

  function setAiStatus(msg, ok) {
    const el = $("#aiStatus"); if (!el) return;
    el.textContent = msg || "";
    el.style.color = ok === false ? "var(--danger)" : "";
  }

  function renderAiBody() {
    const body = $("#aiBody"), foot = $("#aiFoot");
    if (!body) return;
    const curBody = (S.cur && S.cur.body) || (editor && editor.value) || "";
    if (AI.tab === "gen") {
      body.innerHTML = `<div class="ai-layout">
        <div class="ai-col">
          <label>目标描述 *</label>
          <textarea id="aiGoal" class="input" placeholder="描述要生成的提示词。可顺带写使用场景、约束、输出格式、需要的变量等"></textarea>
        </div>
        <div class="ai-col">
          <label>生成结果</label>
          <div class="ai-out" id="aiOut" contenteditable="false"></div>
          <div class="ai-meta" id="aiMeta"></div>
        </div>
      </div>`;
      foot.innerHTML = `<span class="muted small" id="aiStatus"></span><span class="spacer"></span>
        <button class="btn secondary sm" id="aiRun" ${AI.busy ? "disabled" : ""}>生成模板</button>
        <button class="btn ghost sm" id="aiApplyCur" disabled>写入当前提示词</button>
        <button class="btn primary sm" id="aiApplyNew" disabled>新建提示词</button>`;
    } else if (AI.tab === "rewrite") {
      body.innerHTML = `<div class="ai-layout">
        <div class="ai-col">
          <label>原文</label><textarea id="aiSrc" class="input">${esc(curBody)}</textarea>
          <label>改写要求</label><input class="input" id="aiInstr" value="结构更清晰，变量与输出格式更专业">
        </div>
        <div class="ai-col">
          <label>改写结果</label><div class="ai-out" id="aiOut"></div>
          <div class="ai-meta" id="aiMeta"></div>
        </div>
      </div>`;
      foot.innerHTML = `<span class="muted small" id="aiStatus"></span><span class="spacer"></span>
        <button class="btn secondary sm" id="aiRun">开始改写</button>
        <button class="btn primary sm" id="aiApplyCur" disabled>替换当前正文</button>`;
    } else if (AI.tab === "review") {
      body.innerHTML = `<div class="ai-layout">
        <div class="ai-col">
          <label>待评审正文</label><textarea id="aiSrc" class="input">${esc(curBody)}</textarea>
        </div>
        <div class="ai-col">
          <label>评审意见</label><div class="ai-out" id="aiOut"></div>
          <div class="ai-meta" id="aiMeta"></div>
        </div>
      </div>`;
      foot.innerHTML = `<span class="muted small" id="aiStatus"></span><span class="spacer"></span>
        <button class="btn primary sm" id="aiRun">开始评审</button>`;
    } else {
      // 并行测已并入右侧「调试」多模型试跑（2.12.1）
      AI.tab = "gen";
      $$("#aiTabs button").forEach((b) => b.classList.toggle("active", b.dataset.ai === "gen"));
      return renderAiBody();
    }
    window.PBIcons.fill(foot);
    const run = $("#aiRun");
    if (run) run.onclick = () => aiRun();
    const ac = $("#aiApplyCur"); if (ac) ac.onclick = () => aiApply(false);
    const an = $("#aiApplyNew"); if (an) an.onclick = () => aiApply(true);
    const pick = $("#aiModelPick");
    if (pick) pick.addEventListener("change", (e) => {
      const lab = e.target.closest("label");
      if (lab) lab.classList.toggle("on", e.target.checked);
    });
  }

  function resolveDefaultAiTarget() {
    const pid = AI.defaultId || ((AI.profiles || [])[0] && (AI.profiles || [])[0].id) || "";
    const p = (AI.profiles || []).find((x) => x.id === pid) || (AI.profiles || [])[0];
    if (!p) {
      toast("请先在设置中配置 AI 模型", { type: "warn", action: "去设置", onAction: () => openSettings("ai") });
      return null;
    }
    const model = p.default_model || (p.models && p.models[0]) || "";
    if (!model) {
      toast("请先在设置中为默认厂商选择模型", { type: "warn", action: "去设置", onAction: () => openSettings("ai") });
      return null;
    }
    return { profile_id: p.id, model, label: `${p.name || p.id} · ${model}` };
  }

  let _aiLastText = "";
  async function aiRun() {
    if (AI.busy) return;
    await loadAiData();
    const t = resolveDefaultAiTarget();
    if (!t) return;
    AI.busy = true;
    setAiStatus("请求中…");
    try {
      if (AI.tab === "gen") {
        const r = await call("ai_generate", $("#aiGoal").value, "", "", t.profile_id, t.model);
        if (!r || !r.ok) { setAiStatus((r && r.error) || "生成失败", false); return; }
        _aiLastText = r.text || "";
        $("#aiOut").textContent = _aiLastText;
        $("#aiMeta").textContent = `${r.label || r.model || t.label} · ${r.latency_ms || 0} ms`;
        ["aiApplyCur", "aiApplyNew"].forEach((id) => { const b = $("#" + id); if (b) b.disabled = !_aiLastText; });
        setAiStatus("生成完成");
      } else if (AI.tab === "rewrite") {
        const r = await call("ai_rewrite", $("#aiSrc").value, $("#aiInstr").value, t.profile_id, t.model);
        if (!r || !r.ok) { setAiStatus((r && r.error) || "改写失败", false); return; }
        _aiLastText = r.text || "";
        $("#aiOut").textContent = _aiLastText;
        $("#aiMeta").textContent = `${r.model || t.model} · ${r.latency_ms || 0} ms`;
        const b = $("#aiApplyCur"); if (b) b.disabled = !_aiLastText;
        setAiStatus("改写完成 — 可对照左侧原文");
      } else if (AI.tab === "review") {
        const r = await call("ai_review", $("#aiSrc").value, t.profile_id, t.model);
        if (!r || !r.ok) { setAiStatus((r && r.error) || "评审失败", false); return; }
        $("#aiOut").textContent = r.text || "";
        $("#aiMeta").textContent = `${r.model || t.model} · ${r.latency_ms || 0} ms`;
        setAiStatus("评审完成");
      } else {
        setAiStatus("请使用右侧「调试」页的多模型试跑", false);
      }
    } finally {
      AI.busy = false;
    }
  }

  function parseAiMeta(text) {
    /* Extract 标题/关键词 header lines from AI generate output. */
    const lines = String(text || "").replace(/^\uFEFF/, "").split(/\r?\n/);
    let name = "", keywords = [], bodyStart = 0;
    for (let i = 0; i < Math.min(lines.length, 8); i++) {
      const ln = lines[i].trim();
      if (!ln) { if (name || keywords.length) { bodyStart = i + 1; break; } continue; }
      const mTitle = ln.match(/^(?:标题|Title)\s*[:：]\s*(.+)$/i);
      const mKw = ln.match(/^(?:关键词|Keywords?)\s*[:：]\s*(.+)$/i);
      if (mTitle) { name = mTitle[1].trim().replace(/^[【\[]|[】\]]$/g, "").slice(0, 40); bodyStart = i + 1; continue; }
      if (mKw) {
        keywords = mKw[1].split(/[,，;；|/]/).map((x) => x.trim()).filter(Boolean).slice(0, 12);
        bodyStart = i + 1; continue;
      }
      if (name || keywords.length) { bodyStart = i; break; }
      break;
    }
    while (bodyStart < lines.length && !lines[bodyStart].trim()) bodyStart++;
    return { name, keywords, body: lines.slice(bodyStart).join("\n").trim() || String(text || "").trim() };
  }

  async function aiApply(asNew) {
    if (!_aiLastText) return;
    const meta = AI.tab === "gen" ? parseAiMeta(_aiLastText) : { name: "", keywords: [], body: _aiLastText };
    const bodyText = meta.body || _aiLastText;
    if (asNew) {
      const suggested = meta.name || "AI 生成的模板";
      const name = prompt("新提示词名称", suggested) || suggested;
      const r = await call("create_prompt", name, bodyText, S.activeRole || "", "", meta.keywords || [], "");
      if (r && r.id) {
        closeAiDrawer();
        await refreshList();
        await openPrompt(r.id);
        toast(meta.keywords && meta.keywords.length ? "已新建（含关键词）" : "已新建提示词");
      } else toast((r && r.error) || "创建失败", { type: "error" });
      return;
    }
    if (!S.cur) { toast("没有打开的提示词", { type: "warn" }); return; }
    if (S.cur.builtin) {
      const go = await confirmDialog({ title: "内置提示词只读", message: "将复制为可编辑副本再写入改写结果。", ok: "复制并写入" });
      if (!go) return;
      const c = await call("copy_builtin", S.cur.id);
      if (!c || !c.ok) return toast((c && c.error) || "复制失败", { type: "error" });
      await refreshList();
      await openPrompt(c.prompt.id);
    }
    editor.value = bodyText;
    if (meta.name && !S.cur.builtin) { title.value = meta.name; syncTitleWidth(); S.cur.name = meta.name; }
    markDirty();
    await flushSave();
    if (meta.keywords && meta.keywords.length && S.cur && !S.cur.builtin) {
      await persistKeywords(meta.keywords);
    }
    closeAiDrawer();
    toast("已写入正文");
  }

  function isAiOpen() {
    const lay = $(".layout");
    return !!(lay && lay.classList.contains("ai-open"));
  }
  function closeAiDrawer() {
    const lay = $(".layout");
    const panel = $("#aiPanel");
    if (lay) lay.classList.remove("ai-open");
    if (panel) panel.hidden = true;
    const btn = $("#aiBtn"); if (btn) btn.setAttribute("aria-pressed", "false");
  }
  async function openAiStudio(tab) {
    if (tab === "test") { setTab("debug"); return; }
    await loadAiData();
    AI.tab = tab || AI.tab || "gen";
    _aiLastText = "";
    const lay = $(".layout");
    const panel = $("#aiPanel");
    if (panel) panel.hidden = false;
    if (lay) {
      if (!lay.style.getPropertyValue("--ai-w")) lay.style.setProperty("--ai-w", (LAYOUT && LAYOUT.defaults ? LAYOUT.defaults.ai : 420) + "px");
      lay.classList.add("ai-open");
    }
    $$("#aiTabs button").forEach((b) => b.classList.toggle("active", b.dataset.ai === AI.tab));
    renderAiBody();
    const btn = $("#aiBtn"); if (btn) btn.setAttribute("aria-pressed", "true");
    setTimeout(() => { const f = $("#aiGoal") || $("#aiSrc") || $("#aiTestBody"); if (f) f.focus(); }, 0);
  }
  function toggleAiStudio(tab) {
    // 2.12.1: 并行测已并入调试页
    if (tab === "test") { setTab("debug"); closeAiDrawer(); return; }
    if (isAiOpen() && (!tab || tab === AI.tab)) closeAiDrawer();
    else openAiStudio(tab || "gen");
  }
  $$("#aiTabs button").forEach((b) => b.onclick = () => { AI.tab = b.dataset.ai; $$("#aiTabs button").forEach((x) => x.classList.toggle("active", x === b)); renderAiBody(); });
  const aiBtn = $("#aiBtn");
  if (aiBtn) aiBtn.onclick = () => toggleAiStudio("gen");
  const aiCloseBtn = $("#aiCloseBtn");
  if (aiCloseBtn) aiCloseBtn.onclick = () => closeAiDrawer();
  const aiOpenSettings = $("#aiOpenSettings");
  if (aiOpenSettings) aiOpenSettings.onclick = () => { openSettings("ai"); };

  /* ---- layout: column splitters + collapse + overflow menus (2.12.0) ---- */
  const LAYOUT = {
    defaults: { list: 264, side: 400, ai: 420 },
    min: { list: 180, side: 280, ai: 320, editor: 260 },
    max: { list: 420, side: 560, ai: 720 },
    keys: { list: "pb.layout.w.list", side: "pb.layout.w.side", ai: "pb.aiWidth",
            listCol: "pb.layout.collapsed.list", sideCol: "pb.layout.collapsed.side" },
  };
  function layoutEl() { return $(".layout"); }
  function readStoredWidth(key, fallback) {
    try {
      const v = parseInt(localStorage.getItem(key), 10);
      if (Number.isFinite(v) && v > 0) return v;
    } catch (_) {}
    return fallback;
  }
  function clampWidth(kind, w) {
    return Math.max(LAYOUT.min[kind], Math.min(LAYOUT.max[kind], Math.round(w)));
  }
  function applyLayoutWidths(listW, sideW, aiW) {
    const lay = layoutEl(); if (!lay) return;
    if (listW != null) lay.style.setProperty("--list-w", clampWidth("list", listW) + "px");
    if (sideW != null) lay.style.setProperty("--side-w", clampWidth("side", sideW) + "px");
    if (aiW != null) lay.style.setProperty("--ai-w", clampWidth("ai", aiW) + "px");
  }
  function persistLayoutWidths() {
    const lay = layoutEl(); if (!lay) return;
    try {
      const cs = getComputedStyle(lay);
      localStorage.setItem(LAYOUT.keys.list, parseInt(cs.getPropertyValue("--list-w"), 10) || LAYOUT.defaults.list);
      localStorage.setItem(LAYOUT.keys.side, parseInt(cs.getPropertyValue("--side-w"), 10) || LAYOUT.defaults.side);
      localStorage.setItem(LAYOUT.keys.ai, (cs.getPropertyValue("--ai-w") || "").trim() || (LAYOUT.defaults.ai + "px"));
    } catch (_) {}
  }
  function editorFloor() {
    const lay = layoutEl(); if (!lay) return LAYOUT.min.editor;
    const cs = getComputedStyle(lay);
    const edMin = parseInt(cs.getPropertyValue("--ed-min"), 10) || LAYOUT.min.editor;
    return Math.max(LAYOUT.min.editor, edMin);
  }
  function maxListAllowed() {
    const lay = layoutEl(); if (!lay) return LAYOUT.max.list;
    const total = lay.getBoundingClientRect().width;
    const side = lay.classList.contains("side-collapsed") ? 0 : (parseInt(getComputedStyle(lay).getPropertyValue("--side-w"), 10) || LAYOUT.defaults.side);
    const ai = lay.classList.contains("ai-open") ? (parseInt(getComputedStyle(lay).getPropertyValue("--ai-w"), 10) || LAYOUT.defaults.ai) : 0;
    const splitters = 10 + (lay.classList.contains("ai-open") && !lay.classList.contains("side-collapsed") ? 0 : 0);
    return Math.max(LAYOUT.min.list, Math.min(LAYOUT.max.list, total - side - ai - editorFloor() - 15));
  }
  function maxSideAllowed() {
    const lay = layoutEl(); if (!lay) return LAYOUT.max.side;
    const total = lay.getBoundingClientRect().width;
    const list = lay.classList.contains("list-collapsed") ? 0 : (parseInt(getComputedStyle(lay).getPropertyValue("--list-w"), 10) || LAYOUT.defaults.list);
    const ai = lay.classList.contains("ai-open") ? (parseInt(getComputedStyle(lay).getPropertyValue("--ai-w"), 10) || LAYOUT.defaults.ai) : 0;
    return Math.max(LAYOUT.min.side, Math.min(LAYOUT.max.side, total - list - ai - editorFloor() - 15));
  }
  function bindColumnSplitter(handle, kind) {
    if (!handle) return;
    let startX = 0, startW = 0;
    const onMove = (e) => {
      const lay = layoutEl(); if (!lay) return;
      const dx = e.clientX - startX;
      if (kind === "list") {
        const max = maxListAllowed();
        const w = Math.max(LAYOUT.min.list, Math.min(max, startW + dx));
        lay.style.setProperty("--list-w", w + "px");
      } else if (kind === "side") {
        const max = maxSideAllowed();
        // dragging handle right grows side; left shrinks side
        const w = Math.max(LAYOUT.min.side, Math.min(max, startW - dx));
        lay.style.setProperty("--side-w", w + "px");
      }
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      const lay = layoutEl();
      if (lay) { lay.classList.remove("is-resizing"); handle.classList.remove("active"); }
      persistLayoutWidths();
    };
    handle.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const lay = layoutEl(); if (!lay) return;
      startX = e.clientX;
      const cs = getComputedStyle(lay);
      startW = parseInt(cs.getPropertyValue(kind === "list" ? "--list-w" : "--side-w"), 10)
        || (kind === "list" ? LAYOUT.defaults.list : LAYOUT.defaults.side);
      lay.classList.add("is-resizing");
      handle.classList.add("active");
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
    handle.addEventListener("dblclick", (e) => {
      e.preventDefault();
      if (kind === "list") applyLayoutWidths(LAYOUT.defaults.list, null, null);
      else applyLayoutWidths(null, LAYOUT.defaults.side, null);
      persistLayoutWidths();
    });
  }
  function bindAiResize() {
    const handle = $("#aiResize");
    if (!handle) return;
    let startX = 0, startW = LAYOUT.defaults.ai;
    const onMove = (e) => {
      const lay = layoutEl(); if (!lay) return;
      const dx = startX - e.clientX;
      const w = clampWidth("ai", startW + dx);
      lay.style.setProperty("--ai-w", w + "px");
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      const lay = layoutEl(); if (lay) lay.classList.remove("ai-resizing", "is-resizing");
      persistLayoutWidths();
    };
    handle.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const lay = layoutEl(); if (!lay) return;
      startX = e.clientX;
      startW = parseInt(getComputedStyle(lay).getPropertyValue("--ai-w"), 10)
        || lay.querySelector("#aiPanel")?.getBoundingClientRect().width || LAYOUT.defaults.ai;
      lay.classList.add("ai-resizing", "is-resizing");
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
    handle.addEventListener("dblclick", (e) => {
      e.preventDefault();
      applyLayoutWidths(null, null, LAYOUT.defaults.ai);
      persistLayoutWidths();
    });
  }
  function setPanelCollapsed(which, collapsed) {
    const lay = layoutEl(); if (!lay) return;
    const cls = which === "list" ? "list-collapsed" : "side-collapsed";
    lay.classList.toggle(cls, !!collapsed);
    const btn = $(which === "list" ? "#toggleListBtn" : "#toggleSideBtn");
    if (btn) btn.setAttribute("aria-pressed", collapsed ? "false" : "true");
    try { localStorage.setItem(which === "list" ? LAYOUT.keys.listCol : LAYOUT.keys.sideCol, collapsed ? "1" : "0"); } catch (_) {}
  }
  function initLayoutChrome() {
    const lay = layoutEl(); if (!lay) return;
    applyLayoutWidths(
      readStoredWidth(LAYOUT.keys.list, LAYOUT.defaults.list),
      readStoredWidth(LAYOUT.keys.side, LAYOUT.defaults.side),
      readStoredWidth(LAYOUT.keys.ai, LAYOUT.defaults.ai)
    );
    try {
      if (localStorage.getItem(LAYOUT.keys.listCol) === "1") setPanelCollapsed("list", true);
      if (localStorage.getItem(LAYOUT.keys.sideCol) === "1") setPanelCollapsed("side", true);
    } catch (_) {}
    bindColumnSplitter($("#splitList"), "list");
    bindColumnSplitter($("#splitSide"), "side");
    bindAiResize();
    const tl = $("#toggleListBtn");
    if (tl) tl.onclick = () => setPanelCollapsed("list", !lay.classList.contains("list-collapsed"));
    const ts = $("#toggleSideBtn");
    if (ts) ts.onclick = () => setPanelCollapsed("side", !lay.classList.contains("side-collapsed"));
    function fitColumnsToViewport() {
      const total = lay.getBoundingClientRect().width;
      if (!total) return;
      const cs = getComputedStyle(lay);
      let list = lay.classList.contains("list-collapsed") ? 0
        : (parseInt(cs.getPropertyValue("--list-w"), 10) || LAYOUT.defaults.list);
      let side = lay.classList.contains("side-collapsed") ? 0
        : (parseInt(cs.getPropertyValue("--side-w"), 10) || LAYOUT.defaults.side);
      let ai = lay.classList.contains("ai-open")
        ? (parseInt(cs.getPropertyValue("--ai-w"), 10) || LAYOUT.defaults.ai) : 0;
      const splits = 10; // two column splitters when both side panels visible
      const floor = editorFloor();
      // Prefer closing AI when the viewport is too tight for 4 columns
      if (ai && list + side + ai + floor + splits + 5 > total) {
        closeAiDrawer();
        ai = 0;
      }
      // Shrink AI, then side, then list to keep editor floor
      let budget = total - floor - splits - 5;
      if (ai) {
        const maxAi = Math.max(LAYOUT.min.ai, budget - (list || LAYOUT.min.list) - (side || LAYOUT.min.side));
        ai = Math.min(ai, Math.max(LAYOUT.min.ai, maxAi));
        lay.style.setProperty("--ai-w", clampWidth("ai", ai) + "px");
        budget -= ai;
      }
      if (!lay.classList.contains("side-collapsed")) {
        side = Math.min(side, Math.max(LAYOUT.min.side, budget - (list || LAYOUT.min.list)));
        side = clampWidth("side", side);
      }
      if (!lay.classList.contains("list-collapsed")) {
        list = Math.min(list, Math.max(LAYOUT.min.list, budget - (side || 0)));
        list = clampWidth("list", list);
      }
      applyLayoutWidths(
        lay.classList.contains("list-collapsed") ? null : list,
        lay.classList.contains("side-collapsed") ? null : side,
        null
      );
    }
    window.addEventListener("resize", debounce(() => { fitColumnsToViewport(); syncLibHeadDensity(); }, 120));
    // initial fit (e.g. restored wide columns on a smaller window)
    setTimeout(() => { fitColumnsToViewport(); syncLibHeadDensity(); }, 0);
  }

  function placeOverflowMenu(menu, btn) {
    if (!menu || !btn) return;
    const r = btn.getBoundingClientRect();
    menu.style.position = "fixed";
    menu.style.top = `${Math.round(r.bottom + 6)}px`;
    menu.style.right = `${Math.round(window.innerWidth - r.right)}px`;
    menu.style.left = "auto";
    menu.style.zIndex = "120";
  }
  function toggleSortCompact(open) {
    const menu = $("#sortCompactMenu"), btn = $("#sortCompactBtn");
    if (!menu || !btn) return;
    const show = open === undefined ? menu.classList.contains("hidden") : !!open;
    menu.classList.toggle("hidden", !show);
    btn.setAttribute("aria-expanded", show ? "true" : "false");
    if (show) {
      // mark active sort
      const cur = ($("#sortSel") && $("#sortSel").value) || "recent";
      menu.querySelectorAll("[data-sort]").forEach((b) => {
        b.setAttribute("aria-checked", b.dataset.sort === cur ? "true" : "false");
        b.classList.toggle("cursor", b.dataset.sort === cur);
      });
    }
  }
  function syncLibHeadDensity() {
    /* Progressive collapse when list panel is narrow; menus stay overflow-visible */
    const panel = $("#listPanel");
    if (!panel) return;
    const narrow = panel.getBoundingClientRect().width < 280;
    const was = panel.classList.contains("lib-compact");
    panel.classList.toggle("lib-compact", narrow);
    if (!narrow && was) toggleSortCompact(false);
  }

  function toggleEditorMore(open) {
    const menu = $("#editorMoreMenu"), btn = $("#editorMoreBtn");
    if (!menu || !btn) return;
    if (open == null) open = menu.classList.contains("hidden");
    menu.classList.toggle("hidden", !open);
    btn.setAttribute("aria-expanded", String(!!open));
    if (open) placeOverflowMenu(menu, btn);
  }
  $("#editorMoreBtn")?.addEventListener("click", (e) => { e.stopPropagation(); toggleEditorMore(); });
  $("#sortCompactBtn")?.addEventListener("click", (e) => {
    e.stopPropagation(); toggleSortCompact();
  });
  $("#sortCompactMenu")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-sort]"); if (!b) return;
    const v = b.dataset.sort;
    const sel = $("#sortSel");
    if (sel && sel.value !== v) {
      sel.value = v;
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    }
    toggleSortCompact(false);
  });
  // close overflow menus after choosing an action
  $("#editorMoreMenu")?.addEventListener("click", (e) => {
    if (e.target.closest("button[role='menuitem']")) toggleEditorMore(false);
  });
  initLayoutChrome();

  // ---------------------------------------------------------------- shortcuts
  document.addEventListener("keydown", (e) => {
    const k = e.key.toLowerCase(), modal = topModal();
    if (e.key === "Escape" && modal) { e.preventDefault(); closeModal(modal); return; }
    if (e.key === "Escape" && typeof isAiOpen === "function" && isAiOpen()) { e.preventDefault(); closeAiDrawer(); return; }
    if (e.key === "F1") { e.preventDefault(); if (modal === "helpOverlay") closeModal(modal); else if (!modal) openHelp("keys"); return; }
    if (modal) return;
    if (e.ctrlKey && e.shiftKey && !e.altKey && k === "a") { e.preventDefault(); toggleAiStudio("gen"); return; }
    if (e.ctrlKey && !e.shiftKey && !e.altKey) {
      if (k === "s") { e.preventDefault(); markDirty(); flushSave(); return; }
      if (k === "n") { e.preventDefault(); newPrompt(); return; }
      if (e.key === "Enter") { e.preventDefault(); copyResult(); return; }
      if (k === "f") { e.preventDefault(); $("#search").focus(); $("#search").select(); return; }
      if (k === "d" && S.cur) { e.preventDefault(); duplicatePrompt(S.cur.id); return; }
      if (k === "i" && S.cur) { e.preventDefault(); if (document.activeElement !== editor) { editor.focus(); } openInsertMenu(); return; }
      if (k === ",") { e.preventDefault(); openSettings(); return; }
      if (["1", "2", "3"].includes(e.key)) { e.preventDefault(); setTab(TABS[+e.key - 1]); return; }
    }
    if (e.key === "F2" && S.cur && document.activeElement !== $("#list")) { e.preventDefault(); startRename(S.cur.id); }
  });
  window.addEventListener("beforeunload", () => { flushSave(); });

  // ---------------------------------------------------------------- boot
  async function boot() {
    window.PBIcons.fill();
    S.api = window.pywebview.api;
    const b = await call("get_bootstrap");
    if (!b) return;
    S.version = b.version; S.settings = b.settings; S.list = b.prompts || [];
    S.tree = b.tree || { roles: [] };
    ensureExpandedDefaults();
    applyTheme(S.settings.theme);
    {
      const ALLOWED_SORT = new Set(["recent", "updated", "name"]);
      let sort = (S.settings && S.settings.library_sort) || "recent";
      if (!ALLOWED_SORT.has(sort)) sort = "recent";
      S.sort = sort;
      const sel = $("#sortSel"); if (sel) sel.value = sort;
    }
    syncLibScopeUI();
    $("#ver").textContent = `v${b.version}`;
    $("#aboutVer").textContent = `版本 ${b.version}`;
    document.title = "提示词 Builder";
    $("#aboutNote").innerHTML = `数据目录：${esc(b.data_dir)}<br>自动备份：${esc(b.data_dir)}\\backups（最近 10 份）` + (b.log_path ? `<br>日志：${esc(b.log_path)}` : "");
    quickPill(b.quick);
    setTab("form");
    // Prefer tree render; fall back to refresh if tree empty but prompts exist
    if (S.tree.roles && S.tree.roles.length) renderList();
    else await refreshList();
    if (S.flatItems.length) await openPrompt(S.flatItems[0].id);
    else if (S.list.length) await openPrompt(S.list[0].id);
    else showEmptyEditor();
    const m = b.migration;
    if (m && m.migrated) toast(`已从旧版本迁移 ${m.imported} 个提示词（原数据已备份到 legacy-2.x）`, { type: "info", ms: 5000 });
    else if (b.recovered) toast(b.recovered === "default" ? "提示词库文件损坏且没有可用备份，已保留损坏文件副本" : "提示词库文件损坏，已从自动备份恢复（损坏文件已另存）", { type: "warn", ms: 8000 });
    if (b.onboarding) setTimeout(openOnboarding, 250);
    setInterval(refreshQuick, 15000);
  }
  window.PBIcons.fill();
  applyTheme((() => { try { return localStorage.getItem("pb.theme") || "system"; } catch (e) { return "system"; } })());
  if (window.pywebview && window.pywebview.api) boot();
  else window.addEventListener("pywebviewready", boot, { once: true });
})();

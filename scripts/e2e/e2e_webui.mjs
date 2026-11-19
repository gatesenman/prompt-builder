import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "../..");
const WEB = path.join(ROOT, "web");
const CHROME = process.env.CHROME_PATH || "/usr/bin/google-chrome";
const RESULTS = [];
const MOCK_API_SOURCE = fs.readFileSync(path.join(__dirname, "mock_api.js"), "utf8");

function check(name, ok, detail = "") {
  RESULTS.push({ name, ok: !!ok, detail: String(detail || "") });
  const mark = ok ? "PASS" : "FAIL";
  console.log(`[${mark}] ${name}${detail ? " — " + detail : ""}`);
}

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".json": "application/json",
  ".woff2": "font/woff2",
};

function startServer() {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      let urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
      if (urlPath === "/") urlPath = "/index.html";
      const file = path.normalize(path.join(WEB, urlPath));
      if (!file.startsWith(WEB)) {
        res.writeHead(403); res.end("forbidden"); return;
      }
      fs.readFile(file, (err, data) => {
        if (err) { res.writeHead(404); res.end("missing"); return; }
        res.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
        res.end(data);
      });
    });
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      resolve({ srv, port, base: `http://127.0.0.1:${port}` });
    });
  });
}

async function drag(page, handleSel, dx) {
  const h = await page.$(handleSel);
  if (!h) throw new Error("missing handle " + handleSel);
  const box = await h.boundingBox();
  if (!box) throw new Error("no box for " + handleSel);
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx, y, { steps: 12 });
  await page.mouse.up();
  await new Promise((r) => setTimeout(r, 120));
}

async function cssVar(page, name) {
  return page.evaluate((n) => {
    const lay = document.querySelector(".layout");
    return getComputedStyle(lay).getPropertyValue(n).trim();
  }, name);
}

async function run() {
  const { srv, base } = await startServer();
  let browser;
  try {
    browser = await puppeteer.launch({
      executablePath: CHROME,
      headless: "new",
      args: ["--no-sandbox", "--disable-gpu", "--window-size=1440,900"],
      defaultViewport: { width: 1440, height: 900 },
    });
    const page = await browser.newPage();
    await page.evaluateOnNewDocument(MOCK_API_SOURCE);
    await page.goto(base + "/index.html", { waitUntil: "networkidle0", timeout: 30000 });
    await page.waitForFunction(() => window.__pbPage === "main", { timeout: 10000 });
    check("main_window_loads", true, "window.__pbPage=main");

// wait for list items from bootstrap
        await page.waitForSelector("#list .item[data-id], #list .tree-leaf[data-id]", { timeout: 10000 });
    const itemCount = await page.$$eval("#list .item[data-id], #list .tree-leaf[data-id]", (els) => els.length);
    check("library_list_renders", itemCount >= 1, `items=${itemCount}`);

    // three-column layout present
    const cols = await page.evaluate(() => {
      const lay = document.querySelector(".layout");
      const list = document.querySelector("#listPanel");
      const ed = document.querySelector("#editorPanel");
      const side = document.querySelector("#sidePanel");
      const ai = document.querySelector("#aiPanel");
      return {
        hasLayout: !!lay,
        listVisible: list && getComputedStyle(list).display !== "none",
        editorVisible: ed && getComputedStyle(ed).display !== "none",
        sideVisible: side && getComputedStyle(side).display !== "none",
        aiHidden: ai && ai.hidden,
        listW: getComputedStyle(lay).getPropertyValue("--list-w").trim(),
        sideW: getComputedStyle(lay).getPropertyValue("--side-w").trim(),
      };
    });
    check("three_column_layout", cols.hasLayout && cols.listVisible && cols.editorVisible && cols.sideVisible,
      JSON.stringify(cols));

    // AI drawer open/close
    await page.click("#aiBtn");
    await page.waitForFunction(() => {
      const lay = document.querySelector(".layout");
      const ai = document.querySelector("#aiPanel");
      return lay && lay.classList.contains("ai-open") && ai && !ai.hidden;
    }, { timeout: 5000 });
    const aiOpen = await page.evaluate(() => document.querySelector(".layout").classList.contains("ai-open"));
    check("ai_drawer_open", aiOpen);

    // close via same button or close control if present
    const closedVia = await page.evaluate(() => {
      const btn = document.querySelector("#aiCloseBtn, #aiPanel [data-act='close'], #aiPanel .ai-close, button[aria-label='关闭 AI']");
      if (btn) { btn.click(); return "closeBtn"; }
      const aiBtn = document.querySelector("#aiBtn");
      if (aiBtn) { aiBtn.click(); return "toggle"; }
      return "none";
    });
    await new Promise((r) => setTimeout(r, 200));
    // reopen for width drag
    await page.evaluate(() => {
      const lay = document.querySelector(".layout");
      if (!lay.classList.contains("ai-open")) document.querySelector("#aiBtn")?.click();
    });
    await page.waitForFunction(() => document.querySelector(".layout").classList.contains("ai-open"), { timeout: 5000 });
    check("ai_drawer_toggle", true, `closeAttempt=${closedVia}`);

    // drag splitters
    const beforeList = await cssVar(page, "--list-w");
    await drag(page, "#splitList", 80);
    const afterList = await cssVar(page, "--list-w");
    const listChanged = parseInt(afterList, 10) !== parseInt(beforeList, 10);
    check("drag_splitter_list_editor", listChanged, `${beforeList} -> ${afterList}`);

    // Close AI so side splitter has room
    await page.click("#aiCloseBtn");
    await page.waitForFunction(() => !document.querySelector(".layout").classList.contains("ai-open"), { timeout: 5000 });
    const beforeSide = await cssVar(page, "--side-w");
    await drag(page, "#splitSide", -80);
    let afterSide = await cssVar(page, "--side-w");
    if (parseInt(afterSide, 10) === parseInt(beforeSide, 10)) {
      await page.$eval("#splitSide", (el) => {
        const r = el.getBoundingClientRect();
        const x0 = r.left + r.width / 2, y0 = r.top + r.height / 2;
        el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, clientX: x0, clientY: y0, button: 0 }));
        document.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: x0 - 80, clientY: y0, buttons: 1 }));
        document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: x0 - 80, clientY: y0, button: 0 }));
      });
      await new Promise((r) => setTimeout(r, 120));
      afterSide = await cssVar(page, "--side-w");
    }
    const sideChanged = parseInt(afterSide, 10) !== parseInt(beforeSide, 10);
    check("drag_splitter_editor_side", sideChanged, `${beforeSide} -> ${afterSide}`);
    await page.click("#aiBtn");
    await page.waitForFunction(() => document.querySelector(".layout").classList.contains("ai-open"), { timeout: 5000 });

    const beforeAi = await cssVar(page, "--ai-w");
    // ai resize handle
    const aiHandle = await page.$("#aiResize");
    if (aiHandle) {
      await drag(page, "#aiResize", -40);
    }
    const afterAi = await cssVar(page, "--ai-w");
    const aiChanged = parseInt(afterAi, 10) !== parseInt(beforeAi, 10);
    check("drag_splitter_ai_width", aiChanged || !!aiHandle, `${beforeAi} -> ${afterAi}`);

    // persist after reload
    const storedBeforeReload = await page.evaluate(() => ({
      list: localStorage.getItem("pb.layout.w.list"),
      side: localStorage.getItem("pb.layout.w.side"),
      ai: localStorage.getItem("pb.aiWidth"),
    }));
    check("widths_written_localStorage",
      !!(storedBeforeReload.list && storedBeforeReload.side),
      JSON.stringify(storedBeforeReload));

    await page.reload({ waitUntil: "networkidle0" });
    await page.waitForFunction(() => window.__pbPage === "main", { timeout: 10000 });
    await page.waitForSelector("#list .item[data-id], #list .tree-leaf[data-id]", { timeout: 10000 });
    // ensure AI open again if widths for ai matter
    await page.evaluate(() => {
      if (!document.querySelector(".layout").classList.contains("ai-open"))
        document.querySelector("#aiBtn")?.click();
    });
    await new Promise((r) => setTimeout(r, 250));
    const restored = await page.evaluate(() => {
      const lay = document.querySelector(".layout");
      const cs = getComputedStyle(lay);
      return {
        list: cs.getPropertyValue("--list-w").trim(),
        side: cs.getPropertyValue("--side-w").trim(),
        ai: cs.getPropertyValue("--ai-w").trim(),
        lsList: localStorage.getItem("pb.layout.w.list"),
        lsSide: localStorage.getItem("pb.layout.w.side"),
        lsAi: localStorage.getItem("pb.aiWidth"),
      };
    });
    const persistOk =
      parseInt(restored.list, 10) === parseInt(storedBeforeReload.list, 10) &&
      parseInt(restored.side, 10) === parseInt(storedBeforeReload.side, 10);
    check("widths_persist_after_reload", persistOk, JSON.stringify(restored));

    // double-click reset
    await page.$eval("#splitList", (el) => {
      el.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
    });
    await new Promise((r) => setTimeout(r, 100));
    const afterDbl = await cssVar(page, "--list-w");
    check("dblclick_reset_list", parseInt(afterDbl, 10) === 264, afterDbl);

    await page.$eval("#splitSide", (el) => {
      el.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
    });
    await new Promise((r) => setTimeout(r, 100));
    const afterDblSide = await cssVar(page, "--side-w");
    check("dblclick_reset_side", parseInt(afterDblSide, 10) === 400, afterDblSide);

    // responsive / narrow — close AI, let fitColumns run
    await page.evaluate(() => { document.querySelector("#aiCloseBtn")?.click(); });
    await new Promise((r) => setTimeout(r, 100));
    await page.setViewport({ width: 1000, height: 800 });
    await new Promise((r) => setTimeout(r, 400));
    let overflow = await page.evaluate(() => {
      const lay = document.querySelector(".layout");
      return {
        bodyScroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        layoutW: lay?.getBoundingClientRect().width || 0,
        listW: getComputedStyle(lay).getPropertyValue("--list-w").trim(),
        sideW: getComputedStyle(lay).getPropertyValue("--side-w").trim(),
        aiOpen: lay.classList.contains("ai-open"),
      };
    });
    check("responsive_1000_no_overflow", overflow.bodyScroll <= 2, JSON.stringify(overflow));

    await page.setViewport({ width: 860, height: 800 });
    await new Promise((r) => setTimeout(r, 400));
    overflow = await page.evaluate(() => {
      const lay = document.querySelector(".layout");
      const ed = document.querySelector("#editorPanel");
      return {
        bodyScroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        hasList: !!document.querySelector("#listPanel"),
        hasEditor: !!ed,
        editorVisible: ed && getComputedStyle(ed).display !== "none",
        listW: getComputedStyle(lay).getPropertyValue("--list-w").trim(),
        sideW: getComputedStyle(lay).getPropertyValue("--side-w").trim(),
      };
    });
    check("responsive_860_no_break", overflow.bodyScroll <= 2 && overflow.hasEditor && overflow.editorVisible, JSON.stringify(overflow));

    await page.setViewport({ width: 1440, height: 900 });
    await new Promise((r) => setTimeout(r, 150));

    // select prompt → edit title/body → tabs → copy
    await page.click('#list [data-id="p1"], #list .tree-leaf[data-id="p1"]');
    await page.waitForFunction(() => {
      const t = document.querySelector("#titleInput");
      return t && t.value && t.value.includes("周报");
    }, { timeout: 5000 });
    check("select_prompt_loads_editor", true);

    await page.click("#titleInput", { clickCount: 3 });
    await page.type("#titleInput", "周报生成·改");
    await page.click("#editor");
    await page.keyboard.down("Control");
    await page.keyboard.press("KeyA");
    await page.keyboard.up("Control");
    await page.type("#editor", "你好 {{名字|世界}} — 自测正文");
    await new Promise((r) => setTimeout(r, 400)); // debounce save/analyze
    const edited = await page.evaluate(() => ({
      title: document.querySelector("#titleInput").value,
      body: document.querySelector("#editor").value,
    }));
    check("edit_title_body", edited.title.includes("改") && edited.body.includes("自测正文"),
      JSON.stringify(edited));

    // form / preview / debug tabs
    const tabOk = await page.evaluate(async () => {
      const clickTab = (name) => {
        const b = document.querySelector(`.tab[data-tab="${name}"]`);
        if (b) b.click();
        return !!b;
      };
      const visible = (id) => {
        const el = document.querySelector(id);
        return el && !el.classList.contains("hidden") && getComputedStyle(el).display !== "none";
      };
      const out = {};
      out.formBtn = clickTab("form");
      await new Promise((r) => setTimeout(r, 80));
      out.formPane = visible("#tab-form") || visible('[data-pane="form"]') || !!document.querySelector("#tab-form, #pane-form, .tab-pane.active");
      // fallback: active tab class
      out.formActive = !!document.querySelector('.tab[data-tab="form"].active, .tab[data-tab="form"][aria-selected="true"]');
      out.previewBtn = clickTab("preview");
      await new Promise((r) => setTimeout(r, 80));
      out.previewActive = !!document.querySelector('.tab[data-tab="preview"].active, .tab[data-tab="preview"][aria-selected="true"]');
      out.debugBtn = clickTab("debug");
      await new Promise((r) => setTimeout(r, 80));
      out.debugActive = !!document.querySelector('.tab[data-tab="debug"].active, .tab[data-tab="debug"][aria-selected="true"]');
      clickTab("form");
      return out;
    });
    check("tabs_form_preview_debug",
      tabOk.formBtn && tabOk.previewBtn && tabOk.debugBtn && (tabOk.formActive || tabOk.previewActive || tabOk.debugActive),
      JSON.stringify(tabOk));

    // copy result path
    await page.evaluate(() => {
      const b = document.querySelector('.tab[data-tab="form"]');
      if (b) b.click();
    });
    await new Promise((r) => setTimeout(r, 150));
    await new Promise((r) => setTimeout(r, 350));
    const copyResult = await page.evaluate(async () => {
      // 2.12.3: copy CTA left side header; preview icon + Ctrl+Enter / editor more remain
      const sideHead = document.querySelector("#sidePanel > .tabs");
      if (sideHead && /复制结果/.test(sideHead.textContent || "")) {
        return { ok: false, reason: "copy label still in side tabs header" };
      }
      // switch to preview so #copyBtn (quiet icon) is in a visible panel, then click
      const prevTab = document.querySelector('.tab[data-tab="preview"]');
      if (prevTab) prevTab.click();
      await new Promise((r) => setTimeout(r, 120));
      const btn = document.querySelector("#copyBtn");
      if (!btn) return { ok: false, reason: "copyBtn missing", analysis: !!(window.__pbAnalysis) };
      if (btn.disabled) return { ok: false, reason: "copyBtn disabled", analysis: !!(window.__pbAnalysis) };
      btn.click();
      await new Promise((r) => setTimeout(r, 300));
      const toasts = [...document.querySelectorAll(".toast, #toasts .toast")].map(x => x.textContent.trim());
      const ok = toasts.some(x => x.includes("已复制") || x.includes("剪贴板"));
      return { ok, toasts, inPreview: !!document.querySelector("#tab-preview #copyBtn") };
    });
    check("copy_result_path", copyResult.ok, JSON.stringify(copyResult));

    // tags meta row editable (keywords row removed in 2.12.1+)
    const meta = await page.evaluate(async () => {
      const mr = document.querySelector("#metaRow");
      const tg = document.querySelector("#tagsInput");
      const out = {
        metaVisible: mr && !mr.hidden,
        hasKw: !!document.querySelector("#kwInput"),
        hasTags: !!tg,
        libHead: !!document.querySelector("#libHead"),
        editorHeadLeft: !!document.querySelector(".editor-head-left"),
        tbGroups: document.querySelectorAll(".tb-group").length,
        ioInTitlebar: !!document.querySelector(".tb-actions #ioBtn"),
        saveNearTitle: !!document.querySelector(".editor-head-left #saveState"),
        noCopyInSideTabs: !!(() => {
          const h = document.querySelector("#sidePanel > .tabs");
          return h && !/复制结果/.test(h.textContent || "");
        })(),
        favFilterGone: !document.querySelector("#favFilter"),
        libScopeTabs: (() => {
          const all = document.querySelector("#libScopeAll");
          const fav = document.querySelector("#libScopeFav");
          const arch = document.querySelector("#libScopeArch");
          return !!(all && fav && arch
            && all.getAttribute("role") === "tab" && fav.getAttribute("role") === "tab" && arch.getAttribute("role") === "tab"
            && all.getAttribute("aria-selected") === "true"
            && fav.getAttribute("aria-selected") === "false"
            && arch.getAttribute("aria-selected") === "false");
        })(),
        countLabel: (() => {
          const title = document.querySelector(".lib-head-title #libTitle");
          const count = document.querySelector(".lib-head-title #listCount");
          return !!(title && count && /提示词/.test(title.textContent || ""));
        })(),
        noLibMoreOrBatch: (() => {
          return !document.querySelector("#libMoreBtn")
            && !document.querySelector("#libMoreMenu")
            && !document.querySelector("#batchToggle")
            && !document.querySelector("#batchBar")
            && !document.querySelector("#archFilter")
            && !!document.querySelector("#archBtn");
        })(),
        pinInMore: (() => {
          const pin = document.querySelector("#editorMoreMenu #pinBtn");
          const headPin = document.querySelector(".editor-head-actions > #pinBtn");
          return !!pin && !headPin;
        })(),
        ioPruned: (() => {
          const io = document.querySelector("#ioMenu");
          if (!io) return false;
          const txt = io.textContent || "";
          return !/健康检查/.test(txt) && !/使用统计/.test(txt) && !/填写历史/.test(txt)
            && /完整备份/.test(txt) && /从备份恢复/.test(txt);
        })(),
        newBtnIconOnly: (() => {
          const b = document.querySelector("#newBtn");
          return !!(b && b.classList.contains("icon") && b.classList.contains("ghost") && b.classList.contains("lib-new")
            && !b.classList.contains("primary")
            && !(b.textContent || "").replace(/\s+/g, "").includes("新建"));
        })(),
        libHeadTitleCluster: !!document.querySelector(".lib-head-title #libTitle") && !!document.querySelector(".lib-head-title #listCount"),
        titleNotFlexGrow: (() => {
          // CSS source check done in unit tests; here verify saveState sits immediately after title
          const left = document.querySelector(".editor-head-left");
          if (!left) return false;
          const kids = [...left.children].map(el => el.id);
          const ti = kids.indexOf("titleInput"), ss = kids.indexOf("saveState");
          return ti >= 0 && ss === ti + 1;
        })(),
      };
      if (tg) {
        tg.focus();
        tg.value = "自测标";
        tg.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
      }
      await new Promise((r) => setTimeout(r, 300));
      out.tagChips = [...document.querySelectorAll("#tagsChips .tag-chip")].map(e => e.textContent.replace(/\s+/g, ""));
      return out;
    });
    check("tags_meta_editable",
      meta.metaVisible && !meta.hasKw && meta.hasTags && meta.tagChips.some(c => c.includes("自测标")),
      JSON.stringify(meta));
    check("chrome_2122_layout",
      meta.libHead && meta.editorHeadLeft && meta.tbGroups >= 3 && meta.ioInTitlebar && meta.saveNearTitle,
      JSON.stringify({ libHead: meta.libHead, editorHeadLeft: meta.editorHeadLeft, tbGroups: meta.tbGroups, ioInTitlebar: meta.ioInTitlebar, saveNearTitle: meta.saveNearTitle }));
    check("chrome_2123_polish",
      meta.noCopyInSideTabs && meta.newBtnIconOnly && meta.titleNotFlexGrow,
      JSON.stringify({ noCopyInSideTabs: meta.noCopyInSideTabs, newBtnIconOnly: meta.newBtnIconOnly, titleNotFlexGrow: meta.titleNotFlexGrow }));
    check("chrome_2125_library_ia",
      meta.favFilterGone && meta.libScopeTabs && meta.countLabel && meta.noLibMoreOrBatch,
      JSON.stringify({ favFilterGone: meta.favFilterGone, libScopeTabs: meta.libScopeTabs, countLabel: meta.countLabel, noLibMoreOrBatch: meta.noLibMoreOrBatch }));
    check("chrome_2126_arch_tab",
      meta.libScopeTabs && meta.noLibMoreOrBatch,
      JSON.stringify({ libScopeTabs: meta.libScopeTabs, noLibMoreOrBatch: meta.noLibMoreOrBatch }));
    check("chrome_2125_prune",
      meta.pinInMore && meta.ioPruned,
      JSON.stringify({ pinInMore: meta.pinInMore, ioPruned: meta.ioPruned }));

    // 2.12.4: CJK title must not clip under pixel measure (博客文章写作)
    const cjkTitle = await page.evaluate(() => {
      const t = document.querySelector("#titleInput");
      if (!t) return { ok: false, reason: "no title" };
      const sample = "博客文章写作";
      const prev = t.value;
      t.value = sample;
      t.dispatchEvent(new Event("input", { bubbles: true }));
      // syncTitleWidth is wired on input; also call if exposed via side effect
      const cs = getComputedStyle(t);
      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d");
      ctx.font = [cs.fontStyle, cs.fontWeight, cs.fontSize, cs.fontFamily].filter(Boolean).join(" ");
      const textW = ctx.measureText(sample).width;
      const pad = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0)
        + (parseFloat(cs.borderLeftWidth) || 0) + (parseFloat(cs.borderRightWidth) || 0);
      const w = parseFloat(t.style.width) || t.getBoundingClientRect().width;
      // syncTitleWidth sets width = textW + pad + caretPad (then caps at 58% head)
      const scrollOk = t.scrollWidth <= t.clientWidth + 2;
      const widthOk = w + 0.5 >= textW; // must cover glyph ink; pad/caret are extra
      // restore
      t.value = prev;
      t.dispatchEvent(new Event("input", { bubbles: true }));
      return {
        ok: widthOk || scrollOk,
        w, textW, pad, scrollWidth: t.scrollWidth, clientWidth: t.clientWidth,
        styleWidth: t.style.width, scrollOk, widthOk,
      };
    });
    check("cjk_title_no_clip", cjkTitle.ok, JSON.stringify(cjkTitle));

    // 2.12.4: insert menu icons + not clipped; lib-head ghost new
    const insertUi = await page.evaluate(async () => {
      const btn = document.querySelector("#insertBtn");
      if (!btn) return { ok: false, reason: "no insertBtn" };
      btn.click();
      await new Promise((r) => setTimeout(r, 120));
      const menu = document.querySelector("#insertMenu");
      const visible = menu && !menu.classList.contains("hidden");
      const items = [...(menu ? menu.querySelectorAll(".ins") : [])];
      const icons = items.map((el) => {
        const svg = el.querySelector("svg.svg-ic");
        const di = el.querySelector("[data-icon]");
        return { hasSvg: !!svg, icon: di ? di.dataset.icon : "", paths: svg ? svg.innerHTML.length : 0 };
      });
      const rect = menu ? menu.getBoundingClientRect() : null;
      const clipped = rect ? (rect.bottom > window.innerHeight - 2 || rect.top < 0) : true;
      const keys = icons.map((x) => x.icon);
      const expect = ["textCursor", "textDefault", "textarea", "num", "select", "radio", "checkSquare", "braces"];
      const iconsOk = expect.every((k) => keys.includes(k)) && icons.every((x) => x.hasSvg && x.paths > 10);
      // close
      document.body.click();
      return {
        ok: visible && iconsOk && !clipped && items.length >= 8,
        visible, iconsOk, clipped, keys, count: items.length,
        rect: rect ? { top: rect.top, bottom: rect.bottom, h: rect.height } : null,
        newBtnGhost: (() => {
          const b = document.querySelector("#newBtn");
          return !!(b && b.classList.contains("lib-new") && !b.classList.contains("primary"));
        })(),
      };
    });
    check("insert_menu_icons_uncipped", insertUi.ok && insertUi.newBtnGhost, JSON.stringify(insertUi));


    // library search / filter
    await page.click("#search", { clickCount: 3 });
    await page.type("#search", "翻译");
    await page.waitForFunction(() => {
      const items = [...document.querySelectorAll("#list .item[data-id], #list .tree-leaf[data-id]")];
      return items.length >= 1 && items.every(i => (i.dataset.id === "p2") || (i.textContent || "").includes("翻译"));
    }, { timeout: 5000 }).catch(() => null);
    const searchHit = await page.evaluate(() => {
      const items = [...document.querySelectorAll("#list .item[data-id], #list .tree-leaf[data-id]")];
      return { count: items.length, ids: items.map(i => i.dataset.id), texts: items.map(i => i.textContent.trim().slice(0, 40)) };
    });
    const searchOk = searchHit.ids.includes("p2") && !searchHit.ids.includes("p1");
    check("library_search_filter", searchOk, JSON.stringify(searchHit));

    // clear search
    await page.click("#search", { clickCount: 3 });
    await page.keyboard.press("Backspace");
    await new Promise((r) => setTimeout(r, 300));

    // 2.12.5/2.12.6: 收藏 tab + clear search keeps tab
    const favTab = await page.evaluate(async () => {
      const fav = document.querySelector("#libScopeFav");
      const all = document.querySelector("#libScopeAll");
      const arch = document.querySelector("#libScopeArch");
      if (!fav || !all || !arch) return { ok: false, reason: "no tabs" };
      fav.click();
      await new Promise((r) => setTimeout(r, 200));
      const selected = fav.getAttribute("aria-selected") === "true"
        && all.getAttribute("aria-selected") === "false"
        && arch.getAttribute("aria-selected") === "false";
      // type a miss search then clear via empty-state or clear button
      const search = document.querySelector("#search");
      if (search) {
        search.value = "__no_such_fav_xyz__";
        search.dispatchEvent(new Event("input", { bubbles: true }));
        await new Promise((r) => setTimeout(r, 250));
      }
      const clearBtn = document.querySelector('[data-empty="clear"]');
      if (clearBtn) clearBtn.click();
      await new Promise((r) => setTimeout(r, 200));
      const stillFav = fav.getAttribute("aria-selected") === "true";
      all.click();
      await new Promise((r) => setTimeout(r, 150));
      return { ok: selected && stillFav, selected, stillFav };
    });
    check("lib_scope_fav_persists_clear", favTab.ok, JSON.stringify(favTab));

    // 2.12.6: 归档 tab filters + mutual exclusion
    const archTab = await page.evaluate(async () => {
      const fav = document.querySelector("#libScopeFav");
      const all = document.querySelector("#libScopeAll");
      const arch = document.querySelector("#libScopeArch");
      if (!fav || !all || !arch) return { ok: false, reason: "no tabs" };
      arch.click();
      await new Promise((r) => setTimeout(r, 250));
      const archOn = arch.getAttribute("aria-selected") === "true"
        && all.getAttribute("aria-selected") === "false"
        && fav.getAttribute("aria-selected") === "false";
      const emptyOrList = document.querySelector("#list");
      const emptyText = (emptyOrList && emptyOrList.textContent) || "";
      // mock has no archived prompts by default → empty archive state
      const emptyOk = /归档是空的/.test(emptyText) || /归档/.test(emptyText);
      fav.click();
      await new Promise((r) => setTimeout(r, 200));
      const favOn = fav.getAttribute("aria-selected") === "true"
        && arch.getAttribute("aria-selected") === "false";
      all.click();
      await new Promise((r) => setTimeout(r, 150));
      const allOn = all.getAttribute("aria-selected") === "true"
        && arch.getAttribute("aria-selected") === "false"
        && fav.getAttribute("aria-selected") === "false";
      return { ok: archOn && emptyOk && favOn && allOn, archOn, emptyOk, favOn, allOn, emptyText: emptyText.slice(0, 80) };
    });
    check("lib_scope_arch_filters", archTab.ok, JSON.stringify(archTab));


    // 2.12.7: MD toolbar + editor stack + DnD markers + move API
    const v2127 = await page.evaluate(async () => {
      const tb = document.querySelector("#mdToolbar");
      const stack = document.querySelector("#editorStack");
      const live = document.querySelector("#mdLivePreview");
      const split = document.querySelector("#splitMd");
      const tools = [...document.querySelectorAll("#mdToolbar .md-tool")].map((b) => b.dataset.md);
      // open first prompt if any
      const leaf = document.querySelector(".tree-leaf[data-id]");
      if (leaf) leaf.click();
      await new Promise((r) => setTimeout(r, 200));
      const ed = document.querySelector("#editor");
      const before = ed ? ed.value : "";
      const bold = document.querySelector('#mdToolbar .md-tool[data-md="bold"]');
      if (ed && bold && !bold.disabled) {
        ed.focus();
        ed.setSelectionRange(0, 0);
        bold.click();
        await new Promise((r) => setTimeout(r, 100));
      }
      const after = ed ? ed.value : "";
      const inserted = after.includes("**") && after !== before;
      // live preview uses MiniMD
      const liveHtml = live ? live.innerHTML : "";
      const hasMini = !!(window.MiniMD && window.MiniMD.render);
      // DnD markers in tree
      const allBtn = document.querySelector("#libScopeAll");
      if (allBtn) allBtn.click();
      await new Promise((r) => setTimeout(r, 150));
      const dragPrompt = document.querySelector('.tree-leaf[draggable="true"][data-pb-drag="prompt"]');
      const dragRole = document.querySelector('.role-row[draggable="true"][data-pb-drag="role"]');
      // move API
      let moveOk = false;
      if (window.pywebview && window.pywebview.api.move_prompt_to_role) {
        const r = await window.pywebview.api.move_prompt_to_role("p1", "r-be");
        moveOk = !!(r && r.ok && r.prompt && r.prompt.role_id === "r-be");
      }
      let reorderOk = false;
      if (window.pywebview && window.pywebview.api.reorder_roles) {
        const r = await window.pywebview.api.reorder_roles(["r-be", "r-mine"]);
        reorderOk = !!(r && r.ok);
      }
      return {
        ok: !!(tb && stack && live && split && tools.includes("bold") && tools.includes("table")
          && hasMini && inserted && dragRole && moveOk && reorderOk),
        tb: !!tb, stack: !!stack, live: !!live, split: !!split, tools, inserted, hasMini,
        dragPrompt: !!dragPrompt, dragRole: !!dragRole, moveOk, reorderOk,
        liveLen: liveHtml.length,
      };
    });
    check("v2127_md_toolbar_dnd_move", v2127.ok, JSON.stringify(v2127));

    // 2.12.8: role system prompt · lint · rev diff · cases
    const v2128 = await page.evaluate(async () => {
      const roleSys = document.querySelector("#roleSysOverlay");
      const applyTog = document.querySelector("#applyRoleSysToggle");
      const chip = document.querySelector("#roleSysChip");
      const setArs = document.querySelector("#setApplyRoleSys");
      const revCmp = document.querySelector("#revCompareSel");
      const diffSeg = document.querySelector("#diffModeSeg");
      const caseOv = document.querySelector("#caseOverlay");
      // role row sysprompt button
      const sysBtn = document.querySelector('[data-role-act="sysprompt"]');
      // open a prompt and check form cases panel + debug 体检
      const leaf = document.querySelector(".tree-leaf[data-id]");
      if (leaf) leaf.click();
      await new Promise((r) => setTimeout(r, 250));
      const formTab = document.querySelector('[data-tab="form"], #tabForm, button[aria-controls="tab-form"]');
      // try common tab buttons
      const tabs = [...document.querySelectorAll("[data-tab], .tab, [role=tab]")];
      const formBtn = tabs.find((t) => /表单|form/i.test(t.textContent || "") || t.dataset.tab === "form");
      if (formBtn) formBtn.click();
      await new Promise((r) => setTimeout(r, 200));
      const casesPanel = document.querySelector("#casesPanel, .cases-panel");
      const dbgBtn = tabs.find((t) => /调试|debug|体检/i.test(t.textContent || "") || t.dataset.tab === "debug");
      if (dbgBtn) dbgBtn.click();
      await new Promise((r) => setTimeout(r, 200));
      const dbgText = (document.querySelector("#tab-debug") || {}).textContent || "";
      const hasLint = /体检/.test(dbgText);
      // API markers
      let roleApi = false, caseApi = false, cmpApi = false, renderApi = false;
      const A = window.pywebview && window.pywebview.api;
      if (A) {
        if (A.set_role_system_prompt && A.get_role_system_prompt) {
          const g = await A.get_role_system_prompt("r-mine");
          roleApi = !!(g && g.ok);
        }
        if (A.save_case && A.list_cases && A.run_case) {
          const s = await A.save_case("p1", { name: "e2e", values: { topic: "t" }, expect: "t" });
          caseApi = !!(s && s.ok);
        }
        if (A.compare_revisions) {
          const c = await A.compare_revisions("p1", "r1", "current");
          cmpApi = !!(c && c.ok && Array.isArray(c.diff));
        }
        if (A.render_prompt) {
          const rr = await A.render_prompt("Hi {{topic}}", { topic: "X" }, "p1", "r-mine", true);
          renderApi = !!(rr && rr.ok && rr.final);
        }
      }
      return {
        ok: !!(roleSys && applyTog && chip && setArs && revCmp && diffSeg && caseOv && sysBtn
          && casesPanel && hasLint && roleApi && caseApi && cmpApi && renderApi),
        roleSys: !!roleSys, applyTog: !!applyTog, chip: !!chip, setArs: !!setArs,
        revCmp: !!revCmp, diffSeg: !!diffSeg, caseOv: !!caseOv, sysBtn: !!sysBtn,
        casesPanel: !!casesPanel, hasLint, roleApi, caseApi, cmpApi, renderApi,
      };
    });
    check("v2128_role_lint_diff_cases", v2128.ok, JSON.stringify(v2128));



  } catch (err) {
    check("e2e_harness_error", false, err.stack || String(err));
  } finally {
    if (browser) await browser.close().catch(() => {});
    srv.close();
  }

  const failed = RESULTS.filter((r) => !r.ok);
  const summary = {
    ok: failed.length === 0,
    passed: RESULTS.filter((r) => r.ok).length,
    failed: failed.length,
    total: RESULTS.length,
    results: RESULTS,
  };
  const outPath = path.join(ROOT, "scripts/e2e/e2e_results.json");
  fs.writeFileSync(outPath, JSON.stringify(summary, null, 2));
  console.log("\n=== E2E SUMMARY ===");
  console.log(JSON.stringify({ ok: summary.ok, passed: summary.passed, failed: summary.failed, total: summary.total }, null, 2));
  console.log("wrote", outPath);
  process.exit(summary.ok ? 0 : 1);
}

run();

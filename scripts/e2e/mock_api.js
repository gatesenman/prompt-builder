(() => {
  const prompts = {
    "p1": {
      id: "p1", name: "周报生成", body: "请写一份{{语气:正式/轻松|正式}}的周报。\n\n本周：{{本周完成:多行|完成 A}}",
      tags: ["办公"], keywords: ["周报","汇报"], summary: "周报",
      favorite: false, pinned: false, builtin: false, archived: false,
      role_id: "r-mine", category_id: "", test_values: {}, last_values: {},
      var_count: 2, preview: "请写一份…", use_count: 1,
      updated_at: "2026-10-01T00:00:00", last_used_at: "2026-10-20T00:00:00",
      last_ai_run: null, cases: []
    },
    "p2": {
      id: "p2", name: "翻译润色", body: "翻译成{{目标语言:英文/日文|英文}}：\n{{原文:多行|hello}}",
      tags: ["写作"], keywords: ["翻译"], summary: "翻译",
      favorite: true, pinned: false, builtin: false, archived: false,
      role_id: "r-mine", category_id: "", test_values: {}, last_values: {},
      var_count: 2, preview: "翻译成…", use_count: 3,
      updated_at: "2026-10-02T00:00:00", last_used_at: "2026-10-21T00:00:00",
      last_ai_run: null, cases: []
    }
  };
  function listAll() { return Object.values(prompts).map(p => ({...p})); }
  let roleOrder = ["r-mine", "r-be"];
  const rolesMeta = {
    "r-mine": { id: "r-mine", name: "我的", order: 0, system_prompt: "" },
    "r-be": { id: "r-be", name: "后端工程师", order: 10, system_prompt: "你是后端专家。" },
  };
  function tree() {
    const byRole = { "r-mine": [], "r-be": [] };
    for (const p of listAll()) {
      const rid = p.role_id || "r-mine";
      if (!byRole[rid]) byRole[rid] = [];
      byRole[rid].push(p);
    }
    return {
      roles: roleOrder.map((id, i) => ({
        ...rolesMeta[id], order: i * 10,
        prompts: byRole[id] || [], categories: [], count: (byRole[id] || []).length,
        has_system_prompt: !!(rolesMeta[id].system_prompt || "").trim(),
      })),
    };
  }
  function textHasNoFormat(t) {
    return !/(输出|JSON|json|格式|Format|format|返回|结构|schema)/.test(t || "");
  }
  function analyze(body, values) {
    body = body || ""; values = values || {};
    const re = /\{\{([^}:|]+)(?::([^}|]+))?(?:\|([^}]*))?\}\}/g;
    const variables = []; const seen = new Set();
    let m;
    while ((m = re.exec(body))) {
      const name = m[1].trim();
      if (seen.has(name)) continue; seen.add(name);
      const opts = (m[2] || "").split("/").map(s => s.trim()).filter(Boolean);
      variables.push({
        name, control: opts.length > 1 ? "select" : ((m[2]||"").includes("多行") ? "multiline" : "text"),
        options: opts.length > 1 ? opts : [], default: m[3] ?? null, required: m[3] == null,
        count: 1, lines: [1], control_label: opts.length > 1 ? "选择" : "单行"
      });
    }
    let rendered = body.replace(/\{\{([^}:|]+)(?::([^}|]+))?(?:\|([^}]*))?\}\}/g, (_, n, _c, d) => {
      const k = n.trim();
      return (values[k] != null && values[k] !== "") ? String(values[k]) : (d != null ? String(d) : "");
    });
    const missing = [];
    for (const v of variables) {
      if (v.required && (values[v.name] == null || values[v.name] === "")) missing.push(v.name);
    }
    const nl = String.fromCharCode(10);
    const chars = body.length, lines = body.split(nl).length;
    const rchars = rendered.length, rlines = rendered.split(nl).length;
    const issues = [];
    if (textHasNoFormat(body) && body.trim()) {
      issues.push({ level: "info", code: "missing_output_format", message: "未检测到输出格式提示", line: 0, col: 0 });
    }
    const counts = { error: 0, warn: 0, info: 0 };
    for (const i of issues) counts[i.level] = (counts[i.level] || 0) + 1;
    return {
      ok: true, variables, issues, issue_counts: counts,
      missing, rendered, segments: [{k:"text", t: rendered}],
      stats: {
        template: { chars, chars_no_space: chars, cjk: 0, words: 0, lines, tokens: Math.ceil(chars/4) },
        rendered: { chars: rchars, chars_no_space: rchars, cjk: 0, words: 0, lines: rlines, tokens: Math.ceil(rchars/4) }
      }
    };
  }
  const settings = {
    theme: "system", library_sort: "recent", onboarding: 99, starters_dismissed: true,
    admin_mode: false, ai_profiles: [], ai_default_profile: "", apply_role_system_prompt: true
  };
  const api = {
    get_bootstrap() {
      return {
        onboarding: false, version: "2.12.8", settings, prompts: listAll(), tree: tree(),
        tags: ["办公","写作"], starters: [], stats: { prompts: 2 },
        quick: { installed: false }, migration: null, recovered: false,
        data_dir: "/tmp/pb-e2e", log_path: "/tmp/pb-e2e.log"
      };
    },
    list_prompts(query, sort, tag, favOnly, archivedOnly) {
      let items = listAll();
      if (archivedOnly) items = items.filter(p => !!p.archived);
      else items = items.filter(p => !p.archived);
      if (favOnly) items = items.filter(p => !!p.favorite);
      const q = (query || "").toLowerCase();
      if (q) items = items.filter(p =>
        (p.name + " " + (p.keywords||[]).join(" ") + " " + (p.tags||[]).join(" ") + " " + p.body).toLowerCase().includes(q));
      if (tag) items = items.filter(p => (p.tags||[]).includes(tag));
      return items;
    },
    get_tree(query) {
      if (!query) return tree();
      const q = String(query).toLowerCase();
      const roles = tree().roles.map(r => ({
        ...r, prompts: r.prompts.filter(p =>
          (p.name + " " + (p.keywords||[]).join(" ") + " " + p.body).toLowerCase().includes(q))
      }));
      return { roles };
    },
    get_prompt(id) { return prompts[id] ? {...prompts[id]} : null; },
    save_prompt(id, patch) {
      if (!prompts[id]) return { ok: false, error: "missing" };
      Object.assign(prompts[id], patch || {});
      return { ok: true, prompt: {...prompts[id]} };
    },
    analyze(body, values) { return analyze(body, values); },
    set_keywords(id, kws) {
      if (!prompts[id]) return { ok: false };
      prompts[id].keywords = kws || [];
      return { ok: true, prompt: {...prompts[id]} };
    },
    set_tags(id, tags) {
      if (!prompts[id]) return { ok: false };
      prompts[id].tags = tags || [];
      const all = [...new Set(listAll().flatMap(p => p.tags || []))];
      return { ok: true, prompt: {...prompts[id]}, tags: all };
    },
    set_favorite(id, v) { if (prompts[id]) prompts[id].favorite = !!v; return { ok: true }; },
    set_pinned(id, v) { if (prompts[id]) prompts[id].pinned = !!v; return { ok: true }; },
    set_settings(patch) { Object.assign(settings, patch || {}); return { ok: true, settings }; },
    get_settings() { return {...settings}; },
    breadcrumb(id) {
      const p = prompts[id];
      return { ok: true, role: { id: "r-mine", name: "我的" }, category: null, prompt: p ? { id: p.id, name: p.name } : null };
    },
    quick_status() { return { installed: false, ok: true, text: "未安装" }; },
    admin_status() { return { elevated: false, can_elevate: false }; },
    sample_values(body) {
      const a = analyze(body, {});
      const out = {};
      for (const v of a.variables) out[v.name] = v.default != null ? v.default : (v.options[0] || "示例");
      return out;
    },
    copy_text(text) { return { ok: true, chars: (text||"").length }; },
    save_test_values(id, vals) { if (prompts[id]) prompts[id].test_values = vals || {}; return { ok: true }; },
    complete_onboarding() { settings.onboarding = 99; return { ok: true }; },
    get_stats() { return { prompts: 2 }; },
    list_ai_profiles() { return { ok: true, profiles: [], default_profile: "" }; },
    list_ai_presets() {
      return [
        { id: "openai", name: "OpenAI", kind: "openai", base_url: "https://api.openai.com/v1",
          models: ["gpt-4o", "gpt-4o-mini"], default_model: "gpt-4o-mini" },
        { id: "deepseek", name: "DeepSeek", kind: "openai", base_url: "https://api.deepseek.com/v1",
          models: ["deepseek-chat", "deepseek-reasoner"], default_model: "deepseek-chat" },
      ];
    },
    
    ai_fill_form(variables, user_text, profile_id, model) {
      if (!user_text || !String(user_text).trim()) return { ok: false, values: {}, error: "请先描述你的需求", need_settings: false };
      const vals = {};
      (variables || []).forEach((v) => {
        if (!v || !v.name) return;
        if (v.control === "select" || v.control === "radio") vals[v.name] = (v.options && v.options[0]) || "";
        else if (v.control === "multiselect") vals[v.name] = (v.options || []).slice(0, 2).join("、");
        else if (v.control === "number") vals[v.name] = "100";
        else vals[v.name] = "示例：" + String(user_text).slice(0, 20);
      });
      return { ok: true, values: vals, error: "", need_settings: false, model: model || "mock", label: "mock" };
    },
    list_ai_models(spec) {
      const presets = this.list_ai_presets();
      const p = presets.find(x => x.id === (spec && spec.preset)) || presets[0];
      return { ok: true, models: (p && p.models) || ["gpt-4o-mini"], source: "preset", error: "" };
    },
    move_prompt_to_role(prompt_id, role_id) {
      const p = prompts[prompt_id];
      if (!p) return { ok: false, error: "missing" };
      if (p.builtin || p.system) return { ok: false, error: "内置提示词请先复制后编辑" };
      if (!rolesMeta[role_id]) return { ok: false, error: "无法移动到该角色" };
      p.role_id = role_id;
      return { ok: true, prompt: { ...p } };
    },
    reorder_roles(role_ids) {
      const ids = (role_ids || []).filter((id) => rolesMeta[id]);
      if (ids.length) roleOrder = ids;
      return { ok: true };
    },

    get_role_system_prompt(role_id) {
      const r = rolesMeta[role_id];
      if (!r) return { ok: false, system_prompt: "", error: "角色不存在" };
      return { ok: true, role_id, name: r.name, system_prompt: r.system_prompt || "", builtin: !!r.builtin };
    },
    set_role_system_prompt(role_id, text) {
      const r = rolesMeta[role_id];
      if (!r) return { ok: false, error: "角色不存在" };
      r.system_prompt = String(text || "");
      return { ok: true, role: { ...r } };
    },
    render_prompt(body, values, prompt_id, role_id, apply_role_system) {
      const a = analyze(body || "", values || {});
      let sp = "";
      const use = apply_role_system !== false && settings.apply_role_system_prompt !== false;
      const rid = role_id || (prompts[prompt_id] && prompts[prompt_id].role_id) || "";
      if (use && rolesMeta[rid]) sp = (rolesMeta[rid].system_prompt || "").trim();
      const final = sp ? (sp + "\n\n---\n\n" + a.rendered) : a.rendered;
      return { ok: true, rendered: a.rendered, final, system_prompt: sp, applied: !!sp, separator: "---" };
    },
    list_cases(prompt_id) {
      const p = prompts[prompt_id];
      if (!p) return { ok: false, cases: [], error: "提示词不存在" };
      return { ok: true, cases: [...(p.cases || [])] };
    },
    save_case(prompt_id, caseObj) {
      const p = prompts[prompt_id];
      if (!p) return { ok: false, error: "提示词不存在" };
      p.cases = p.cases || [];
      const c = caseObj || {};
      if (c.id) {
        const i = p.cases.findIndex(x => x.id === c.id);
        if (i >= 0) p.cases[i] = { ...p.cases[i], ...c, values: c.values || {} };
      } else {
        if (p.cases.length >= 10) return { ok: false, error: "每个提示词最多 10 个用例" };
        const nc = { id: "case-" + Math.random().toString(16).slice(2, 10), name: c.name || "用例",
          values: c.values || {}, expect: c.expect || "", notes: c.notes || "", last_run: {} };
        p.cases.push(nc);
        return { ok: true, case: nc, cases: [...p.cases] };
      }
      return { ok: true, case: c, cases: [...p.cases] };
    },
    delete_case(prompt_id, case_id) {
      const p = prompts[prompt_id];
      if (!p) return { ok: false, error: "提示词不存在" };
      p.cases = (p.cases || []).filter(c => c.id !== case_id);
      return { ok: true, cases: [...p.cases] };
    },
    run_case(prompt_id, case_id) {
      const p = prompts[prompt_id];
      if (!p) return { ok: false, error: "提示词不存在" };
      const c = (p.cases || []).find(x => x.id === case_id);
      if (!c) return { ok: false, error: "用例不存在" };
      const rr = this.render_prompt(p.body, c.values || {}, prompt_id, p.role_id, true);
      const expect = (c.expect || "").trim();
      const soft = expect ? ((rr.final || "").includes(expect) || (rr.rendered || "").includes(expect)) : null;
      return { ok: true, used_ai: false, rendered: rr.rendered, final: rr.final, output: rr.final,
        expect, soft_match: soft, match: soft === true ? "pass" : (soft === false ? "fail" : "n/a"),
        error: "", cases: p.cases };
    },
    list_revisions(prompt_id) {
      return [{ id: "r1", name: "旧版", body: "old\nline", saved_at: "2026-10-01T00:00:00", source: "manual", note: "" }];
    },
    compare_revisions(prompt_id, rev_a, rev_b) {
      const a = { id: rev_a, name: "旧版", body: "old\nline", saved_at: "2026-10-01T00:00:00" };
      const cur = prompts[prompt_id] || { name: "x", body: "new\nline" };
      const b = rev_b === "current"
        ? { id: "current", name: cur.name, body: cur.body, saved_at: cur.updated_at }
        : { id: rev_b, name: "另一版", body: "other", saved_at: "2026-10-02T00:00:00" };
      const diff = [
        { op: "del", text: "old" }, { op: "ins", text: "new" }, { op: "eq", text: "line" }
      ];
      return { ok: true, a, b, diff, name_diff: [], combined_diff: diff, name_changed: a.name !== b.name };
    },

    hide_window() { return { ok: true }; },
    quit_app() { return { ok: true }; },
  };
  const wrapped = {};
  for (const [k, fn] of Object.entries(api)) {
    wrapped[k] = (...args) => Promise.resolve(fn(...args));
  }
  const apiProxy = new Proxy(wrapped, {
    get(target, prop) {
      if (prop in target) return target[prop];
      return (..._args) => Promise.resolve({ ok: true });
    }
  });
  window.pywebview = { api: apiProxy };
  window.dispatchEvent(new Event("pywebviewready"));
})();

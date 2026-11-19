"""Prompt generate / rewrite / review system prompts + orchestration."""
from __future__ import annotations
from typing import Any
from ai_providers import chat_completion, parallel_chat

SYS_GENERATE = """你是资深提示词工程师，为 IDE / Cursor / 编程助手编写可直接粘贴使用的提示词模板。
硬性要求：
1. 先输出两行元数据，然后空一行，再输出 Markdown 正文（不要用代码围栏包整篇）：
   标题：【场景/动作】短名（6–16字，动词+对象或短名词；不要角色名前缀、不要「完整流程」）
   关键词：词1, 词2, 词3（中文为主，可含常见英文技术别名，如 weekly/CR/PR/API；3–8个，覆盖同义词与场景）
2. 正文可含标题与列表；需要用户每次替换的内容必须写成 {{变量名}}；可选默认值用 {{名:默认}}；枚举用 {{名:选项A/选项B|默认}}；多行用 {{名:多行}}。
3. 正文结构包含：角色与目标、上下文（变量）、工作步骤、输出格式、质量门槛/自检。
4. 中文撰写；技术术语可保留英文。不要解释你的过程。"""

SYS_REWRITE = """你是提示词润色专家。在保留原意与关键变量的前提下改写提示词，使结构更清晰、变量更规范、输出格式更明确。
要求：
- 输出完整改写后的 Markdown 正文（不要解释、不要 diff）。
- 变量统一为 {{变量名}} / {{名:默认}} / {{名:A/B|默认}} / {{名:多行}}。
- 补齐缺失的：角色、步骤、输出格式、质量门槛。
- 删除空话与重复；保持专业、可执行。"""

SYS_REVIEW = """你是提示词评审专家。对照清单评审给定模板，指出问题并给出可粘贴的修改建议。
评审维度：
1. 目标与角色是否清晰
2. 变量设计（命名、必填/默认、多行、枚举）是否合理
3. 步骤是否可执行、有无歧义
4. 输出格式是否具体
5. 安全（有无诱导泄露密钥、越权）
6. IDE 可用性（能否直接粘贴进 Cursor/IDE 得到好结果）
输出 Markdown：
## 总评（优/良/需改）
## 问题清单（严重度 · 位置 · 说明）
## 具体改写建议（按优先级）
## 可选的变量表
不要输出完整重写正文，除非某一段必须示例。"""


def _user_gen(goal: str, audience: str, extra: str) -> str:
    return (
        f"## 目标\n{goal.strip()}\n\n"
        f"## 使用场景 / 受众\n{(audience or 'IDE 中的编程助手').strip()}\n\n"
        f"## 额外要求\n{(extra or '无').strip()}\n"
    )


def _user_rewrite(body: str, instruction: str) -> str:
    return (
        f"## 改写要求\n{(instruction or '结构更清晰，变量与输出格式更专业').strip()}\n\n"
        f"## 原提示词\n{body.strip()}\n"
    )


def _user_review(body: str) -> str:
    return f"## 待评审提示词\n{body.strip()}\n"


def run_generate(target: dict, goal: str, audience: str = "", extra: str = "", **kw) -> dict:
    messages = [
        {"role": "system", "content": SYS_GENERATE},
        {"role": "user", "content": _user_gen(goal, audience, extra)},
    ]
    return chat_completion(
        kind=target.get("kind") or "openai",
        base_url=target.get("base_url") or "",
        api_key=target.get("api_key") or "",
        model=target.get("model") or "",
        messages=messages,
        temperature=kw.get("temperature", 0.4),
        max_tokens=kw.get("max_tokens", 4096),
        timeout=kw.get("timeout", 90.0),
    )


def run_rewrite(target: dict, body: str, instruction: str = "", **kw) -> dict:
    messages = [
        {"role": "system", "content": SYS_REWRITE},
        {"role": "user", "content": _user_rewrite(body, instruction)},
    ]
    return chat_completion(
        kind=target.get("kind") or "openai",
        base_url=target.get("base_url") or "",
        api_key=target.get("api_key") or "",
        model=target.get("model") or "",
        messages=messages,
        temperature=kw.get("temperature", 0.3),
        max_tokens=kw.get("max_tokens", 4096),
        timeout=kw.get("timeout", 90.0),
    )


def run_review(target: dict, body: str, **kw) -> dict:
    messages = [
        {"role": "system", "content": SYS_REVIEW},
        {"role": "user", "content": _user_review(body)},
    ]
    return chat_completion(
        kind=target.get("kind") or "openai",
        base_url=target.get("base_url") or "",
        api_key=target.get("api_key") or "",
        model=target.get("model") or "",
        messages=messages,
        temperature=kw.get("temperature", 0.2),
        max_tokens=kw.get("max_tokens", 3072),
        timeout=kw.get("timeout", 90.0),
    )


def run_parallel_test(
    targets: list[dict],
    *,
    rendered: str = "",
    system: str = "",
    user: str = "",
    **kw,
) -> list[dict]:
    """Parallel compare: either pass rendered prompt as user message, or system+user."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    content = (user or rendered or "").strip()
    if not content:
        return [{"id": t.get("id"), "ok": False, "text": "", "error": "测试内容为空", "latency_ms": 0} for t in targets]
    messages.append({"role": "user", "content": content})
    return parallel_chat(
        targets,
        messages,
        temperature=kw.get("temperature", 0.4),
        max_tokens=kw.get("max_tokens", 4096),
        timeout=kw.get("timeout", 90.0),
        max_workers=kw.get("max_workers", 6),
    )


def resolve_target_from_profile(profile: dict, api_key_plain: str, model: str | None = None) -> dict:
    return {
        "id": profile.get("id") or profile.get("preset") or "p",
        "label": profile.get("name") or profile.get("preset") or "model",
        "provider": profile.get("name") or profile.get("preset") or "",
        "kind": profile.get("kind") or "openai",
        "base_url": profile.get("base_url") or "",
        "api_key": api_key_plain,
        "model": model or profile.get("default_model") or (profile.get("models") or [""])[0],
    }


SYS_JUDGE = """你是严格的 LLM 输出评审员。根据「原始提示词」与各模型回复，按统一量规打分。
量规（每项 1–5，再取平均四舍五入为总分 1–5）：
1. 指令遵循  2. 完整性  3. 格式规范  4. 实用性
输出严格 JSON 数组（不要 Markdown 围栏），每项对应输入顺序：
[{"i":0,"score":4,"note":"一句话理由"}, ...]
score 必须是 1–5 整数。只输出 JSON。"""


def run_judge(target: dict, rendered: str, results: list, **kw) -> dict:
    lines = []
    for i, row in enumerate(results or []):
        label = row.get("label") or row.get("model") or f"#{i}"
        body = (row.get("text") or row.get("error") or "").strip()[:3000]
        lines.append(f"### [{i}] {label}\n{body or '(空)'}")
    user = (
        f"## 原始提示词（已渲染）\n{(rendered or '')[:6000]}\n\n"
        f"## 各模型回复\n" + "\n\n".join(lines)
    )
    messages = [
        {"role": "system", "content": SYS_JUDGE},
        {"role": "user", "content": user},
    ]
    r = chat_completion(
        kind=target.get("kind") or "openai",
        base_url=target.get("base_url") or "",
        api_key=target.get("api_key") or "",
        model=target.get("model") or "",
        messages=messages,
        temperature=kw.get("temperature", 0.1),
        max_tokens=kw.get("max_tokens", 2048),
        timeout=kw.get("timeout", 90.0),
    )
    scores = []
    if r.get("ok"):
        import json, re
        text = r.get("text") or ""
        m = re.search(r"\[[\s\S]*\]", text)
        try:
            arr = json.loads(m.group(0) if m else text)
            if isinstance(arr, list):
                for item in arr:
                    if not isinstance(item, dict):
                        continue
                    scores.append({
                        "i": int(item.get("i", len(scores))),
                        "score": max(1, min(5, int(item.get("score") or 0))),
                        "note": str(item.get("note") or "")[:200],
                    })
        except Exception:
            pass
    return {"ok": r.get("ok"), "text": r.get("text") or "", "error": r.get("error") or "",
            "latency_ms": r.get("latency_ms"), "scores": scores}


SYS_FILL_FORM = """你是表单填写助手。根据用户的自然语言需求，为给定变量表填写值。
只输出一个 JSON 对象（不要 Markdown 围栏，不要解释），键必须是变量名，值必须是字符串。
规则：
- text / multiline：按需求写简洁中文（或多行文本）
- number：只输出数字字符串
- select / radio：值必须是 options 列表中的某一项（原文照抄）
- multiselect：多个选项用中文顿号「、」连接，且每一项都必须在 options 中；可不选则输出空字符串
- 必填字段尽量给出合理值；未提及的可选字段可省略或填 ""
- 不要编造不在 options 中的枚举值"""


def _coerce_fill_values(variables: list, raw: dict) -> dict:
    """Validate AI JSON against schema; drop/clamp invalid enum values."""
    from prompt_syntax import MULTI_JOIN, _split_multi_default, _is_number
    out = {}
    raw = raw if isinstance(raw, dict) else {}
    for v in variables or []:
        if isinstance(v, dict):
            name, ctl, opts, default = v.get("name"), v.get("control") or "text", v.get("options") or [], v.get("default")
        else:
            name, ctl, opts, default = v.name, v.control, v.options, v.default
        if not name or name not in raw:
            continue
        val = raw.get(name)
        if val is None:
            continue
        val = str(val).strip() if not isinstance(val, str) else val.strip()
        if ctl in ("select", "radio"):
            if opts and val not in opts:
                # try soft match
                hit = next((o for o in opts if o.lower() == val.lower()), None)
                if hit is None:
                    continue
                val = hit
        elif ctl == "multiselect":
            parts = _split_multi_default(val)
            parts = [p for p in parts if (not opts) or p in opts]
            val = MULTI_JOIN.join(parts)
        elif ctl == "number":
            if val and not _is_number(val):
                continue
        out[name] = val
    return out


def run_fill_form(target: dict, variables: list, user_text: str, **kw) -> dict:
    """Fill form fields from natural language. Returns {ok, values, text, error, ...}."""
    import json, re
    user_text = (user_text or "").strip()
    if not user_text:
        return {"ok": False, "values": {}, "error": "请先描述你的需求", "text": "", "latency_ms": 0}
    if not variables:
        return {"ok": False, "values": {}, "error": "没有可填写的变量", "text": "", "latency_ms": 0}
    schema = []
    for v in variables:
        d = v if isinstance(v, dict) else (v.to_dict() if hasattr(v, "to_dict") else dict(v))
        schema.append({
            "name": d.get("name"),
            "control": d.get("control") or "text",
            "control_label": d.get("control_label") or d.get("control") or "text",
            "options": list(d.get("options") or []),
            "required": bool(d.get("required")),
            "default": d.get("default"),
        })
    user = (
        "## 变量表（JSON）\n"
        + json.dumps(schema, ensure_ascii=False)
        + "\n\n## 用户需求\n"
        + user_text
        + "\n\n请只输出 JSON 对象。"
    )
    messages = [
        {"role": "system", "content": SYS_FILL_FORM},
        {"role": "user", "content": user},
    ]
    r = chat_completion(
        kind=target.get("kind") or "openai",
        base_url=target.get("base_url") or "",
        api_key=target.get("api_key") or "",
        model=target.get("model") or "",
        messages=messages,
        temperature=kw.get("temperature", 0.2),
        max_tokens=kw.get("max_tokens", 2048),
        timeout=kw.get("timeout", 60.0),
    )
    if not r.get("ok"):
        return {"ok": False, "values": {}, "error": r.get("error") or "AI 填写失败",
                "text": r.get("text") or "", "latency_ms": r.get("latency_ms")}
    text = r.get("text") or ""
    parsed = None
    m = re.search(r"\{[\s\S]*\}", text)
    try:
        parsed = json.loads(m.group(0) if m else text)
    except Exception:
        return {"ok": False, "values": {}, "error": "AI 返回的不是有效 JSON，请重试或手动填写",
                "text": text, "latency_ms": r.get("latency_ms")}
    values = _coerce_fill_values(variables, parsed if isinstance(parsed, dict) else {})
    if not values:
        return {"ok": False, "values": {}, "error": "AI 未能匹配到有效字段值，请改写描述或手动填写",
                "text": text, "latency_ms": r.get("latency_ms")}
    return {"ok": True, "values": values, "error": "", "text": text,
            "latency_ms": r.get("latency_ms"), "model": target.get("model"),
            "label": target.get("label")}


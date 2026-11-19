"""Markdown prompt variable syntax: parse, validate, render, stats.

Syntax (inside any Markdown text):
    {{名称}}                    必填，单行文本
    {{名称|默认值}}             可选，空着时使用默认值（{{名称|}} = 默认为空）
    {{名称:多行}}               多行文本（别名：long / multiline / textarea / 长文本）
    {{名称:数字|300}}           数字（别名：number / num）
    {{名称:正式/轻松/幽默|正式}} 下拉选项，用 / 分隔
    {{优先级:单选:高/中/低|中}}  单选（别名：radio）；选项用 / 分隔
    {{标签:多选:技术/产品/设计}} 多选（别名：checkbox / multi）；渲染时用顿号「、」连接
    \\{{ 原样 }}                 反斜杠转义，输出字面量 {{
The same name may appear several times; it is one form field and every occurrence
receives the same value. This module is the single source of truth for the editor,
the debug panel and quick-pick insertion.
"""
from __future__ import annotations
import re
from copy import copy
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from typing import Any

MULTILINE_ALIASES = {"多行", "长文本", "long", "multiline", "textarea", "text*"}
NUMBER_ALIASES = {"数字", "number", "num"}
TEXT_ALIASES = {"", "单行", "文本", "text"}
RADIO_ALIASES = {"单选", "radio"}
MULTI_ALIASES = {"多选", "checkbox", "checkboxes", "multi", "multiselect"}
CONTROL_LABEL = {
    "text": "单行", "multiline": "多行", "number": "数字", "select": "下拉",
    "radio": "单选", "multiselect": "多选",
}
MULTI_JOIN = "、"  # rendered join for multiselect values


@dataclass
class Token:
    start: int
    end: int
    raw: str
    name: str
    control: str = "text"
    options: list[str] = field(default_factory=list)
    default: str | None = None
    line: int = 1
    col: int = 1


@dataclass
class Variable:
    name: str
    control: str = "text"
    options: list[str] = field(default_factory=list)
    default: str | None = None
    required: bool = True
    count: int = 0
    lines: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["control_label"] = CONTROL_LABEL.get(self.control, self.control)
        return d


def _issue(level: str, code: str, message: str, line: int = 0, col: int = 0, var: str = "") -> dict:
    return {"level": level, "code": code, "message": message, "line": line, "col": col, "var": var}


def _line_col(text: str, pos: int, line_starts: list[int]) -> tuple[int, int]:
    lo, hi = 0, len(line_starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if line_starts[mid] <= pos:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1, pos - line_starts[lo] + 1


def _fence_mask(text: str) -> list[bool]:
    """Per-line flag: True if the line is inside a ``` / ~~~ fenced code block."""
    mask, inside, marker = [], False, ""
    for ln in text.split("\n"):
        s = ln.lstrip()
        if not inside and (s.startswith("```") or s.startswith("~~~")):
            inside, marker = True, s[:3]
            mask.append(True)
            continue
        if inside:
            mask.append(True)
            if s.startswith(marker):
                inside = False
            continue
        mask.append(False)
    return mask


def _split_multi_default(s: str) -> list[str]:
    """Split a multiselect default/value on顿号、comma, or slash."""
    s = (s or "").strip()
    if not s:
        return []
    for sep in (MULTI_JOIN, ",", "/", "，"):
        if sep in s:
            return [p.strip() for p in s.split(sep) if p.strip()]
    return [s]


def _parse_choice_ctype(ctype: str) -> tuple[str | None, list[str]]:
    """Detect ``单选:a/b`` / ``radio:a/b`` / ``多选:a/b`` before bare select."""
    for sep in (":", "："):
        if sep not in ctype:
            continue
        left, right = ctype.split(sep, 1)
        left_s, right_s = left.strip(), right.strip()
        low = left_s.lower()
        opts = [o.strip() for o in right_s.split("/") if o.strip()]
        if low in RADIO_ALIASES or left_s in RADIO_ALIASES:
            return "radio", opts
        if low in MULTI_ALIASES or left_s in MULTI_ALIASES:
            return "multiselect", opts
    # bare alias with no options yet
    low = ctype.lower()
    if low in RADIO_ALIASES or ctype in RADIO_ALIASES:
        return "radio", []
    if low in MULTI_ALIASES or ctype in MULTI_ALIASES:
        return "multiselect", []
    return None, []


def _parse_inner(inner: str) -> tuple[str, str, list[str], str | None, list[tuple[str, str, str]]]:
    """Return name, control, options, default, problems[(level, code, msg)]."""
    problems: list[tuple[str, str, str]] = []
    default: str | None = None
    head = inner
    if "|" in inner:
        head, default = inner.split("|", 1)
        default = default.strip()
    name, ctype = head, ""
    if ":" in head:
        name, ctype = head.split(":", 1)
    elif "：" in head:  # full-width colon
        name, ctype = head.split("：", 1)
    name, ctype = name.strip(), ctype.strip()
    control, options = "text", []
    low = ctype.lower()
    choice_ctl, choice_opts = _parse_choice_ctype(ctype)
    if choice_ctl:
        control, options = choice_ctl, choice_opts
        label = CONTROL_LABEL.get(control, control)
        if len(options) < 2:
            problems.append(("warn", f"{control}_options", f"{label}至少需要两个选项（用 / 分隔）"))
        if len(set(options)) != len(options):
            problems.append(("warn", f"{control}_dup", f"{label}选项有重复"))
        if control == "radio" and default not in (None, "") and options and default not in options:
            problems.append(("warn", "radio_default", f"默认值「{default}」不在单选选项中"))
        if control == "multiselect" and default not in (None, ""):
            bad = [x for x in _split_multi_default(default) if options and x not in options]
            if bad:
                problems.append(("warn", "multiselect_default",
                                 f"默认值含不在选项中的项：{'、'.join(bad)}"))
            else:
                # normalize default to MULTI_JOIN for stable render
                parts = [x for x in _split_multi_default(default) if x in options] if options else _split_multi_default(default)
                default = MULTI_JOIN.join(parts)
    elif "/" in ctype:
        control = "select"
        options = [o.strip() for o in ctype.split("/") if o.strip()]
        if len(options) < 2:
            problems.append(("warn", "select_options", "下拉至少需要两个选项（用 / 分隔）"))
        if len(set(options)) != len(options):
            problems.append(("warn", "select_dup", "下拉选项有重复"))
    elif low in MULTILINE_ALIASES or ctype in MULTILINE_ALIASES:
        control = "multiline"
    elif low in NUMBER_ALIASES or ctype in NUMBER_ALIASES:
        control = "number"
    elif low in TEXT_ALIASES or ctype in TEXT_ALIASES:
        control = "text"
    else:
        problems.append(("warn", "unknown_control", f"未知控件类型「{ctype}」，按单行文本处理"))
    if control == "select" and default not in (None, "") and options and default not in options:
        problems.append(("warn", "select_default", f"默认值「{default}」不在下拉选项中"))
    if control == "number" and default not in (None, "") and not _is_number(default):
        problems.append(("warn", "number_default", f"数字变量的默认值「{default}」不是数字"))
    return name, control, options, default, problems


def _is_number(s: str) -> bool:
    try:
        float(str(s).strip().replace(",", ""))
        return True
    except ValueError:
        return False


def normalize_newlines(text: str) -> str:
    """CRLF / lone CR -> LF so positions, line numbers and output are consistent."""
    text = text or ""
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


_SCAN = re.compile(r"\\\{\{|\{\{|\}\}")
LONG_TEMPLATE = 200_000


def tokenize(text: str) -> tuple[list[Token], list[dict], list[tuple[int, int, str]]]:
    """Scan text (regex driven, linear time). Returns tokens, issues and escape spans.

    Rules
      * ``\\{{ ... }}``  literal; its matching ``}}`` on the same line is not reported as stray
      * ``{{{名}}}``     the extra outer braces are literal text: renders ``{值}``
      * ``{{a {{b}}``   the first ``{{`` is reported unclosed, ``{{b}}`` still works
      * a variable may not span lines (almost always a missing ``}}``)
      * problems inside fenced code blocks are downgraded to info
    """
    text = normalize_newlines(text)
    n = len(text)
    line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
    fence = _fence_mask(text)
    tokens: list[Token] = []
    issues: list[dict] = []
    escapes: list[tuple[int, int, str]] = []

    def where(pos: int) -> tuple[int, int, bool]:
        line, col = _line_col(text, pos, line_starts)
        return line, col, (fence[line - 1] if line - 1 < len(fence) else False)

    def eol_of(pos: int) -> int:
        # O(log n) via line_starts (a text.find per token made long single lines quadratic)
        line, _ = _line_col(text, pos, line_starts)
        return line_starts[line] - 1 if line < len(line_starts) else n

    next_close_cache = [-2, -1]  # [query pos, result]; queries are monotonic -> amortised linear

    def next_close(pos: int) -> int:
        q, r = next_close_cache
        if q <= pos and (r == -1 or r >= pos) and q != -2:
            return r
        r = text.find("}}", pos)
        next_close_cache[0], next_close_cache[1] = pos, r
        return r

    pos = 0
    while pos < n:
        m = _SCAN.search(text, pos)
        if not m:
            break
        i, tok = m.start(), m.group()
        if tok == "\\{{":
            eol = eol_of(i)
            nested = text.find("{{", i + 3, eol)
            # only a "}}" before the next "{{" closes the escape (bounded search -> linear)
            close = text.find("}}", i + 3, nested if nested != -1 else eol)
            end = close + 2 if close != -1 else i + 3
            escapes.append((i, end, text[i + 1:end]))
            pos = end
            continue
        if tok == "}}":
            line, col, in_code = where(i)
            ls = line_starts[line - 1]
            # JSON-like text ({"a": {"b": 1}}) legitimately ends with }} -> only a hint
            json_like = "{" in text[ls:i]
            if not in_code:
                lvl = "info" if json_like else "warn"
                issues.append(_issue(lvl, "stray_close", "多余的「}}」，前面没有「{{」（括号不配对）", line, col))
            pos = i + 2
            continue
        # tok == "{{"
        if i + 2 < n and text[i + 2] == "{":
            pos = i + 1  # "{{{" -> first brace is literal, rescan from the next one
            continue
        line, col, in_code = where(i)
        eol = eol_of(i)
        close = text.find("}}", i + 2, eol)
        if close == -1:
            close = next_close(i + 2)  # only decides which message to show
        if close == -1 or close > eol:
            lvl = "info" if in_code else "error"
            msg = ("变量跨行，可能缺少「}}」（括号不配对）" if close != -1
                   else "「{{」没有对应的「}}」（括号不配对）")
            issues.append(_issue(lvl, "unclosed", msg, line, col))
            pos = i + 2
            continue
        nested = text.find("{{", i + 2, close)
        while nested != -1 and text[nested - 1] == "\\":
            nested = text.find("{{", nested + 2, close)
        if nested != -1:
            lvl = "info" if in_code else "error"
            issues.append(_issue(lvl, "unclosed", "「{{」没有对应的「}}」（括号不配对或嵌套）", line, col))
            pos = nested
            continue
        inner = text[i + 2:close]
        raw = text[i:close + 2]
        name, control, options, default, problems = _parse_inner(inner)
        if not name:
            issues.append(_issue("info" if in_code else "error", "empty_name", f"空变量名：{raw}", line, col))
        elif "{" in name or "}" in name:
            issues.append(_issue("info" if in_code else "error", "bad_name",
                                 f"变量名含非法字符「{{」或「}}」：{raw}", line, col))
        else:
            if len(name) > 40:
                problems.append(("warn", "long_name", "变量名过长（超过 40 个字符），表单里会被截断显示"))
            for lvl, code, msg in problems:
                issues.append(_issue(lvl, code, f"{msg}：{raw}", line, col, name))
            tokens.append(Token(i, close + 2, raw, name, control, options, default, line, col))
        pos = close + 2
    # single-brace hint, outside code fences, e.g. {名称}
    for m in re.finditer(r"(?<![{\\])\{([\u4e00-\u9fffA-Za-z_][\u4e00-\u9fff\w]{0,20})\}(?!\})", text):
        line, col, in_code = where(m.start())
        if in_code:
            continue
        issues.append(_issue("info", "single_brace", f"「{m.group(0)}」是单花括号，变量需要写成 {{{{{m.group(1)}}}}}", line, col))
    if n > LONG_TEMPLATE:
        issues.append(_issue("info", "long_template", f"正文很长（{n} 字符），编辑和预览可能变慢"))
    return tokens, issues, escapes


def collect_variables(tokens: list[Token], issues: list[dict]) -> list[Variable]:
    by_name: dict[str, Variable] = {}
    order: list[str] = []
    for t in tokens:
        v = by_name.get(t.name)
        if v is None:
            v = Variable(name=t.name, control=t.control, options=list(t.options), default=t.default)
            by_name[t.name] = v
            order.append(t.name)
        else:
            if t.control != v.control or (t.control in ("select", "radio", "multiselect") and t.options != v.options):
                issues.append(_issue("warn", "dup_control",
                                     f"变量「{t.name}」多处的控件类型不一致，使用第一处（第 {v.lines[0]} 行）的设置",
                                     t.line, t.col, t.name))
            if t.default is not None:
                if v.default is None:
                    v.default = t.default
                elif t.default != v.default:
                    issues.append(_issue("warn", "dup_default",
                                         f"变量「{t.name}」默认值冲突：「{v.default}」与「{t.default}」，使用第一个",
                                         t.line, t.col, t.name))
        v.count += 1
        v.lines.append(t.line)
    out = []
    for name in order:
        v = by_name[name]
        v.required = v.default is None
        out.append(v)
    # partial defaults: info only
    for v in out:
        if v.default is not None and v.count > 1:
            no_default = [t for t in tokens if t.name == v.name and t.default is None]
            if no_default:
                issues.append(_issue("info", "partial_default",
                                     f"变量「{v.name}」部分出现处未写默认值，将统一使用默认值「{v.default}」",
                                     no_default[0].line, no_default[0].col, v.name))
    return out


def _value_for(v: Variable, values: dict) -> str | None:
    raw = (values or {}).get(v.name)
    if raw is not None and str(raw).strip() != "":
        return normalize_newlines(str(raw))
    if v.default is not None:
        return v.default
    return None


@lru_cache(maxsize=256)
def _parse_cached(text: str):
    tokens, issues, escapes = tokenize(text)
    variables = collect_variables(tokens, issues)
    return tuple(tokens), tuple(issues), tuple(escapes), tuple(variables)


def parse(text: str) -> tuple[list[Token], list[dict], list[Variable]]:
    """Cached tokenize + collect. Returns fresh copies safe to mutate."""
    tokens, issues, _esc, variables = _parse_cached(normalize_newlines(text))
    return list(tokens), [dict(i) for i in issues], [copy(v) for v in variables]


def render_segments(text: str, values: dict | None = None, tokens: list[Token] | None = None,
                    variables: list[Variable] | None = None) -> list[dict]:
    """Rendered output as segments: kind = text | value | default | missing.

    The preview uses this to highlight exactly which parts came from variables
    (escaped literals such as \\{{x}} are plain text and never highlighted)."""
    text = normalize_newlines(text)
    if tokens is None or variables is None:
        tokens, _, variables = parse(text)
    vmap = {v.name: v for v in variables}
    segs: list[dict] = []

    def lit(chunk: str) -> None:
        if chunk:
            chunk = chunk.replace("\\{{", "{{")
            if segs and segs[-1]["k"] == "text":
                segs[-1]["t"] += chunk
            else:
                segs.append({"k": "text", "t": chunk})

    pos = 0
    vals = values or {}
    for t in sorted(tokens, key=lambda t: t.start):
        lit(text[pos:t.start])
        v = vmap[t.name]
        raw = vals.get(v.name)
        if raw is not None and str(raw).strip() != "":
            segs.append({"k": "value", "t": normalize_newlines(str(raw)), "v": v.name})
        elif v.default is not None:
            segs.append({"k": "default", "t": v.default, "v": v.name})
        else:
            segs.append({"k": "missing", "t": t.raw, "v": v.name})
        pos = t.end
    lit(text[pos:])
    return segs


def render(text: str, values: dict | None = None, tokens: list[Token] | None = None,
           variables: list[Variable] | None = None) -> str:
    return "".join(s["t"] for s in render_segments(text, values, tokens, variables))


_CJK = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")
_WORD = re.compile(r"[A-Za-z0-9_]+(?:['’-][A-Za-z0-9_]+)*")
_WS = re.compile(r"\s")


def estimate_tokens(s: str) -> int:
    """Rough LLM token estimate: CJK ≈ 0.8 token/char, other text ≈ 1 token per 3.6 chars."""
    if not s:
        return 0
    cjk = len(_CJK.findall(s))
    rest = len(_WS.sub("", s)) - cjk
    return max(1, round(cjk * 0.8 + max(0, rest) / 3.6))


def text_stats(s: str) -> dict:
    s = s or ""
    return {
        "chars": len(s),
        "chars_no_space": len(_WS.sub("", s)),
        "cjk": len(_CJK.findall(s)),
        "words": len(_WORD.findall(s)),
        "lines": (s.count("\n") + 1) if s else 0,
        "tokens": estimate_tokens(s),
    }


def sample_values(variables: list[Variable] | list[dict]) -> dict:
    """Plausible test values for every variable (debug panel → 一键试填)."""
    out = {}
    for v in variables:
        d = v if isinstance(v, dict) else v.to_dict()
        name, ctl, default, opts = d["name"], d["control"], d.get("default"), d.get("options") or []
        if ctl == "select" or ctl == "radio":
            out[name] = default if default not in (None, "") and default in opts else (opts[0] if opts else "")
        elif ctl == "multiselect":
            if default not in (None, ""):
                out[name] = default
            else:
                out[name] = opts[0] if opts else ""
        elif ctl == "number":
            out[name] = default if default not in (None, "") and _is_number(default) else "100"
        elif ctl == "multiline":
            out[name] = f"示例{name}第一行\n示例{name}第二行"
        else:
            out[name] = default if default not in (None, "") else f"示例{name}"
    return out


def analyze(text: str, values: dict | None = None) -> dict:
    """Full analysis used by the debug panel."""
    values = {str(k): ("" if v is None else str(v)) for k, v in (values or {}).items()}
    text = normalize_newlines(text)
    tokens, issues, variables = parse(text)
    segments = render_segments(text, values, tokens, variables)
    rendered = "".join(s["t"] for s in segments)
    missing = []
    for v in variables:
        val = _value_for(v, values)
        if v.required and val is None:
            missing.append(v.name)
            issues.append(_issue("warn", "required_empty", f"必填变量「{v.name}」未填写", v.lines[0], 0, v.name))
        raw = values.get(v.name)
        if raw not in (None, "") and str(raw).strip():
            if v.control == "number" and not _is_number(str(raw)):
                issues.append(_issue("warn", "number_value", f"「{v.name}」应为数字，当前为「{raw}」", v.lines[0], 0, v.name))
            if v.control == "select" and v.options and str(raw) not in v.options:
                issues.append(_issue("info", "select_value", f"「{v.name}」的值「{raw}」不在选项中", v.lines[0], 0, v.name))
            if v.control == "radio" and v.options and str(raw) not in v.options:
                issues.append(_issue("info", "radio_value", f"「{v.name}」的值「{raw}」不在单选选项中", v.lines[0], 0, v.name))
            if v.control == "multiselect" and v.options:
                bad = [x for x in _split_multi_default(str(raw)) if x not in v.options]
                if bad:
                    issues.append(_issue("info", "multiselect_value",
                                         f"「{v.name}」含无效选项：{'、'.join(bad)}", v.lines[0], 0, v.name))
    names = {v.name for v in variables}
    unused = [k for k in values.keys() if k not in names and str(values.get(k) or "").strip()]
    if unused:
        issues.append(_issue("info", "unused_values", "表单/测试值中有正文未使用的变量：" + "、".join(unused[:12])
                             + ("…" if len(unused) > 12 else "")))
    # vars declared in body never filled (no value and no default) — beyond required_empty
    unfilled = []
    for v in variables:
        raw = values.get(v.name)
        has_val = raw is not None and str(raw).strip() != ""
        if not has_val and v.default is None and not v.required:
            # optional without default and empty — soft info
            unfilled.append(v.name)
        elif not has_val and v.default is None and v.required:
            pass  # already required_empty
        elif not has_val and v.default is not None:
            pass  # will use default
    if unfilled:
        issues.append(_issue("info", "unfilled_optional",
                             "可选变量未填写（无默认）：" + "、".join(unfilled[:12])))
    if not text.strip():
        issues.append(_issue("info", "empty_body", "提示词正文为空"))
    # long body / high token estimate
    st = text_stats(text)
    if st["chars"] >= 12000 or st["tokens"] >= 4000:
        issues.append(_issue("warn", "high_tokens",
                             f"正文偏长（{st['chars']} 字符 · 约 {st['tokens']} tokens），可能影响模型效果与费用"))
    elif st["chars"] >= 6000 or st["tokens"] >= 2000:
        issues.append(_issue("info", "long_body",
                             f"正文较长（{st['chars']} 字符 · 约 {st['tokens']} tokens）"))
    # missing output-format hint
    fmt_keys = ("输出", "JSON", "json", "格式", "Format", "format", "返回", "结构", "schema", "Schema")
    if text.strip() and not any(k in text for k in fmt_keys):
        issues.append(_issue("info", "missing_output_format",
                             "未检测到输出格式提示（如「输出」「JSON」「格式」），建议补充期望结构"))
    # conflicting markers soft check: both 【】 style and {{}} heavily mixed with leftover single braces already covered
    if "{{" in text and "}}" in text:
        # orphan {{ without }} already in tokenize; check for 【变量】 style leftovers
        import re as _re
        if _re.search(r"【[^】]{1,20}】", text) and _re.search(r"\{\{", text):
            issues.append(_issue("info", "mixed_markers",
                                 "同时出现「【】」与「{{}}」标记，确认是否故意混用"))
    # duplicate variable names already warned via dup_control; surface as lint-friendly summary
    seen_names = {}
    for v in variables:
        seen_names[v.name] = seen_names.get(v.name, 0) + 1  # count is on Variable
    # Variable.count > 1 is OK (same var multi-use); dup_control covers conflicting defs

    order = {"error": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda x: (order.get(x["level"], 3), x["line"] or 1_000_000, x["col"]))
    counts = {k: sum(1 for x in issues if x["level"] == k) for k in ("error", "warn", "info")}
    return {
        "variables": [v.to_dict() for v in variables],
        "issues": issues,
        "issue_counts": counts,
        "rendered": rendered,
        "segments": segments,
        "missing": missing,
        "stats": {"template": text_stats(text), "rendered": text_stats(rendered)},
        "ok": counts["error"] == 0 and not missing,
    }


def variables_of(text: str) -> list[dict]:
    _, _, variables = parse(text)
    return [v.to_dict() for v in variables]


def preview_line(text: str, limit: int = 60) -> str:
    """First meaningful line (body text preferred over headings), Markdown stripped, for list previews."""
    def clean(ln: str) -> str:
        s = re.sub(r"^(#{1,6}\s+|>\s*|[-*+]\s+|\d+\.\s+)", "", ln.strip())
        s = re.sub(r"[*_`]", "", s)
        s = re.sub(r"(?<!\\)\{\{\s*([^}:|：]+?)\s*(?:[:：|][^}]*)?\}\}", lambda m: "‹" + m.group(1).strip() + "›", s)
        return s[:limit] + ("…" if len(s) > limit else "")
    lines, fence = [], False
    for ln in (text or "").split("\n"):
        s = ln.strip()
        if s.startswith("```") or s.startswith("~~~"):
            fence = not fence
            continue
        if fence or not s or s.startswith("<!--"):
            continue
        lines.append(s)
    for s in lines:
        if not s.startswith("#"):
            return clean(s)
    return clean(lines[0]) if lines else ""

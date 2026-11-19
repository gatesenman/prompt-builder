"""LLM provider presets + OpenAI-compatible / Anthropic / Gemini HTTP clients (stdlib only)."""
from __future__ import annotations
import json, ssl, urllib.error, urllib.request
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# Built-in presets — users pick one, then fill API key / optional base URL override.
PROVIDER_PRESETS: list[dict[str, Any]] = [
    {"id": "openai", "name": "OpenAI", "region": "international", "kind": "openai",
     "base_url": "https://api.openai.com/v1", "models": ["gpt-4o", "gpt-4o-mini", "o4-mini"]},
    {"id": "anthropic", "name": "Anthropic Claude", "region": "international", "kind": "anthropic",
     "base_url": "https://api.anthropic.com", "models": ["claude-sonnet-4-20250514", "claude-3-5-haiku-latest"]},
    {"id": "gemini", "name": "Google Gemini", "region": "international", "kind": "gemini",
     "base_url": "https://generativelanguage.googleapis.com/v1beta", "models": ["gemini-2.0-flash", "gemini-2.5-pro"]},
    {"id": "dashscope", "name": "通义 / DashScope", "region": "domestic", "kind": "openai",
     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "models": ["qwen-plus", "qwen-max", "qwen-turbo"]},
    {"id": "zhipu", "name": "智谱 GLM", "region": "domestic", "kind": "openai",
     "base_url": "https://open.bigmodel.cn/api/paas/v4", "models": ["glm-4-plus", "glm-4-flash"]},
    {"id": "deepseek", "name": "DeepSeek", "region": "domestic", "kind": "openai",
     "base_url": "https://api.deepseek.com/v1", "models": ["deepseek-chat", "deepseek-reasoner"]},
    {"id": "moonshot", "name": "月之暗面 Kimi", "region": "domestic", "kind": "openai",
     "base_url": "https://api.moonshot.cn/v1", "models": ["moonshot-v1-128k", "moonshot-v1-32k", "kimi-latest"]},
    {"id": "baichuan", "name": "百川", "region": "domestic", "kind": "openai",
     "base_url": "https://api.baichuan-ai.com/v1", "models": ["Baichuan4", "Baichuan3-Turbo"]},
    {"id": "doubao", "name": "豆包 / 火山方舟", "region": "domestic", "kind": "openai",
     "base_url": "https://ark.cn-beijing.volces.com/api/v3", "models": ["doubao-pro-32k", "doubao-lite-32k"]},
    {"id": "openrouter", "name": "OpenRouter", "region": "aggregator", "kind": "openai",
     "base_url": "https://openrouter.ai/api/v1", "models": ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4", "google/gemini-2.0-flash"]},
    {"id": "siliconflow", "name": "SiliconFlow 硅基流动", "region": "aggregator", "kind": "openai",
     "base_url": "https://api.siliconflow.cn/v1", "models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"]},
    {"id": "custom", "name": "自定义 (OpenAI 兼容 / 一API / New API)", "region": "aggregator", "kind": "openai",
     "base_url": "", "models": ["gpt-4o-mini"]},
]


def list_presets() -> list[dict]:
    return [{k: v for k, v in p.items()} for p in PROVIDER_PRESETS]


def _http_json(method: str, url: str, headers: dict, body: dict | None, timeout: float) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return {"ok": True, "status": resp.status, "data": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:800]
        try:
            detail = json.loads(err_body)
        except Exception:
            detail = err_body
        return {"ok": False, "status": e.code, "error": f"HTTP {e.code}", "detail": detail}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e) or e.__class__.__name__}


def chat_completion(
    *,
    kind: str,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    temperature: float = 0.4,
    max_tokens: int = 4096,
    timeout: float = 90.0,
) -> dict:
    """Return {ok, text, error, latency_ms, raw_usage}."""
    import time
    t0 = time.monotonic()
    kind = (kind or "openai").lower()
    base = (base_url or "").rstrip("/")
    key = (api_key or "").strip()
    if not key:
        return {"ok": False, "text": "", "error": "未配置 API Key", "latency_ms": 0}
    if not model:
        return {"ok": False, "text": "", "error": "未指定模型", "latency_ms": 0}

    if kind == "anthropic":
        # convert messages: system separate
        system = ""
        conv = []
        for m in messages:
            if m.get("role") == "system":
                system = (system + "\n" + m.get("content", "")).strip()
            else:
                conv.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        url = f"{base}/v1/messages" if not base.endswith("/v1") else f"{base}/messages"
        if "/v1/messages" not in url and not url.endswith("/messages"):
            url = f"{base}/v1/messages"
        body = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "messages": conv}
        if system:
            body["system"] = system
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        r = _http_json("POST", url, headers, body, timeout)
        ms = int((time.monotonic() - t0) * 1000)
        if not r.get("ok"):
            return {"ok": False, "text": "", "error": r.get("error") or "请求失败", "detail": r.get("detail"), "latency_ms": ms}
        data = r.get("data") or {}
        parts = data.get("content") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        return {"ok": True, "text": text, "error": "", "latency_ms": ms, "usage": data.get("usage")}

    if kind == "gemini":
        # Gemini generateContent
        sys_txt = ""
        contents = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                sys_txt = (sys_txt + "\n" + m.get("content", "")).strip()
                continue
            grole = "user" if role != "assistant" else "model"
            contents.append({"role": grole, "parts": [{"text": m.get("content", "")}]})
        url = f"{base}/models/{model}:generateContent?key={urllib.request.quote(key)}"
        # if base already has key style — prefer header-less query
        body: dict[str, Any] = {"contents": contents, "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
        if sys_txt:
            body["systemInstruction"] = {"parts": [{"text": sys_txt}]}
        r = _http_json("POST", url, {}, body, timeout)
        ms = int((time.monotonic() - t0) * 1000)
        if not r.get("ok"):
            return {"ok": False, "text": "", "error": r.get("error") or "请求失败", "detail": r.get("detail"), "latency_ms": ms}
        data = r.get("data") or {}
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            text = json.dumps(data, ensure_ascii=False)[:2000]
        return {"ok": True, "text": text, "error": "", "latency_ms": ms, "usage": data.get("usageMetadata")}

    # openai-compatible
    if not base:
        return {"ok": False, "text": "", "error": "未配置 Base URL", "latency_ms": 0}
    url = f"{base}/chat/completions"
    body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    headers = {"Authorization": f"Bearer {key}"}
    r = _http_json("POST", url, headers, body, timeout)
    ms = int((time.monotonic() - t0) * 1000)
    if not r.get("ok"):
        return {"ok": False, "text": "", "error": r.get("error") or "请求失败", "detail": r.get("detail"), "latency_ms": ms}
    data = r.get("data") or {}
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except Exception:
        text = ""
    return {"ok": True, "text": text, "error": "", "latency_ms": ms, "usage": data.get("usage")}


def parallel_chat(
    targets: list[dict],
    messages: list[dict],
    *,
    temperature: float = 0.4,
    max_tokens: int = 4096,
    timeout: float = 90.0,
    max_workers: int = 6,
) -> list[dict]:
    """targets: [{id, label, kind, base_url, api_key, model}, ...]
    Returns list aligned with targets: {id, label, model, ok, text, error, latency_ms}
    """
    results: dict[str, dict] = {}

    def run_one(t: dict) -> tuple[str, dict]:
        tid = str(t.get("id") or t.get("model") or id(t))
        r = chat_completion(
            kind=t.get("kind") or "openai",
            base_url=t.get("base_url") or "",
            api_key=t.get("api_key") or "",
            model=t.get("model") or "",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        return tid, {
            "id": tid,
            "label": t.get("label") or t.get("model") or tid,
            "model": t.get("model") or "",
            "provider": t.get("provider") or "",
            **r,
        }

    if not targets:
        return []
    workers = max(1, min(max_workers, len(targets)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_one, t): t for t in targets}
        for fut in as_completed(futs):
            try:
                tid, row = fut.result()
                results[tid] = row
            except Exception as e:
                t = futs[fut]
                tid = str(t.get("id") or t.get("model"))
                results[tid] = {
                    "id": tid, "label": t.get("label") or tid, "model": t.get("model") or "",
                    "provider": t.get("provider") or "", "ok": False, "text": "", "error": str(e), "latency_ms": 0,
                }
    # preserve input order
    ordered = []
    for t in targets:
        tid = str(t.get("id") or t.get("model") or id(t))
        ordered.append(results.get(tid) or {
            "id": tid, "label": t.get("label") or tid, "ok": False, "text": "", "error": "无结果", "latency_ms": 0,
        })
    return ordered


def preset_models(preset_id: str = "") -> list[str]:
    for p in PROVIDER_PRESETS:
        if p.get("id") == preset_id:
            return list(p.get("models") or [])
    return []


def list_models(
    *,
    kind: str = "openai",
    base_url: str = "",
    api_key: str = "",
    preset: str = "",
    timeout: float = 25.0,
) -> dict:
    """Fetch model ids from the provider. Returns {ok, models, source, error}.

    OpenAI-compatible: GET {base}/models
    Anthropic / Gemini: best-effort HTTP, else preset fallback.
    """
    kind = (kind or "openai").lower()
    base = (base_url or "").rstrip("/")
    key = (api_key or "").strip()
    fallback = preset_models(preset)

    def _ok(models: list[str], source: str) -> dict:
        seen, out = set(), []
        for m in models:
            mid = str(m or "").strip()
            if not mid or mid in seen:
                continue
            seen.add(mid)
            out.append(mid)
            if len(out) >= 120:
                break
        if not out and fallback:
            return {"ok": True, "models": fallback, "source": "preset", "error": ""}
        return {"ok": True, "models": out, "source": source, "error": ""}

    if not key:
        if fallback:
            return {"ok": True, "models": fallback, "source": "preset", "error": "未提供 API Key，已用预设模型"}
        return {"ok": False, "models": [], "source": "", "error": "未配置 API Key"}

    if kind == "anthropic":
        # Anthropic has no public models list for all keys; try then fall back.
        url = f"{base}/v1/models" if base and not base.endswith("/v1") else f"{base}/models" if base else ""
        if url:
            r = _http_json("GET", url, {"x-api-key": key, "anthropic-version": "2023-06-01"}, None, timeout)
            if r.get("ok"):
                data = r.get("data") or {}
                rows = data.get("data") or data.get("models") or []
                ids = []
                for row in rows:
                    if isinstance(row, dict):
                        ids.append(row.get("id") or row.get("name") or "")
                    elif isinstance(row, str):
                        ids.append(row)
                if ids:
                    return _ok(ids, "api")
        return _ok(fallback, "preset")

    if kind == "gemini":
        url = f"{base}/models?key={urllib.request.quote(key)}" if base else ""
        if url:
            r = _http_json("GET", url, {}, None, timeout)
            if r.get("ok"):
                data = r.get("data") or {}
                rows = data.get("models") or []
                ids = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    name = str(row.get("name") or "")
                    # "models/gemini-2.0-flash" -> "gemini-2.0-flash"
                    if "/" in name:
                        name = name.split("/")[-1]
                    # prefer generateContent-capable
                    methods = row.get("supportedGenerationMethods") or []
                    if methods and "generateContent" not in methods:
                        continue
                    if name:
                        ids.append(name)
                if ids:
                    return _ok(ids, "api")
        return _ok(fallback, "preset")

    # openai-compatible
    if not base:
        if fallback:
            return {"ok": True, "models": fallback, "source": "preset", "error": "未配置 Base URL，已用预设模型"}
        return {"ok": False, "models": [], "source": "", "error": "未配置 Base URL"}
    url = f"{base}/models"
    r = _http_json("GET", url, {"Authorization": f"Bearer {key}"}, None, timeout)
    if not r.get("ok"):
        if fallback:
            return {"ok": True, "models": fallback, "source": "preset",
                    "error": (r.get("error") or "拉取失败") + "；已用预设模型"}
        return {"ok": False, "models": [], "source": "", "error": r.get("error") or "拉取失败",
                "detail": r.get("detail")}
    data = r.get("data") or {}
    rows = data.get("data") or data.get("models") or []
    ids = []
    for row in rows:
        if isinstance(row, dict):
            ids.append(row.get("id") or row.get("name") or "")
        elif isinstance(row, str):
            ids.append(row)
    if not ids and fallback:
        return _ok(fallback, "preset")
    return _ok(ids, "api")

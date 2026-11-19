/* Tiny, safe Markdown → HTML renderer for the preview tab (escapes everything first). */
(function () {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  function inline(s) {
    const codes = [];
    s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
    s = esc(s)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_]+)__/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
      .replace(/~~([^~]+)~~/g, "<del>$1</del>")
      .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${esc(codes[+i])}</code>`);
  }
  function render(src) {
    const lines = String(src || "").replace(/\r\n?/g, "\n").split("\n");
    const out = []; let i = 0;
    while (i < lines.length) {
      const l = lines[i];
      const fence = l.match(/^\s*(```|~~~)/);
      if (fence) {
        const buf = []; i++;
        while (i < lines.length && !lines[i].trim().startsWith(fence[1])) buf.push(lines[i++]);
        i++; out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`); continue;
      }
      let m;
      if ((m = l.match(/^(#{1,6})\s+(.*)$/))) { out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`); i++; continue; }
      if (/^\s*([-*_])\s*\1\s*\1[\s\1]*$/.test(l)) { out.push("<hr>"); i++; continue; }
      if (/^\s*>/.test(l)) {
        const buf = []; while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
        out.push(`<blockquote>${render(buf.join("\n"))}</blockquote>`); continue;
      }
      if (/^\s*([-*+]|\d+[.)])\s+/.test(l)) {
        const ordered = /^\s*\d/.test(l); const buf = [];
        while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) buf.push(lines[i++].replace(/^\s*([-*+]|\d+[.)])\s+/, ""));
        const tag = ordered ? "ol" : "ul";
        out.push(`<${tag}>${buf.map((b) => `<li>${inline(b)}</li>`).join("")}</${tag}>`); continue;
      }
      if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        const row = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        const head = row(l); i += 2; const body = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) body.push(row(lines[i++]));
        out.push(`<table><tr>${head.map((h) => `<th>${inline(h)}</th>`).join("")}</tr>${body.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</table>`);
        continue;
      }
      if (!l.trim()) { i++; continue; }
      const buf = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*```|\s*~~~|\s*>|\s*([-*+]|\d+[.)])\s+)/.test(lines[i])) buf.push(inline(lines[i++]));
      out.push(`<p>${buf.join("<br>")}</p>`);
    }
    return out.join("\n");
  }
  window.MiniMD = { render };
})();

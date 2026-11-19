"""Parser / renderer tests.  Run:  python -m unittest discover -s src/tests -v"""
import os, sys, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # src/

from prompt_syntax import (analyze, estimate_tokens, normalize_newlines, render, render_segments,
                           sample_values, tokenize, variables_of)


def codes(r, level=None):
    return [i["code"] for i in r["issues"] if level is None or i["level"] == level]


class Syntax(unittest.TestCase):
    def test_all_documented_forms(self):
        body = ("{{名}} {{可选|默认}} {{空|}} {{正文:多行}} {{字数:数字|300}} "
                "{{语气:A/B/C|A}} {{单:单行}} {{全角：多行}}")
        vs = {v["name"]: v for v in variables_of(body)}
        self.assertTrue(vs["名"]["required"])
        self.assertEqual(vs["可选"]["default"], "默认")
        self.assertEqual(vs["空"]["default"], "")
        self.assertFalse(vs["空"]["required"])
        self.assertEqual(vs["正文"]["control"], "multiline")
        self.assertEqual((vs["字数"]["control"], vs["字数"]["default"]), ("number", "300"))
        self.assertEqual((vs["语气"]["control"], vs["语气"]["options"]), ("select", ["A", "B", "C"]))
        self.assertEqual(vs["单"]["control"], "text")
        self.assertEqual(vs["全角"]["control"], "multiline")
        out = render(body, {"名": "X", "正文": "P", "单": "S", "全角": "Q"})
        self.assertEqual(out, "X 默认  P 300 A S Q")

    def test_escape_literal_no_stray_warning(self):
        r = analyze(r"写法：\{{变量}} 与 {{真}}", {"真": "1"})
        self.assertEqual(r["rendered"], "写法：{{变量}} 与 1")
        self.assertNotIn("stray_close", codes(r))
        self.assertEqual([v["name"] for v in r["variables"]], ["真"])

    def test_escape_without_close(self):
        r = analyze(r"\{{ 只是括号", {})
        self.assertEqual(r["rendered"], "{{ 只是括号")
        self.assertEqual(codes(r, "error"), [])

    def test_triple_braces(self):
        r = analyze("{{{名}}}", {"名": "v"})
        self.assertEqual(r["rendered"], "{v}")
        self.assertEqual(codes(r, "error"), [])

    def test_nested_braces(self):
        r = analyze("{{外 {{内}} }}", {"内": "x"})
        self.assertIn("unclosed", codes(r, "error"))
        self.assertEqual([v["name"] for v in r["variables"]], ["内"])
        self.assertIn("x", r["rendered"])

    def test_unclosed_and_multiline_variable(self):
        r = analyze("a {{名\n}} b", {})
        self.assertIn("unclosed", codes(r, "error"))
        self.assertEqual(r["variables"], [])
        r = analyze("a {{名", {})
        self.assertEqual(r["issues"][0]["line"], 1)
        self.assertIn("unclosed", codes(r, "error"))

    def test_line_numbers(self):
        r = analyze("第一行\n第二行 {{坏\n第三行 {{好}}", {})
        bad = [i for i in r["issues"] if i["code"] == "unclosed"][0]
        self.assertEqual((bad["line"], bad["col"]), (2, 5))
        self.assertEqual(r["variables"][0]["lines"], [3])

    def test_empty_and_bad_names(self):
        self.assertIn("empty_name", codes(analyze("{{}}", {})))
        self.assertIn("empty_name", codes(analyze("{{|默认}}", {})))
        self.assertIn("empty_name", codes(analyze("{{：多行}}", {})))

    def test_json_braces_are_hint_only(self):
        r = analyze('输出 JSON：{"a": {"b": 1}}', {})
        self.assertEqual(codes(r, "error") + codes(r, "warn"), [])

    def test_stray_close_warns(self):
        self.assertIn("stray_close", codes(analyze("多余 }} 括号", {}), "warn"))

    def test_code_fence_downgrades(self):
        r = analyze("```\n{{坏\n```\n正文", {})
        self.assertEqual(codes(r, "error"), [])
        self.assertIn("unclosed", codes(r, "info"))

    def test_duplicate_names_conflicting_defaults(self):
        r = analyze("{{a|1}} {{a|2}} {{a}}", {})
        self.assertIn("dup_default", codes(r, "warn"))
        self.assertIn("partial_default", codes(r, "info"))
        self.assertEqual(r["rendered"], "1 1 1")
        self.assertEqual(len(r["variables"]), 1)
        self.assertEqual(r["variables"][0]["count"], 3)

    def test_duplicate_names_conflicting_controls(self):
        r = analyze("{{a:多行}} {{a:数字}}", {})
        self.assertIn("dup_control", codes(r, "warn"))
        self.assertEqual(r["variables"][0]["control"], "multiline")

    def test_select_and_number_checks(self):
        self.assertIn("select_default", codes(analyze("{{s:A/B|C}}", {})))
        self.assertIn("select_options", codes(analyze("{{s:A/}}", {})))
        self.assertIn("select_dup", codes(analyze("{{s:A/A}}", {})))
        self.assertIn("number_default", codes(analyze("{{n:数字|abc}}", {})))
        self.assertIn("number_value", codes(analyze("{{n:数字}}", {"n": "十"})))
        self.assertNotIn("number_value", codes(analyze("{{n:数字}}", {"n": "1,000.5"})))
        self.assertIn("unknown_control", codes(analyze("{{x:颜色}}", {})))

    def test_crlf(self):
        body = "第一行\r\n{{名|默认}}\r\n第三行 {{坏\r\n"
        r = analyze(body, {"名": "值\r\n第二行"})
        self.assertNotIn("\r", r["rendered"])
        self.assertTrue(r["rendered"].startswith("第一行\n值\n第二行\n第三行"))
        bad = [i for i in r["issues"] if i["code"] == "unclosed"][0]
        self.assertEqual(bad["line"], 3)
        self.assertEqual(normalize_newlines("a\rb\r\nc"), "a\nb\nc")

    def test_required_missing_keeps_placeholder(self):
        r = analyze("你好 {{名}}", {})
        self.assertEqual(r["missing"], ["名"])
        self.assertEqual(r["rendered"], "你好 {{名}}")
        self.assertFalse(r["ok"])

    def test_whitespace_value_uses_default(self):
        self.assertEqual(render("{{a|默认}}", {"a": "   "}), "默认")

    def test_unused_values(self):
        self.assertIn("unused_values", codes(analyze("{{a}}", {"a": "1", "旧": "x"})))

    def test_segments(self):
        segs = render_segments(r"A{{x}}B{{y|d}}C{{z}}\{{lit}}", {"x": "1"})
        kinds = [(s["k"], s["t"]) for s in segs]
        self.assertEqual(kinds, [("text", "A"), ("value", "1"), ("text", "B"), ("default", "d"),
                                 ("text", "C"), ("missing", "{{z}}"), ("text", "{{lit}}")])

    def test_stats_and_tokens(self):
        r = analyze("你好世界 hello world", {})
        st = r["stats"]["template"]
        self.assertEqual(st["cjk"], 4)
        self.assertGreater(st["tokens"], 0)
        self.assertEqual(estimate_tokens(""), 0)

    def test_sample_values(self):
        vals = sample_values(variables_of("{{a}} {{n:数字}} {{s:X/Y}} {{m:多行}} {{d|默认}}"))
        self.assertEqual(vals["n"], "100")
        self.assertEqual(vals["s"], "X")
        self.assertIn("\n", vals["m"])
        self.assertEqual(vals["d"], "默认")
        r = analyze("{{a}} {{n:数字}} {{s:X/Y}} {{m:多行}}", vals)
        self.assertTrue(r["ok"], r["issues"])

    def test_very_long_template_is_linear(self):
        unit = "段落 {{名|默认}} 文本 \\{{字面}} {\"j\":{\"k\":1}}\n"
        big = unit * 25000  # ~1 MB
        t = time.perf_counter()
        r = analyze(big, {"名": "x"})
        dt = time.perf_counter() - t
        self.assertLess(dt, 15.0)  # generous: build machines can be heavily loaded
        self.assertEqual(len(r["variables"]), 1)
        self.assertIn("long_template", codes(r, "info"))

    def test_many_escapes_not_quadratic(self):
        # Scaling test (load-independent): 4x the input must cost well under 16x the time.
        def best(n):
            src = "\\{{" * n + "{{a}}"
            ts = []
            for _ in range(3):
                t = time.perf_counter()
                toks, _, _ = tokenize(src)
                ts.append(time.perf_counter() - t)
            self.assertEqual([x.name for x in toks], ["a"])
            return min(ts)
        small, large = best(6000), best(24000)
        self.assertLess(large / max(small, 1e-4), 10.0, (small, large))

    def test_cache_returns_independent_copies(self):
        a = analyze("{{x}}", {})
        a["variables"][0]["name"] = "changed"
        a["issues"].clear()
        b = analyze("{{x}}", {})
        self.assertEqual(b["variables"][0]["name"], "x")
        self.assertTrue(b["issues"])


if __name__ == "__main__":
    unittest.main()


class DoubleSlash(unittest.TestCase):
    """The "//" trigger state machine (keyhook.SlashDetector)."""
    S, DIV, COLON, A = 0xBF, 0x6F, 0xBA, 0x41

    def run_seq(self, seq, window_ms=500):
        from keyhook import SlashDetector
        d = SlashDetector(window_ms)
        hits = []
        for ev in seq:
            vk, down, t = ev[0], ev[1], ev[2]
            kw = ev[3] if len(ev) > 3 else {}
            if d.feed(vk, down, t, **kw):
                hits.append(t)
        return hits

    def tap(self, vk, t, **kw):
        return [(vk, True, t, kw), (vk, False, t + 0.02, kw)]

    def test_two_slashes_trigger(self):
        self.assertEqual(self.run_seq(self.tap(self.S, 0) + self.tap(self.S, 0.2)), [0.2])

    def test_numpad_divide_counts(self):
        self.assertEqual(self.run_seq(self.tap(self.DIV, 0) + self.tap(self.S, 0.1)), [0.1])
        self.assertEqual(self.run_seq(self.tap(self.DIV, 0) + self.tap(self.DIV, 0.1, shift=True)), [0.1])

    def test_single_slash_never(self):
        self.assertEqual(self.run_seq(self.tap(self.S, 0)), [])

    def test_too_slow(self):
        self.assertEqual(self.run_seq(self.tap(self.S, 0) + self.tap(self.S, 0.7)), [])
        # the late slash starts a new pair
        self.assertEqual(self.run_seq(self.tap(self.S, 0) + self.tap(self.S, 0.7) + self.tap(self.S, 0.9)), [0.9])

    def test_other_key_between(self):
        self.assertEqual(self.run_seq(self.tap(self.S, 0) + self.tap(self.A, 0.1) + self.tap(self.S, 0.2)), [])

    def test_modifier_between_is_ignored(self):
        self.assertEqual(self.run_seq(self.tap(self.S, 0) + self.tap(0xA0, 0.1) + self.tap(self.S, 0.2)), [0.2])

    def test_after_colon_url(self):
        seq = self.tap(self.COLON, 0, shift=True) + self.tap(self.S, 0.1) + self.tap(self.S, 0.2)
        self.assertEqual(self.run_seq(seq), [])
        seq += self.tap(self.S, 0.3)  # file:///
        self.assertEqual(self.run_seq(seq), [])
        # semicolon (no shift) does not block
        self.assertEqual(self.run_seq(self.tap(self.COLON, 0) + self.tap(self.S, 0.1) + self.tap(self.S, 0.2)), [0.2])

    def test_url_run_ends_after_pause_or_window_change(self):
        url = self.tap(self.COLON, 0, shift=True) + self.tap(self.S, 0.1) + self.tap(self.S, 0.2)
        # later "//" with nothing typed in between still triggers after a pause
        self.assertEqual(self.run_seq(url + self.tap(self.S, 1.5) + self.tap(self.S, 1.6)), [1.6])
        # ... or right away in another window
        self.assertEqual(self.run_seq(url + self.tap(self.S, 0.3, fg=7) + self.tap(self.S, 0.4, fg=7)), [0.4])

    def test_auto_repeat_and_held(self):
        seq = [(self.S, True, 0), (self.S, True, 0.03), (self.S, True, 0.06), (self.S, False, 0.1)]
        self.assertEqual(self.run_seq(seq), [])

    def test_question_mark_and_shortcuts(self):
        self.assertEqual(self.run_seq(self.tap(self.S, 0, shift=True) + self.tap(self.S, 0.1, shift=True)), [])
        self.assertEqual(self.run_seq(self.tap(self.S, 0, ctrl=True) + self.tap(self.S, 0.1, ctrl=True)), [])
        self.assertEqual(self.run_seq(self.tap(self.S, 0) + self.tap(self.S, 0.1, shift=True)), [])

    def test_different_window(self):
        seq = self.tap(self.S, 0, fg=1) + self.tap(self.S, 0.1, fg=2)
        self.assertEqual(self.run_seq(seq), [])

    def test_three_slashes_trigger_once(self):
        seq = self.tap(self.S, 0) + self.tap(self.S, 0.1) + self.tap(self.S, 0.2)
        self.assertEqual(self.run_seq(seq), [0.1])
        seq += self.tap(self.S, 0.3)
        self.assertEqual(self.run_seq(seq), [0.1, 0.3])

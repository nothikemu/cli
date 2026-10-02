import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import convert  # noqa: E402
from convert import ConversionError, Options, convert_text, get_profile  # noqa: E402


def run(text, ext, **kw):
    return convert_text(text, get_profile(ext), Options(**kw), source_name="notes.txt", source_suffix=".txt")


class DecodeTests(unittest.TestCase):
    def test_utf8(self):
        self.assertEqual(convert.decode_bytes("héllo".encode("utf-8")), ("héllo", "utf-8", False))

    def test_utf8_bom(self):
        text, enc, bom = convert.decode_bytes(b"\xef\xbb\xbfhi")
        self.assertEqual((text, enc, bom), ("hi", "utf-8-sig", True))

    def test_utf16_bom(self):
        text, enc, bom = convert.decode_bytes("hi ✓".encode("utf-16"))
        self.assertEqual((text, enc, bom), ("hi ✓", "utf-16", True))

    def test_cp1252_fallback(self):
        text, enc, _ = convert.decode_bytes(b"caf\xe9 \x93q\x94")
        self.assertEqual((text, enc), ("café “q”", "cp1252"))

    def test_latin1_last_resort(self):
        _, enc, _ = convert.decode_bytes(b"\x81\x8d")
        self.assertEqual(enc, "latin-1")

    def test_binary_rejected(self):
        with self.assertRaises(ConversionError):
            convert.decode_bytes(b"ab\x00cd")

    def test_explicit_encoding_error(self):
        with self.assertRaisesRegex(ConversionError, "offset 1"):
            convert.decode_bytes(b"a\xff", "utf-8")

    def test_unknown_encoding(self):
        with self.assertRaisesRegex(ConversionError, "unknown encoding"):
            convert.canonical_encoding("klingon-8")


class EolTests(unittest.TestCase):
    def test_detect(self):
        self.assertEqual(convert.detect_eol("a\r\nb\r\n"), "crlf")
        self.assertEqual(convert.detect_eol("a\nb"), "lf")
        self.assertEqual(convert.detect_eol("a\rb"), "cr")
        self.assertEqual(convert.detect_eol("a\r\nb\n"), "mixed")
        self.assertEqual(convert.detect_eol("ab"), "none")

    def test_bat_gets_crlf(self):
        self.assertEqual(run("echo a\necho b\n", "bat").data, b"echo a\r\necho b\r\n")

    def test_py_gets_lf(self):
        self.assertEqual(run("x=1\r\ny=2\r\n", "py", shebang="none").data, b"x=1\ny=2\n")

    def test_keep(self):
        self.assertEqual(
            convert_text("a\r\nb\r\n", get_profile("sh"), Options(eol="keep", shebang="none"), source_eol="crlf").data,
            b"a\r\nb\r\n",
        )

    def test_explicit_override(self):
        self.assertEqual(run("a\nb", "py", eol="cr", shebang="none").data, b"a\rb\r")


class TransformTests(unittest.TestCase):
    def test_shebang_added_and_executable(self):
        c = run("print(1)\n", "py")
        self.assertTrue(c.text.startswith("#!/usr/bin/env python3\n"))
        self.assertTrue(c.executable)

    def test_existing_shebang_kept(self):
        c = run("#!/usr/bin/python2\nprint 1\n", "py")
        self.assertEqual(c.text.count("#!"), 1)

    def test_custom_and_disabled_shebang(self):
        self.assertTrue(run("x\n", "sh", shebang="/bin/dash").text.startswith("#!/bin/dash\n"))
        c = run("x\n", "sh", shebang="none")
        self.assertEqual(c.text, "x\n")
        self.assertFalse(c.executable)

    def test_no_chmod(self):
        self.assertFalse(run("x\n", "sh", chmod=False).executable)

    def test_sanitize(self):
        c = run("echo “hi” — it’s ok​…\n", "sh", sanitize=True, shebang="none")
        self.assertEqual(c.text, "echo \"hi\" -- it's ok...\n")
        self.assertEqual(c.warnings, [])

    def test_smart_quote_warning(self):
        self.assertTrue(any("--sanitize" in w for w in run("print(“hi”)", "py").warnings))
        self.assertEqual(run("“hi”", "txt").warnings, [])

    def test_whitespace_options(self):
        c = run("\n\n    a  \n    \tb\n\n\n", "txt", strip_trailing=True, dedent=True, trim=True, expand_tabs=4)
        self.assertEqual(c.text, "a\n    b\n")

    def test_final_newline(self):
        self.assertEqual(run("a", "txt").text, "a\n")
        self.assertEqual(run("a", "txt", final_newline=False).text, "a")

    def test_header_after_shebang(self):
        c = run("#!/bin/sh\necho\n", "sh", header="from {source}")
        self.assertEqual(c.text, "#!/bin/sh\n# from notes.txt\necho\n")

    def test_header_bat_and_json(self):
        self.assertTrue(run("echo\n", "bat", header="hi").text.startswith(":: hi\n"))
        c = run("{}", "json", header="hi")
        self.assertEqual(c.text, "{}\n")
        self.assertTrue(c.warnings)

    def test_bom_auto_for_powershell(self):
        self.assertTrue(run("Write-Host 'é'\n", "ps1").data.startswith(b"\xef\xbb\xbf"))
        self.assertFalse(run("Write-Host 'e'\n", "ps1").data.startswith(b"\xef\xbb\xbf"))

    def test_bom_never_before_shebang(self):
        c = run("echo é\n", "sh", bom="yes")
        self.assertFalse(c.bom)
        self.assertTrue(any("shebang" in w for w in c.warnings))

    def test_encode_error_reports_position(self):
        with self.assertRaisesRegex(ConversionError, r"line 2, column 3"):
            run("ok\nab☃\n", "txt", encoding="ascii")

    def test_encode_replace(self):
        self.assertEqual(run("a☃\n", "txt", encoding="ascii", errors="replace").data, b"a?\n")

    def test_cp1252_output(self):
        self.assertEqual(run("café\n", "bat", encoding="cp1252").data, b"caf\xe9\r\n")

    def test_batch_non_ascii_warning(self):
        self.assertTrue(any("chcp" in w for w in run("echo é\n", "bat").warnings))

    def test_unknown_extension(self):
        p = get_profile("xyz")
        self.assertFalse(p.known)
        self.assertEqual(convert_text("a\r\n", p, Options()).data, b"a\n")

    def test_aliases(self):
        self.assertEqual(convert.normalize_ext(".Python"), "py")
        self.assertEqual(convert.normalize_ext("bat"), "bat")
        with self.assertRaises(ConversionError):
            convert.normalize_ext("../x")


class ExtractTests(unittest.TestCase):
    DOC = (
        "# Title\n\nIntro\n\n```python\nprint(1)\n```\n\ntext\n\n~~~bash\necho hi\n~~~\n\n"
        "```\nplain\n```\n\n````py\nprint(2)\n```\nstill code\n````\n"
    )

    def test_blocks(self):
        blocks = convert.find_code_blocks(self.DOC)
        self.assertEqual([b.lang for b in blocks], ["python", "bash", "", "py"])
        self.assertEqual(blocks[3].code, "print(2)\n```\nstill code")

    def test_extract_by_target_language(self):
        c = run(self.DOC, "py", extract=True, shebang="none")
        self.assertEqual(c.text, "print(1)\n\nprint(2)\n```\nstill code\n")

    def test_extract_lang_override(self):
        c = run(self.DOC, "txt", extract=True, langs=["bash"])
        self.assertEqual(c.text, "echo hi\n")

    def test_extract_falls_back_to_unlabelled(self):
        self.assertEqual(run(self.DOC, "rb", extract=True, shebang="none").text, "plain\n")

    def test_extract_all(self):
        self.assertIn("echo hi", run(self.DOC, "txt", extract=True, langs=["all"]).text)

    def test_extract_errors(self):
        with self.assertRaisesRegex(ConversionError, "no fenced code"):
            run("just prose", "py", extract=True)
        with self.assertRaisesRegex(ConversionError, "found python"):
            run("```python\nx\n```", "rb", extract=True)


class MarkdownTests(unittest.TestCase):
    def md(self, text):
        return convert.MarkdownRenderer().render(text)

    def test_inline(self):
        out = convert.render_inline("**b** *i* _j_ ~~s~~ `a<b>` [l](http://x.y?a=1&b=2) <https://z.io> & <tag>")
        self.assertIn("<strong>b</strong>", out)
        self.assertIn("<em>i</em>", out)
        self.assertIn("<em>j</em>", out)
        self.assertIn("<del>s</del>", out)
        self.assertIn("<code>a&lt;b&gt;</code>", out)
        self.assertIn('<a href="http://x.y?a=1&amp;b=2">l</a>', out)
        self.assertIn('<a href="https://z.io">https://z.io</a>', out)
        self.assertIn("&amp; &lt;tag&gt;", out)

    def test_snake_case_not_italic(self):
        self.assertEqual(convert.render_inline("my_var_name"), "my_var_name")

    def test_escapes_and_bare_urls(self):
        self.assertEqual(convert.render_inline(r"\*not em\*"), "*not em*")
        self.assertIn('<a href="https://a.b/c">https://a.b/c</a>.', convert.render_inline("see https://a.b/c."))

    def test_blocks(self):
        out = self.md("# H1\n\npara\nline\n\n- a\n- b\n\n3. x\n4. y\n\n> q\n\n***\n\n    code\n")
        self.assertIn('<h1 id="h1">H1</h1>', out)
        self.assertIn("<p>para\nline</p>", out)
        self.assertIn("<ul>\n<li>a</li>\n<li>b</li>\n</ul>", out)
        self.assertIn('<ol start="3">', out)
        self.assertIn("<blockquote>\n<p>q</p>\n</blockquote>", out)
        self.assertIn("<hr>", out)
        self.assertIn("<pre><code>code</code></pre>", out)

    def test_html_is_escaped(self):
        self.assertNotIn("<script>", self.md("<script>alert(1)</script>"))

    def test_duplicate_heading_ids(self):
        out = self.md("## Intro\n\n## Intro\n")
        self.assertIn('id="intro"', out)
        self.assertIn('id="intro-1"', out)

    def test_html_page(self):
        c = convert_text("# Hello *World*\n\ntext\n", get_profile("html"), Options(toc=True), source_name="a.md", source_suffix=".md")
        self.assertIn("<title>Hello World</title>", c.text)
        self.assertIn('<nav class="toc">', c.text)
        self.assertIn('<meta charset="utf-8">', c.text)

    def test_plain_text_html(self):
        c = convert_text("a < b\n", get_profile("html"), Options(title="T"), source_name="a.txt", source_suffix=".txt")
        self.assertIn('<pre class="plain">a &lt; b\n</pre>', c.text)
        self.assertIn("<title>T</title>", c.text)


class CheckTests(unittest.TestCase):
    def test_python(self):
        self.assertTrue(convert.syntax_check("x = 1\n", "python")[0])
        ok, msg = convert.syntax_check("def (:\n", "python")
        self.assertFalse(ok)
        self.assertIn("line 1", msg)

    def test_json_ini_xml(self):
        self.assertTrue(convert.syntax_check('{"a": 1}', "json")[0])
        self.assertFalse(convert.syntax_check("{a: 1}", "json")[0])
        self.assertTrue(convert.syntax_check("[s]\na=1\n", "ini")[0])
        self.assertFalse(convert.syntax_check("a=1\n", "ini")[0])
        self.assertTrue(convert.syntax_check("<a><b/></a>", "xml")[0])
        self.assertFalse(convert.syntax_check("<a>", "xml")[0])

    @unittest.skipUnless(shutil.which("sh") and os.name != "nt", "needs a POSIX sh")
    def test_shell(self):
        self.assertTrue(convert.syntax_check("echo hi\n", "sh")[0])
        self.assertFalse(convert.syntax_check("if then fi\n", "sh")[0])

    def test_strict_raises(self):
        with self.assertRaisesRegex(ConversionError, "syntax check failed"):
            run("def (:\n", "py", strict=True)

    def test_check_warns(self):
        self.assertTrue(any("syntax check failed" in w for w in run("def (:\n", "py", check=True).warnings))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.cwd)

    def cli(self, *args, stdin=b""):
        raw_out = io.BytesIO()
        out = io.TextIOWrapper(raw_out, encoding="utf-8", newline="")
        err = io.StringIO()
        fake_stdin = mock.Mock()
        fake_stdin.buffer = io.BytesIO(stdin)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(sys, "stdin", fake_stdin):
            try:
                code = convert.main(list(args))
            except SystemExit as exc:
                code = exc.code
        out.flush()
        return code, raw_out.getvalue().decode("utf-8"), err.getvalue()

    def write(self, name, data):
        p = self.tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
        return p

    def test_readme_examples(self):
        self.write("notes.txt", "print('hi')\r\n")
        self.assertEqual(self.cli("notes.txt", "py")[0], 0)
        self.assertEqual((self.tmp / "notes.py").read_bytes(), b"#!/usr/bin/env python3\nprint('hi')\n")
        if os.name != "nt":
            self.assertTrue(os.stat(self.tmp / "notes.py").st_mode & stat.S_IXUSR)
        self.assertEqual(self.cli("notes.txt", "bat", "-e", "cp1252")[0], 0)
        self.assertEqual((self.tmp / "notes.bat").read_bytes(), b"print('hi')\r\n")
        self.assertTrue((self.tmp / "notes.txt").exists())

    def test_no_fix_keeps_line_endings(self):
        self.write("a.txt", "x\r\ny\r\n")
        self.cli("a.txt", "sh", "--no-fix", "--no-shebang")
        self.assertEqual((self.tmp / "a.sh").read_bytes(), b"x\r\ny\r\n")

    def test_conflicts(self):
        self.write("a.txt", "one\n")
        self.write("a.sh", "old\n")
        code, out, _ = self.cli("a.txt", "sh")
        self.assertEqual(code, 1)
        self.assertIn("already exists", out)
        self.assertEqual((self.tmp / "a.sh").read_text(), "old\n")

        self.assertEqual(self.cli("a.txt", "sh", "--on-conflict", "skip")[0], 0)
        self.assertEqual((self.tmp / "a.sh").read_text(), "old\n")

        self.assertEqual(self.cli("a.txt", "sh", "--on-conflict", "rename", "--no-shebang")[0], 0)
        self.assertEqual((self.tmp / "a-1.sh").read_text(), "one\n")

        self.assertEqual(self.cli("a.txt", "sh", "-f", "--backup", "--no-shebang")[0], 0)
        self.assertEqual((self.tmp / "a.sh").read_text(), "one\n")
        self.assertEqual((self.tmp / "a.sh.bak").read_text(), "old\n")

    def test_unchanged_is_not_a_conflict(self):
        self.write("a.txt", "x\n")
        self.cli("a.txt", "md")
        code, out, _ = self.cli("a.txt", "md")
        self.assertEqual(code, 0)
        self.assertIn("unchanged", out)

    def test_dry_run_and_diff(self):
        self.write("a.txt", "echo “hi”\n")
        code, out, _ = self.cli("a.txt", "sh", "-n", "--diff", "-s")
        self.assertEqual(code, 0)
        self.assertIn('+echo "hi"', out)
        self.assertIn("+#!/bin/sh", out)
        self.assertFalse((self.tmp / "a.sh").exists())

    def test_stdin_to_stdout(self):
        code, out, err = self.cli("-", "json", "-o", "-", "--check", stdin=b'{"a": 1}')
        self.assertEqual(code, 0)
        self.assertEqual(out, '{"a": 1}\n')
        self.assertIn("valid JSON", err)

    def test_explicit_output_and_to_flag(self):
        self.write("a.txt", "x\n")
        self.assertEqual(self.cli("--to", "md", "a.txt", "-o", "out/readme.md")[0], 0)
        self.assertEqual((self.tmp / "out" / "readme.md").read_text(), "x\n")

    def test_directory_recursive_output_dir(self):
        self.write("docs/a.md", "# A\n")
        self.write("docs/sub/b.txt", "b\n")
        self.write("docs/sub/skip.log", "nope\n")
        self.write("docs/.hidden/c.md", "c\n")
        code, out, _ = self.cli("docs", "html", "-r", "-d", "site", "--json")
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report["summary"]["converted"], 2)
        self.assertTrue((self.tmp / "site" / "a.html").exists())
        self.assertTrue((self.tmp / "site" / "sub" / "b.html").exists())
        self.assertFalse((self.tmp / "site" / ".hidden").exists())

    def test_non_recursive_and_exclude(self):
        self.write("d/a.txt", "a\n")
        self.write("d/b.txt", "b\n")
        self.write("d/s/c.txt", "c\n")
        self.cli("d", "md", "--exclude", "b.*")
        self.assertTrue((self.tmp / "d" / "a.md").exists())
        self.assertFalse((self.tmp / "d" / "b.md").exists())
        self.assertFalse((self.tmp / "d" / "s" / "c.md").exists())

    def test_glob_pattern(self):
        self.write("a.txt", "a\n")
        self.write("b.txt", "b\n")
        code, out, _ = self.cli("*.txt", "md", "--suffix", "_v2")
        self.assertEqual(code, 0)
        self.assertTrue((self.tmp / "a_v2.md").exists())
        self.assertIn("2 converted", out)

    def test_remove_source(self):
        self.write("a.txt", "a\n")
        self.cli("a.txt", "md", "--remove-source")
        self.assertFalse((self.tmp / "a.txt").exists())
        self.assertTrue((self.tmp / "a.md").exists())

    def test_strict_does_not_write(self):
        self.write("a.txt", "def (:\n")
        code, out, _ = self.cli("a.txt", "py", "--strict")
        self.assertEqual(code, 1)
        self.assertFalse((self.tmp / "a.py").exists())

    def test_usage_errors(self):
        self.write("a.txt", "a\n")
        self.assertEqual(self.cli("a.txt")[0], 2)
        self.assertEqual(self.cli("missing.txt", "py")[0], 2)
        self.assertEqual(self.cli("a.txt", "py", "-e", "nope")[0], 2)
        self.write("b.txt", "b\n")
        self.assertEqual(self.cli("a.txt", "b.txt", "py", "-o", "x.py")[0], 2)

    def test_options_after_positionals_and_between(self):
        self.write("a.txt", "a\n")
        self.assertEqual(self.cli("a.txt", "--no-shebang", "sh", "-q")[0], 0)
        self.assertEqual((self.tmp / "a.sh").read_text(), "a\n")

    def test_list_formats(self):
        code, out, _ = self.cli("--list-formats")
        self.assertEqual(code, 0)
        self.assertIn("ps1", out)

    def test_encoding_failure_is_reported(self):
        self.write("a.txt", "snow ☃\n")
        code, out, _ = self.cli("a.txt", "bat", "-e", "cp1252")
        self.assertEqual(code, 1)
        self.assertIn("U+2603", out)


if __name__ == "__main__":
    unittest.main()

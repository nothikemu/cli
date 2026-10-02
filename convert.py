#!/usr/bin/env python3
"""convert.py - turn plain text / Markdown documents into ready-to-run files.

Unlike a plain rename, the converter takes care of everything that makes a
pasted-together script fail on another machine: line endings, character
encodings, byte-order marks, shebang lines, the executable bit, "smart"
typographic punctuation, code buried inside Markdown fences, and more.

Only the Python standard library is used, so the file can be copied and run
anywhere Python 3.9+ is available:

    python convert.py notes.txt py
    python convert.py README.md html --toc
    python convert.py draft.md sh --extract --sanitize --check

Run ``python convert.py --help`` for the full option list.
"""

from __future__ import annotations

import argparse
import codecs
import configparser
import datetime as _dt
import difflib
import fnmatch
import glob
import html
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

__version__ = "2.0.0"
PROG = "convert.py"

EOLS = {"lf": "\n", "crlf": "\r\n", "cr": "\r"}
EOL_LABELS = {"lf": "LF", "crlf": "CRLF", "cr": "CR", "none": "none", "mixed": "mixed"}

DEFAULT_INCLUDE = ("*.txt", "*.text", "*.md", "*.markdown", "*.mdown", "*.mkd")
MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd", ".mkdn"}


class ConversionError(Exception):
    """A problem that prevents a single file from being converted."""


# --------------------------------------------------------------------------
# Format profiles
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Profile:
    ext: str
    description: str
    eol: str = "lf"
    shebang: Optional[str] = None
    languages: Tuple[str, ...] = ()
    comment: Optional[str] = None  # template with "{}" for the text
    checker: Optional[str] = None
    code: bool = True  # is this an executable / machine-read format?
    bom: bool = False  # write a UTF-8 BOM when the text is not pure ASCII
    known: bool = True


_P = Profile
PROFILES = {
    p.ext: p
    for p in [
        # Unix scripts
        _P("py", "Python script", "lf", "#!/usr/bin/env python3", ("python", "py", "python3", "py3"), "# {}", "python"),
        _P("pyw", "Python script (Windows, no console)", "crlf", None, ("python", "py", "python3"), "# {}", "python"),
        _P("sh", "POSIX shell script", "lf", "#!/bin/sh", ("sh", "shell", "posix", "bash"), "# {}", "sh"),
        _P("bash", "Bash script", "lf", "#!/usr/bin/env bash", ("bash", "sh", "shell"), "# {}", "bash"),
        _P("zsh", "Zsh script", "lf", "#!/usr/bin/env zsh", ("zsh", "sh", "shell"), "# {}", "zsh"),
        _P("fish", "Fish shell script", "lf", "#!/usr/bin/env fish", ("fish",), "# {}", "fish"),
        _P("command", "macOS double-clickable shell script", "lf", "#!/bin/sh", ("sh", "bash", "shell"), "# {}", "sh"),
        _P("rb", "Ruby script", "lf", "#!/usr/bin/env ruby", ("ruby", "rb"), "# {}", "ruby"),
        _P("pl", "Perl script", "lf", "#!/usr/bin/env perl", ("perl", "pl"), "# {}", "perl"),
        _P("lua", "Lua script", "lf", None, ("lua",), "-- {}"),
        _P("r", "R script", "lf", None, ("r",), "# {}"),
        _P("php", "PHP script", "lf", None, ("php",), "// {}", "php"),
        _P("js", "JavaScript", "lf", None, ("javascript", "js", "node", "nodejs"), "// {}", "node"),
        _P("mjs", "JavaScript module", "lf", None, ("javascript", "js", "mjs", "node"), "// {}", "node"),
        _P("cjs", "CommonJS module", "lf", None, ("javascript", "js", "cjs", "node"), "// {}", "node"),
        _P("ts", "TypeScript", "lf", None, ("typescript", "ts"), "// {}"),
        _P("go", "Go source", "lf", None, ("go", "golang"), "// {}"),
        _P("rs", "Rust source", "lf", None, ("rust", "rs"), "// {}"),
        _P("c", "C source", "lf", None, ("c",), "/* {} */"),
        _P("cpp", "C++ source", "lf", None, ("cpp", "c++", "cxx"), "// {}"),
        _P("java", "Java source", "lf", None, ("java",), "// {}"),
        _P("sql", "SQL script", "lf", None, ("sql", "postgresql", "mysql", "sqlite"), "-- {}"),
        _P("awk", "AWK script", "lf", "#!/usr/bin/awk -f", ("awk",), "# {}"),
        _P("makefile", "Makefile", "lf", None, ("make", "makefile"), "# {}"),
        # Windows scripts
        _P("bat", "Windows batch file", "crlf", None, ("bat", "batch", "cmd", "dosbatch", "winbatch"), ":: {}"),
        _P("cmd", "Windows command script", "crlf", None, ("cmd", "bat", "batch", "dosbatch"), ":: {}"),
        _P("ps1", "PowerShell script", "crlf", None, ("powershell", "ps1", "pwsh", "ps"), "# {}", bom=True),
        _P("psm1", "PowerShell module", "crlf", None, ("powershell", "ps1", "pwsh"), "# {}", bom=True),
        _P("vbs", "VBScript", "crlf", None, ("vbscript", "vbs", "vb"), "' {}"),
        _P("reg", "Windows registry file", "crlf", None, ("reg", "registry"), "; {}"),
        _P("ahk", "AutoHotkey script", "crlf", None, ("autohotkey", "ahk"), "; {}", bom=True),
        # Data / config
        _P("json", "JSON document", "lf", None, ("json", "jsonc"), None, "json"),
        _P("yaml", "YAML document", "lf", None, ("yaml", "yml"), "# {}", "yaml"),
        _P("yml", "YAML document", "lf", None, ("yaml", "yml"), "# {}", "yaml"),
        _P("toml", "TOML document", "lf", None, ("toml",), "# {}", "toml"),
        _P("ini", "INI configuration", "lf", None, ("ini", "cfg", "conf"), "; {}", "ini"),
        _P("cfg", "Configuration file", "lf", None, ("ini", "cfg", "conf"), "# {}", "ini"),
        _P("env", "dotenv file", "lf", None, ("env", "dotenv", "sh"), "# {}"),
        _P("xml", "XML document", "lf", None, ("xml",), "<!-- {} -->", "xml"),
        _P("svg", "SVG image", "lf", None, ("svg", "xml"), "<!-- {} -->", "xml"),
        _P("csv", "CSV data", "crlf", None, ("csv",), None, code=False),
        _P("tsv", "TSV data", "lf", None, ("tsv",), None, code=False),
        # Web / documents
        _P("html", "HTML page (Markdown is rendered)", "lf", None, ("html",), "<!-- {} -->", code=False),
        _P("htm", "HTML page (Markdown is rendered)", "lf", None, ("html", "htm"), "<!-- {} -->", code=False),
        _P("css", "CSS stylesheet", "lf", None, ("css",), "/* {} */"),
        _P("md", "Markdown document", "lf", None, ("markdown", "md"), "<!-- {} -->", code=False),
        _P("txt", "Plain text", "lf", None, ("text", "txt", "plain"), None, code=False),
        _P("rtf", "Plain text (Windows line endings)", "crlf", None, ("text", "txt"), None, code=False),
    ]
}

# Short names people commonly type instead of the extension itself.
EXT_ALIASES = {
    "python": "py", "python3": "py", "shell": "sh", "batch": "bat", "powershell": "ps1",
    "pwsh": "ps1", "javascript": "js", "node": "js", "typescript": "ts", "ruby": "rb",
    "perl": "pl", "markdown": "md", "text": "txt", "web": "html", "vbscript": "vbs",
    "golang": "go", "rust": "rs",
}


def get_profile(ext: str) -> Profile:
    """Return the profile for ``ext`` (or a generic LF profile if unknown)."""
    key = ext.lower()
    if key in PROFILES:
        return PROFILES[key]
    return Profile(key, "Unknown format (generic LF profile)", known=False, code=False)


def normalize_ext(raw: str) -> str:
    ext = raw.strip().lstrip(".").strip()
    if not ext or any(c in ext for c in "/\\"):
        raise ConversionError(f"invalid target extension: {raw!r}")
    return EXT_ALIASES.get(ext.lower(), ext)


# --------------------------------------------------------------------------
# Options & results
# --------------------------------------------------------------------------


@dataclass
class Options:
    encoding: Optional[str] = None  # output encoding (None: profile default / utf-8)
    input_encoding: Optional[str] = None  # None: auto-detect
    errors: str = "strict"  # strict | replace | ignore | xmlcharrefreplace | backslashreplace
    eol: str = "auto"  # auto | lf | crlf | cr | keep
    bom: str = "auto"  # auto | yes | no
    shebang: str = "auto"  # auto | none | <custom line>
    chmod: bool = True
    extract: bool = False
    langs: List[str] = field(default_factory=list)
    sanitize: bool = False
    strip_trailing: bool = False
    expand_tabs: Optional[int] = None
    dedent: bool = False
    trim: bool = False
    final_newline: bool = True
    header: Optional[str] = None
    markdown: str = "auto"  # auto | yes | no  (only for HTML output)
    title: Optional[str] = None
    css: Optional[str] = None  # CSS text (not a path)
    toc: bool = False
    check: bool = False
    strict: bool = False


@dataclass
class Converted:
    text: str  # final text, still using "\n" line endings
    data: bytes  # encoded output
    encoding: str
    eol: str
    bom: bool
    executable: bool
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class Result:
    source: str
    dest: Optional[str] = None
    status: str = "pending"  # converted | unchanged | skipped | failed | dry-run
    encoding_in: Optional[str] = None
    encoding_out: Optional[str] = None
    eol_in: Optional[str] = None
    eol_out: Optional[str] = None
    lines: int = 0
    bytes: int = 0
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status not in ("failed",)


# --------------------------------------------------------------------------
# Decoding / encoding
# --------------------------------------------------------------------------

_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def canonical_encoding(name: str) -> str:
    try:
        return codecs.lookup(name).name
    except LookupError:
        raise ConversionError(f"unknown encoding: {name!r} (see python -m encodings)") from None


def _position(text: str, index: int) -> str:
    line = text.count("\n", 0, index) + 1
    col = index - (text.rfind("\n", 0, index) + 1) + 1
    return f"line {line}, column {col}"


def decode_bytes(data: bytes, encoding: Optional[str] = None) -> Tuple[str, str, bool]:
    """Decode ``data``. Returns ``(text, encoding_used, had_bom)``.

    With no explicit ``encoding`` the BOM is honoured, then UTF-8 is tried,
    then Windows-1252, then Latin-1 (which never fails).
    """
    if encoding:
        enc = canonical_encoding(encoding)
        try:
            text = data.decode(enc)
        except UnicodeDecodeError as exc:
            raise ConversionError(
                f"cannot decode byte 0x{data[exc.start]:02x} at offset {exc.start} as {enc}; "
                "try another --input-encoding"
            ) from None
        had_bom = text.startswith("\ufeff")
        return (text[1:] if had_bom else text), enc, had_bom

    for bom, enc in _BOMS:
        if data.startswith(bom):
            text = data.decode(enc)
            return text.lstrip("\ufeff") if enc != "utf-8-sig" else text, enc, True

    if b"\x00" in data:
        raise ConversionError("file looks binary (contains NUL bytes); pass --input-encoding to force it")

    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc), enc, False
        except UnicodeDecodeError:
            continue
    raise AssertionError("unreachable: latin-1 decodes everything")


def detect_eol(text: str) -> str:
    crlf = text.count("\r\n")
    cr = text.count("\r") - crlf
    lf = text.count("\n") - crlf
    counts = {"crlf": crlf, "lf": lf, "cr": cr}
    present = [k for k, v in counts.items() if v]
    if not present:
        return "none"
    if len(present) > 1:
        return "mixed"
    return present[0]


def dominant_eol(text: str) -> str:
    crlf = text.count("\r\n")
    cr = text.count("\r") - crlf
    lf = text.count("\n") - crlf
    best = max((crlf, "crlf"), (lf, "lf"), (cr, "cr"))
    return best[1] if best[0] else "lf"


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def encode_text(text: str, encoding: str, errors: str, bom: bool) -> bytes:
    enc = encoding
    if bom and enc == "utf-8":
        enc = "utf-8-sig"
    try:
        return text.encode(enc, errors)
    except UnicodeEncodeError as exc:
        bad = exc.object[exc.start:exc.end]
        chars = ", ".join(f"{c!r} (U+{ord(c):04X})" for c in bad[:5])
        raise ConversionError(
            f"{chars} at {_position(exc.object, exc.start)} cannot be encoded as {encoding}; "
            "use --sanitize, --errors replace, or a different --encoding"
        ) from None


# --------------------------------------------------------------------------
# Text transformations
# --------------------------------------------------------------------------

SMART_CHARS = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'", "\u00b4": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"', "\u00ab": '"', "\u00bb": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "--", "\u2015": "--", "\u2212": "-",
    "\u2026": "...", "\u2022": "*", "\u00d7": "x",
    "\u00a0": " ", "\u2002": " ", "\u2003": " ", "\u2004": " ", "\u2005": " ", "\u2006": " ",
    "\u2007": " ", "\u2008": " ", "\u2009": " ", "\u200a": " ", "\u202f": " ", "\u205f": " ", "\u3000": " ",
    "\u200b": "", "\u200c": "", "\u200d": "", "\u2060": "", "\ufeff": "", "\u00ad": "",
    "\u2028": "\n", "\u2029": "\n",
}
_SMART_RE = re.compile("[" + "".join(SMART_CHARS) + "]")


def sanitize_text(text: str) -> Tuple[str, int]:
    """Replace typographic punctuation and invisible characters with ASCII."""
    count = 0

    def repl(m: "re.Match[str]") -> str:
        nonlocal count
        count += 1
        return SMART_CHARS[m.group(0)]

    return _SMART_RE.sub(repl, text), count


def count_smart(text: str) -> int:
    return len(_SMART_RE.findall(text))


_FENCE_RE = re.compile(r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[^`\n]*)$")


@dataclass
class CodeBlock:
    lang: str
    code: str
    line: int


def find_code_blocks(text: str) -> List[CodeBlock]:
    """Return all fenced code blocks in Markdown ``text`` (``\\n`` line endings)."""
    blocks: List[CodeBlock] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = _FENCE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        fence = m.group("fence")
        indent = len(m.group("indent"))
        info = m.group("info").strip()
        lang = info.split()[0].strip("{}.").lower() if info else ""
        start = i + 1
        body: List[str] = []
        i += 1
        while i < len(lines):
            close = re.match(r"^ {0,3}(`{3,}|~{3,})[ \t]*$", lines[i])
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= len(fence):
                break
            line = lines[i]
            # remove up to ``indent`` leading spaces, as CommonMark does
            strip = len(line) - len(line.lstrip(" "))
            body.append(line[min(strip, indent):])
            i += 1
        blocks.append(CodeBlock(lang, "\n".join(body), start))
        i += 1
    return blocks


def extract_code(text: str, langs: Sequence[str]) -> Tuple[str, str]:
    """Pull code out of Markdown fences.

    ``langs`` lists acceptable fence languages; ``["*"]`` accepts all blocks.
    Unlabelled blocks are used when no labelled block matches.
    Returns ``(code, description)``.
    """
    blocks = find_code_blocks(text)
    if not blocks:
        raise ConversionError("--extract: no fenced code blocks (``` or ~~~) found")
    wanted = {lang.lower() for lang in langs}
    if "*" in wanted or "all" in wanted:
        chosen = blocks
    else:
        chosen = [b for b in blocks if b.lang in wanted]
        if not chosen:
            chosen = [b for b in blocks if not b.lang]
        if not chosen:
            found = sorted({b.lang for b in blocks})
            raise ConversionError(
                f"--extract: no code blocks tagged {', '.join(sorted(wanted)) or '(none)'}; "
                f"found {', '.join(found)} - use --lang to pick one, or --lang all"
            )
    code = "\n\n".join(b.code.strip("\n") for b in chosen)
    return code, f"extracted {len(chosen)} of {len(blocks)} code block(s)"


def _comment(profile: Profile, text: str) -> Optional[str]:
    if not profile.comment:
        return None
    return "\n".join(profile.comment.format(line) for line in text.split("\n"))


def render_header(template: str, source_name: str) -> str:
    now = _dt.datetime.now()
    try:
        return template.format(
            source=source_name, date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H:%M:%S"), version=__version__,
        )
    except (KeyError, IndexError, ValueError):
        return template


DEFAULT_HEADER = "Generated from {source} by convert.py {version} on {date}"


# --------------------------------------------------------------------------
# Markdown -> HTML (small, dependency-free CommonMark-ish subset)
# --------------------------------------------------------------------------

_ATX_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_HR_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_LIST_RE = re.compile(r"^( *)([-*+]|\d{1,9}[.)])(?:[ \t]+(.*)|$)")
_QUOTE_RE = re.compile(r"^ {0,3}> ?(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_TASK_RE = re.compile(r"^\[([ xX])\][ \t]+(.*)$", re.S)


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def slugify(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).lower()
    text = re.sub(r"[^\w\- ]", "", text).strip()
    return re.sub(r"[\s]+", "-", text) or "section"


def render_inline(text: str) -> str:
    stash: List[str] = []

    def keep(fragment: str) -> str:
        stash.append(fragment)
        return f"\x00{len(stash) - 1}\x00"

    def url(u: str) -> str:
        return html.escape(html.unescape(u), quote=True)

    # backslash escapes
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|~<>])", lambda m: keep(html.escape(m.group(1))), text)
    # code spans
    text = re.sub(r"(`+)(.+?)(?<!`)\1(?!`)", lambda m: keep(f"<code>{html.escape(m.group(2).strip())}</code>"), text, flags=re.S)
    # autolinks
    text = re.sub(r"<((?:https?|ftp|mailto):[^>\s]+)>", lambda m: keep(f'<a href="{url(m.group(1))}">{html.escape(m.group(1))}</a>'), text)
    text = html.escape(text, quote=False)

    def link(m: "re.Match[str]", image: bool) -> str:
        label, href, title = m.group(1), m.group(2), m.group(3)
        t = f' title="{html.escape(html.unescape(title))}"' if title else ""
        if image:
            return keep(f'<img src="{url(href)}" alt="{html.escape(html.unescape(label))}"{t}>')
        return f'<a href="{url(href)}"{t}>{label}</a>'

    text = re.sub(r'!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+"([^)]*?)")?\s*\)', lambda m: link(m, True), text)
    text = re.sub(r'\[([^\]]+)\]\(\s*<?([^)\s>]+)>?(?:\s+"([^)]*?)")?\s*\)', lambda m: link(m, False), text)
    text = re.sub(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", r"<strong>\2</strong>", text, flags=re.S)
    text = re.sub(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])", r"<em>\1</em>", text, flags=re.S)
    text = re.sub(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])", r"<em>\1</em>", text, flags=re.S)
    text = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<del>\1</del>", text, flags=re.S)
    text = re.sub(r"(?: {2,}|\\)\n", "<br>\n", text)
    # bare URLs
    text = re.sub(r'(?<!["=>\w])(https?://[^\s<]+[^\s<.,;:!?)\]\'"])', r'<a href="\1">\1</a>', text)

    while "\x00" in text:
        new = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)
        if new == text:
            break
        text = new
    return text


class MarkdownRenderer:
    """Renders the commonly used parts of Markdown to HTML."""

    def __init__(self) -> None:
        self.headings: List[Tuple[int, str, str]] = []  # (level, id, html)
        self._ids: dict = {}

    def _unique_id(self, base: str) -> str:
        n = self._ids.get(base, 0)
        self._ids[base] = n + 1
        return base if n == 0 else f"{base}-{n}"

    def heading(self, level: int, raw: str) -> str:
        inner = render_inline(raw.strip())
        hid = self._unique_id(slugify(inner))
        self.headings.append((level, hid, inner))
        return f'<h{level} id="{hid}">{inner}</h{level}>'

    def render(self, text: str) -> str:
        return "\n".join(self._blocks(text.split("\n")))

    def toc(self) -> str:
        if not self.headings:
            return ""
        top = min(level for level, _, _ in self.headings)
        items = []
        for level, hid, inner in self.headings:
            pad = "  " * (level - top)
            plain = re.sub(r"<[^>]+>", "", inner)
            items.append(f'{pad}<li class="toc-l{level - top + 1}"><a href="#{hid}">{plain}</a></li>')
        return '<nav class="toc">\n<ul>\n' + "\n".join(items) + "\n</ul>\n</nav>"

    def _is_block_start(self, line: str) -> bool:
        return bool(_ATX_RE.match(line) or _FENCE_RE.match(line) or _HR_RE.match(line) or _QUOTE_RE.match(line))

    def _blocks(self, lines: List[str]) -> Iterator[str]:
        para: List[str] = []
        i, n = 0, len(lines)

        def flush() -> Iterator[str]:
            if para:
                yield "<p>" + render_inline("\n".join(s.strip() for s in para)) + "</p>"
                para.clear()

        while i < n:
            line = lines[i]
            stripped = line.strip()

            fence = _FENCE_RE.match(line)
            if fence:
                yield from flush()
                info = fence.group("info").strip()
                lang = info.split()[0] if info else ""
                body: List[str] = []
                i += 1
                while i < n:
                    close = re.match(r"^ {0,3}(`{3,}|~{3,})[ \t]*$", lines[i])
                    if close and close.group(1)[0] == fence.group("fence")[0] and len(close.group(1)) >= len(fence.group("fence")):
                        break
                    body.append(lines[i])
                    i += 1
                cls = f' class="language-{html.escape(lang)}"' if lang else ""
                yield f"<pre><code{cls}>{html.escape(chr(10).join(body))}</code></pre>"
                i += 1
                continue

            if not stripped:
                yield from flush()
                i += 1
                continue

            if para and re.match(r"^ {0,3}(=+|-+)[ \t]*$", line):  # setext heading
                level = 1 if stripped[0] == "=" else 2
                content = "\n".join(s.strip() for s in para)
                para.clear()
                yield self.heading(level, content)
                i += 1
                continue

            atx = _ATX_RE.match(line)
            if atx:
                yield from flush()
                yield self.heading(len(atx.group(1)), atx.group(2) or "")
                i += 1
                continue

            if _HR_RE.match(line):
                yield from flush()
                yield "<hr>"
                i += 1
                continue

            if _QUOTE_RE.match(line):
                yield from flush()
                quoted: List[str] = []
                while i < n and lines[i].strip():
                    q = _QUOTE_RE.match(lines[i])
                    quoted.append(q.group(1) if q else lines[i])
                    i += 1
                yield "<blockquote>\n" + "\n".join(self._blocks(quoted)) + "\n</blockquote>"
                continue

            if "|" in line and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]) and "-" in lines[i + 1]:
                yield from flush()
                i = yield from self._table(lines, i)
                continue

            lm = _LIST_RE.match(line)
            if lm and (not para or lm.group(3)):
                yield from flush()
                i = yield from self._list(lines, i)
                continue

            if line.startswith("    ") and not para:  # indented code block
                code: List[str] = []
                while i < n and (lines[i].startswith("    ") or not lines[i].strip()):
                    code.append(lines[i][4:])
                    i += 1
                while code and not code[-1].strip():
                    code.pop()
                yield f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>"
                continue

            para.append(line)
            i += 1
        yield from flush()

    @staticmethod
    def _cells(row: str) -> List[str]:
        row = row.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|") and not row.endswith("\\|"):
            row = row[:-1]
        return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row)]

    def _table(self, lines: List[str], i: int):
        header = self._cells(lines[i])
        aligns = []
        for spec in self._cells(lines[i + 1]):
            left, right = spec.startswith(":"), spec.endswith(":")
            aligns.append("center" if left and right else "right" if right else "left" if left else None)
        i += 2
        rows = []
        while i < len(lines) and lines[i].strip() and "|" in lines[i]:
            rows.append(self._cells(lines[i]))
            i += 1

        def cell(tag: str, text: str, col: int) -> str:
            a = aligns[col] if col < len(aligns) else None
            style = f' style="text-align:{a}"' if a else ""
            return f"<{tag}{style}>{render_inline(text)}</{tag}>"

        out = ["<table>", "<thead>", "<tr>" + "".join(cell("th", c, k) for k, c in enumerate(header)) + "</tr>", "</thead>"]
        if rows:
            out.append("<tbody>")
            for r in rows:
                r = (r + [""] * len(header))[: len(header)]
                out.append("<tr>" + "".join(cell("td", c, k) for k, c in enumerate(r)) + "</tr>")
            out.append("</tbody>")
        out.append("</table>")
        yield "\n".join(out)
        return i

    def _list(self, lines: List[str], i: int):
        n = len(lines)
        first = _LIST_RE.match(lines[i])
        assert first
        base = len(first.group(1))
        ordered = first.group(2)[0].isdigit()
        start = int(first.group(2)[:-1]) if ordered else 1
        items: List[List[str]] = []
        loose = False
        content_col = 0
        while i < n:
            line = lines[i]
            m = _LIST_RE.match(line)
            if m and len(m.group(1)) == base and m.group(2)[0].isdigit() == ordered:
                items.append([m.group(3) or ""])
                content_col = len(line) - len((m.group(3) or "")) if m.group(3) else len(m.group(0)) + 1
                i += 1
                continue
            if m and len(m.group(1)) < base:
                break
            if not line.strip():
                j = i + 1
                while j < n and not lines[j].strip():
                    j += 1
                if j >= n:
                    break
                nxt = _LIST_RE.match(lines[j])
                if _indent_of(lines[j]) > base or (nxt and len(nxt.group(1)) == base and nxt.group(2)[0].isdigit() == ordered):
                    if not (nxt and len(nxt.group(1)) > base):
                        loose = True
                    items[-1].append("")
                    i += 1
                    continue
                break
            if _indent_of(line) > base:
                items[-1].append(line[min(_indent_of(line), content_col):])
                i += 1
                continue
            if m or self._is_block_start(line) or not items[-1][-1].strip():
                break
            items[-1].append(line.strip())  # lazy continuation
            i += 1

        tag = "ol" if ordered else "ul"
        attr = f' start="{start}"' if ordered and start != 1 else ""
        out = [f"<{tag}{attr}>"]
        for item in items:
            text = "\n".join(item).rstrip("\n")
            checkbox = ""
            task = _TASK_RE.match(text)
            if task:
                checked = " checked" if task.group(1) in "xX" else ""
                checkbox = f'<input type="checkbox" disabled{checked}> '
                text = task.group(2)
            inner = "\n".join(self._blocks(text.split("\n")))
            if not loose and inner.startswith("<p>"):
                # tight list: unwrap the paragraphs
                inner = re.sub(r"</?p>", "", inner)
            out.append(f"<li>{checkbox}{inner}</li>")
        out.append(f"</{tag}>")
        yield "\n".join(out)
        return i


DEFAULT_CSS = """\
:root { color-scheme: light dark; --fg:#1f2328; --bg:#ffffff; --muted:#59636e; --code-bg:#f6f8fa; --border:#d1d9e0; --link:#0969da; }
@media (prefers-color-scheme: dark) { :root { --fg:#e6edf3; --bg:#0d1117; --muted:#9198a1; --code-bg:#161b22; --border:#3d444d; --link:#4493f8; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
main { max-width: 52rem; margin: 0 auto; padding: 2rem 1rem 4rem; }
h1,h2,h3,h4,h5,h6 { line-height:1.25; margin:1.6em 0 .6em; }
h1,h2 { border-bottom:1px solid var(--border); padding-bottom:.3em; }
a { color:var(--link); }
code, pre { font-family: ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:.9em; }
code { background:var(--code-bg); padding:.15em .35em; border-radius:4px; }
pre { background:var(--code-bg); padding:1rem; border-radius:6px; overflow:auto; line-height:1.45; }
pre code { background:none; padding:0; }
pre.plain { white-space: pre-wrap; word-wrap: break-word; }
blockquote { margin:0; padding:0 1em; color:var(--muted); border-left:.25em solid var(--border); }
table { border-collapse:collapse; display:block; overflow:auto; }
th, td { border:1px solid var(--border); padding:.4em .8em; }
img { max-width:100%; }
hr { border:0; border-top:1px solid var(--border); margin:2em 0; }
nav.toc { border:1px solid var(--border); border-radius:6px; padding:.5rem 1rem; margin-bottom:2rem; }
nav.toc ul { list-style:none; padding-left:0; margin:.5em 0; }
nav.toc .toc-l2 { padding-left:1em; } nav.toc .toc-l3 { padding-left:2em; } nav.toc .toc-l4 { padding-left:3em; }
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="{charset}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="convert.py {version}">
<title>{title}</title>
<style>
{css}</style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
"""


def to_html(text: str, *, markdown: bool, title: Optional[str], css: Optional[str], toc: bool,
            charset: str, fallback_title: str, header_comment: Optional[str] = None) -> str:
    if markdown:
        r = MarkdownRenderer()
        body = r.render(text)
        if toc:
            body = r.toc() + "\n" + body if r.headings else body
        if not title and r.headings:
            title = re.sub(r"<[^>]+>", "", r.headings[0][2])
            title = html.unescape(title)
    else:
        body = f'<pre class="plain">{html.escape(text)}</pre>'
    page = HTML_TEMPLATE.format(
        charset=html.escape(charset), version=__version__,
        title=html.escape(title or fallback_title), css=css if css is not None else DEFAULT_CSS, body=body,
    )
    if header_comment:
        page = page.replace("<!DOCTYPE html>\n", "<!DOCTYPE html>\n" + header_comment + "\n", 1)
    return page


# --------------------------------------------------------------------------
# Syntax checks
# --------------------------------------------------------------------------


def _run_checker(cmd: List[str], text: str, suffix: str) -> Tuple[Optional[bool], str]:
    exe = shutil.which(cmd[0])
    if not exe:
        return None, f"{cmd[0]} not installed, check skipped"
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        proc = subprocess.run([exe, *cmd[1:], tmp], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"{cmd[0]} check could not run: {exc}"
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if proc.returncode == 0:
        return True, f"{cmd[0]} syntax OK"
    msg = (proc.stderr or proc.stdout).strip().replace(tmp, "<output>")
    return False, msg.splitlines()[0] if msg else f"{cmd[0]} reported an error"


def syntax_check(text: str, checker: Optional[str]) -> Tuple[Optional[bool], str]:
    """Return ``(ok, message)``; ``ok`` is ``None`` when the check was skipped."""
    if not checker:
        return None, "no syntax checker for this format"
    if checker == "python":
        try:
            compile(text, "<output>", "exec")
        except SyntaxError as exc:
            return False, f"line {exc.lineno}: {exc.msg}"
        return True, "python syntax OK"
    if checker == "json":
        try:
            json.loads(text)
        except ValueError as exc:
            return False, str(exc)
        return True, "valid JSON"
    if checker == "xml":
        import xml.etree.ElementTree as ET

        try:
            ET.fromstring(text)
        except ET.ParseError as exc:
            return False, str(exc)
        return True, "well-formed XML"
    if checker == "toml":
        try:
            import tomllib  # type: ignore[import-not-found]
        except ImportError:
            return None, "tomllib needs Python 3.11+, check skipped"
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            return False, str(exc)
        return True, "valid TOML"
    if checker == "ini":
        try:
            configparser.ConfigParser(interpolation=None, strict=False).read_string(text)
        except configparser.Error as exc:
            return False, str(exc).splitlines()[0]
        return True, "valid INI"
    if checker == "yaml":
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            return None, "PyYAML not installed, check skipped"
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return False, str(exc).splitlines()[0]
        return True, "valid YAML"
    commands = {
        "sh": (["sh", "-n"], ".sh"), "bash": (["bash", "-n"], ".sh"), "zsh": (["zsh", "-n"], ".zsh"),
        "fish": (["fish", "--no-execute"], ".fish"), "node": (["node", "--check"], ".js"),
        "ruby": (["ruby", "-c"], ".rb"), "perl": (["perl", "-c"], ".pl"), "php": (["php", "-l"], ".php"),
    }
    if checker in commands:
        cmd, suffix = commands[checker]
        return _run_checker(cmd, text, suffix)
    return None, f"unknown checker {checker!r}"


# --------------------------------------------------------------------------
# The conversion pipeline
# --------------------------------------------------------------------------


def convert_text(text: str, profile: Profile, opts: Options, *, source_name: str = "<stdin>",
                 source_suffix: str = "", source_eol: str = "lf") -> Converted:
    """Run the full pipeline on already-decoded ``text``."""
    notes: List[str] = []
    warnings: List[str] = []
    text = normalize_newlines(text)
    if text.startswith("\ufeff"):
        text = text[1:]

    if opts.extract:
        langs = opts.langs or list(profile.languages) or [profile.ext]
        text, desc = extract_code(text, langs)
        notes.append(desc)

    if opts.sanitize:
        text, n = sanitize_text(text)
        if n:
            notes.append(f"sanitized {n} character(s)")
    elif profile.code:
        n = count_smart(text)
        if n:
            warnings.append(
                f"{n} typographic/invisible character(s) such as \u201c \u201d \u2019 \u2014 or no-break spaces found; "
                "they break most interpreters - rerun with --sanitize"
            )

    if opts.dedent:
        text = textwrap.dedent(text)
    if opts.expand_tabs:
        text = text.expandtabs(opts.expand_tabs)
    if opts.strip_trailing:
        text = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
    if opts.trim:
        text = text.strip("\n")
        text = re.sub(r"^(?:[ \t]*\n)+", "", text)

    encoding = canonical_encoding(opts.encoding or "utf-8")
    is_html = profile.ext in ("html", "htm")

    header = render_header(opts.header, source_name) if opts.header else None
    if header and not is_html:
        commented = _comment(profile, header)
        if commented:
            if text.startswith("#!"):
                first, _, rest = text.partition("\n")
                text = first + "\n" + commented + "\n" + rest
            else:
                text = commented + "\n" + text
            notes.append("header")
        else:
            warnings.append(f".{profile.ext} files have no comment syntax; --header ignored")

    # shebang
    if not is_html and opts.shebang != "none":
        line = profile.shebang if opts.shebang == "auto" else opts.shebang
        if line and not line.startswith("#!"):
            line = "#!" + line
        if line and not text.startswith("#!"):
            text = line + "\n" + text
            notes.append("shebang")

    if is_html:
        use_md = opts.markdown == "yes" or (opts.markdown == "auto" and source_suffix.lower() in MARKDOWN_SUFFIXES)
        text = to_html(
            text, markdown=use_md, title=opts.title, css=opts.css, toc=opts.toc, charset=encoding,
            fallback_title=Path(source_name).stem or "Document",
            header_comment=_comment(profile, header) if header else None,
        )
        notes.append("markdown rendered" if use_md else "text wrapped in <pre>")

    if opts.final_newline and text and not text.endswith("\n"):
        text += "\n"

    # line endings
    if opts.eol == "auto":
        eol = profile.eol
    elif opts.eol == "keep":
        eol = source_eol if source_eol in EOLS else "lf"
    else:
        eol = opts.eol

    # byte-order mark
    non_ascii = any(ord(c) > 127 for c in text)
    if opts.bom == "yes":
        bom = True
    elif opts.bom == "no":
        bom = False
    else:
        bom = profile.bom and non_ascii and encoding == "utf-8"
    if bom and encoding not in ("utf-8", "utf-16", "utf-32"):
        if opts.bom == "yes":
            warnings.append(f"--bom has no effect for {encoding}")
        bom = False
    if bom and text.startswith("#!"):
        warnings.append("not writing a BOM: it would break the shebang line")
        bom = False
    if encoding.startswith(("utf-16", "utf-32")) and text.startswith("#!"):
        warnings.append(f"{encoding} output cannot be executed via its shebang line")

    if profile.ext in ("bat", "cmd") and encoding == "utf-8" and non_ascii:
        warnings.append(
            "non-ASCII text in a batch file: cmd.exe reads the legacy code page; "
            "use -e cp1252 (or cp437/cp850) or add 'chcp 65001 >nul' at the top"
        )

    if opts.check or opts.strict:
        ok, msg = syntax_check(text, profile.checker)
        if ok is False:
            if opts.strict:
                raise ConversionError(f"syntax check failed: {msg}")
            warnings.append(f"syntax check failed: {msg}")
        elif ok:
            notes.append(msg)
        elif profile.checker:
            notes.append(msg)

    final = text.replace("\n", EOLS[eol]) if eol != "lf" else text
    data = encode_text(final, encoding, opts.errors, bom)
    executable = opts.chmod and text.startswith("#!") and not is_html
    return Converted(text, data, encoding, eol, bom, executable, notes, warnings)


# --------------------------------------------------------------------------
# File handling
# --------------------------------------------------------------------------


def has_glob(s: str) -> bool:
    return any(c in s for c in "*?[")


def iter_inputs(raw_inputs: Sequence[str], recursive: bool, include: Sequence[str],
                exclude: Sequence[str]) -> Iterator[Tuple[Path, Optional[Path]]]:
    """Yield ``(file, root)`` pairs. ``root`` is the directory the file was found under."""
    seen = set()

    def excluded(p: Path) -> bool:
        return any(fnmatch.fnmatch(p.name, pat) or fnmatch.fnmatch(p.as_posix(), pat) for pat in exclude)

    def emit(p: Path, root: Optional[Path]):
        key = os.path.normcase(str(p.resolve()))
        if key not in seen and not excluded(p):
            seen.add(key)
            yield p, root

    for raw in raw_inputs:
        if raw == "-":
            yield Path("-"), None
            continue
        p = Path(raw).expanduser()
        if p.is_dir():
            walker = sorted(p.rglob("*")) if recursive else sorted(p.iterdir())
            for f in walker:
                if f.is_file() and any(fnmatch.fnmatch(f.name.lower(), pat.lower()) for pat in include):
                    if any(part.startswith(".") for part in f.relative_to(p).parts):
                        continue
                    yield from emit(f, p)
        elif p.exists():
            yield from emit(p, None)
        elif has_glob(raw):
            matches = sorted(glob.glob(os.path.expanduser(raw), recursive=True))
            for m in matches:
                if Path(m).is_file():
                    yield from emit(Path(m), None)
            if not matches:
                raise ConversionError(f"no files match {raw!r}")
        else:
            raise ConversionError(f"no such file or directory: {raw!r}")


def destination_for(src: Path, root: Optional[Path], ext: str, *, output: Optional[str],
                    output_dir: Optional[str], suffix: str) -> Path:
    stem = "stdin" if str(src) == "-" else src.stem
    name = f"{stem}{suffix}.{ext}"
    if output and output != "-":
        out = Path(output).expanduser()
        if out.is_dir() or output.endswith(("/", os.sep)):
            return out / name
        return out
    if output_dir:
        base = Path(output_dir).expanduser()
        if root is not None:
            return base / src.relative_to(root).parent / name
        return base / name
    if str(src) == "-":
        return Path.cwd() / name
    return src.with_name(name)


def unique_path(path: Path) -> Path:
    n = 1
    while True:
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def same_file(a: Path, b: Path) -> bool:
    try:
        return a.exists() and b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


def write_atomic(dest: Path, data: bytes, executable: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=str(dest.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        mode = stat.S_IMODE(dest.stat().st_mode) if dest.exists() else (0o666 & ~_umask())
        if executable and os.name != "nt":
            mode |= (mode & 0o444) >> 2 or 0o100
        os.chmod(tmp, mode)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _umask() -> int:
    if os.name == "nt":
        return 0
    mask = os.umask(0)
    os.umask(mask)
    return mask


@dataclass
class RunConfig:
    ext: str
    profile: Profile
    opts: Options
    output: Optional[str] = None
    output_dir: Optional[str] = None
    suffix: str = ""
    on_conflict: str = "error"  # error | overwrite | skip | rename
    backup: bool = False
    dry_run: bool = False
    diff: bool = False
    remove_source: bool = False
    max_size: int = 50 * 1024 * 1024


def make_diff(before: str, after: str, src_name: str, dest_name: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=src_name, tofile=dest_name,
    ))


def convert_one(src: Path, root: Optional[Path], cfg: RunConfig, stdin_data: Optional[bytes] = None,
                diff_out=None) -> Result:
    res = Result(source=str(src))
    try:
        if str(src) == "-":
            data = stdin_data if stdin_data is not None else sys.stdin.buffer.read()
            suffix = ""
            name = "stdin"
        else:
            size = src.stat().st_size
            if size > cfg.max_size:
                raise ConversionError(f"file is {size:,} bytes, larger than --max-size")
            data = src.read_bytes()
            suffix = src.suffix
            name = src.name

        text, enc_in, had_bom = decode_bytes(data, cfg.opts.input_encoding)
        res.encoding_in = enc_in + (" (BOM)" if had_bom and "sig" not in enc_in else "")
        res.eol_in = detect_eol(text)

        conv = convert_text(text, cfg.profile, cfg.opts, source_name=name, source_suffix=suffix,
                            source_eol=dominant_eol(text))
        res.notes, res.warnings = conv.notes, conv.warnings
        res.encoding_out = conv.encoding + (" + BOM" if conv.bom else "")
        res.eol_out = conv.eol
        res.lines = conv.text.count("\n") + (0 if conv.text.endswith("\n") or not conv.text else 1)
        res.bytes = len(conv.data)

        if cfg.output == "-":
            res.dest = "<stdout>"
            if cfg.dry_run:
                res.status = "dry-run"
            else:
                sys.stdout.flush()
                sys.stdout.buffer.write(conv.data)
                sys.stdout.buffer.flush()
                res.status = "converted"
            return res

        dest = destination_for(src, root, cfg.ext, output=cfg.output, output_dir=cfg.output_dir, suffix=cfg.suffix)

        if cfg.diff and diff_out is not None:
            d = make_diff(normalize_newlines(text), conv.text, name, dest.name)
            diff_out.write(d if d else f"(no content changes for {name})\n")

        overwriting = dest.exists()
        if overwriting:
            if dest.is_dir():
                raise ConversionError(f"destination is a directory: {dest}")
            existing = dest.read_bytes()
            if existing == conv.data:
                res.dest = str(dest)
                res.status = "unchanged"
                if conv.executable and not cfg.dry_run and os.name != "nt" and not os.access(dest, os.X_OK):
                    write_atomic(dest, conv.data, True)
                    res.notes.append("+x")
                return res
            if cfg.on_conflict == "skip":
                res.dest = str(dest)
                res.status = "skipped"
                res.notes.append("destination exists")
                return res
            if cfg.on_conflict == "rename":
                dest = unique_path(dest)
                overwriting = False
            elif cfg.on_conflict == "error":
                what = "the source file" if str(src) != "-" and same_file(src, dest) else "it"
                raise ConversionError(f"{dest} already exists; use --force to overwrite {what}, "
                                      "--on-conflict rename, or --on-conflict skip")
        res.dest = str(dest)

        if cfg.dry_run:
            res.status = "dry-run"
            return res

        if overwriting and cfg.backup:
            bak = dest.with_name(dest.name + ".bak")
            shutil.copy2(dest, bak)
            res.notes.append(f"backup: {bak.name}")

        write_atomic(dest, conv.data, conv.executable)
        if conv.executable and os.name != "nt":
            res.notes.append("+x")
        res.status = "converted"

        if cfg.remove_source and str(src) != "-" and not same_file(src, dest):
            src.unlink()
            res.notes.append("source removed")
    except ConversionError as exc:
        res.status, res.error = "failed", str(exc)
    except OSError as exc:
        res.status, res.error = "failed", f"{exc.strerror or exc}" + (f": {exc.filename}" if exc.filename else "")
    return res


# --------------------------------------------------------------------------
# Terminal output
# --------------------------------------------------------------------------


class Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        if enabled and os.name == "nt":
            os.system("")  # enables ANSI escape processing on Windows 10+

    def _w(self, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.enabled else s

    def green(self, s: str) -> str: return self._w("32", s)
    def red(self, s: str) -> str: return self._w("31", s)
    def yellow(self, s: str) -> str: return self._w("33", s)
    def cyan(self, s: str) -> str: return self._w("36", s)
    def dim(self, s: str) -> str: return self._w("2", s)
    def bold(self, s: str) -> str: return self._w("1", s)


def want_color(choice: str, stream) -> bool:
    if choice == "always":
        return True
    if choice == "never" or os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def _symbols(stream) -> dict:
    enc = (getattr(stream, "encoding", None) or "ascii").lower()
    try:
        "✓✗→•".encode(enc)
        return {"ok": "✓", "fail": "✗", "arrow": "→", "dot": "•", "skip": "-", "warn": "!"}
    except (UnicodeEncodeError, LookupError):
        return {"ok": "+", "fail": "x", "arrow": "->", "dot": "*", "skip": "-", "warn": "!"}


def short(path: Optional[str]) -> str:
    if not path:
        return "?"
    try:
        rel = os.path.relpath(path)
        return rel if not rel.startswith(".." + os.sep + "..") else path
    except ValueError:
        return path


def report_line(res: Result, st: Style, sym: dict, verbose: bool) -> List[str]:
    lines = []
    if res.status == "failed":
        lines.append(f"{st.red(sym['fail'])} {short(res.source)}: {st.red(res.error or 'failed')}")
        return lines
    icon = {
        "converted": st.green(sym["ok"]), "dry-run": st.cyan(sym["dot"]),
        "unchanged": st.dim(sym["ok"]), "skipped": st.yellow(sym["skip"]),
    }.get(res.status, "?")
    dest = res.dest if res.dest == "<stdout>" else short(res.dest)
    meta = f"{res.encoding_out}, {EOL_LABELS.get(res.eol_out or '', res.eol_out)}, {res.lines} line{'s' if res.lines != 1 else ''}"
    extra = ""
    if res.status != "converted":
        extra = f" [{res.status}]"
    tags = ", ".join(res.notes)
    line = f"{icon} {short(res.source)} {sym['arrow']} {st.bold(dest)}{extra} {st.dim('(' + meta + ')')}"
    if tags:
        line += " " + st.dim("[" + tags + "]")
    lines.append(line)
    if verbose:
        lines.append(st.dim(f"    input: {res.encoding_in}, {EOL_LABELS.get(res.eol_in or '', res.eol_in)}; output: {res.bytes:,} bytes"))
    for w in res.warnings:
        lines.append(f"  {st.yellow(sym['warn'] + ' ' + w)}")
    return lines


def list_formats(stream) -> None:
    rows = sorted(PROFILES.values(), key=lambda p: p.ext)
    stream.write(f"{'EXT':<9}{'EOL':<6}{'CHECK':<8}{'SHEBANG':<24}DESCRIPTION\n")
    for p in rows:
        stream.write(f"{p.ext:<9}{EOL_LABELS[p.eol]:<6}{(p.checker or '-'):<8}{(p.shebang or '-'):<24}{p.description}\n")
    stream.write("\nAny other extension works too, using LF line endings and no extras.\n")
    stream.write("Aliases: " + ", ".join(f"{k}={v}" for k, v in sorted(EXT_ALIASES.items())) + "\n")


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

EPILOG = """\
examples:
  %(prog)s notes.txt py                         notes.txt -> notes.py (LF, shebang, chmod +x)
  %(prog)s "C:\\docs\\setup.txt" bat -e cp1252    Windows batch file with CRLF line endings
  %(prog)s draft.md sh --extract --sanitize      pull the ```sh blocks out of a Markdown file
  %(prog)s README.md html --toc --title Docs     render Markdown to a standalone web page
  %(prog)s docs/ -r html -d site/                convert a whole folder tree
  %(prog)s *.txt py --dry-run --diff             preview every change without writing
  cat snippet.txt | %(prog)s - py -o -           filter mode: stdin to stdout
  %(prog)s --list-formats                        show every built-in format

exit status: 0 success, 1 at least one file failed, 2 usage error.
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        usage="%(prog)s [options] FILE [FILE ...] EXT\n       %(prog)s [options] --to EXT FILE [FILE ...]",
        description="Convert plain text or Markdown files into scripts, batch files, config files or web pages, "
                    "fixing line endings, encodings, shebangs and permissions along the way.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("args", nargs="*", metavar="FILE... EXT",
                   help="one or more input files, directories or glob patterns ('-' for stdin), "
                        "followed by the target extension (e.g. py, sh, bat, html)")
    p.add_argument("-t", "--to", metavar="EXT", help="target extension; when given, every positional argument is an input")
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--list-formats", action="store_true", help="list built-in formats and exit")

    g = p.add_argument_group("encoding")
    g.add_argument("-e", "--encoding", metavar="ENC", help="output encoding, e.g. utf-8, ascii, cp1252, utf-16 (default: utf-8)")
    g.add_argument("-i", "--input-encoding", metavar="ENC", help="input encoding (default: auto-detect BOM / UTF-8 / cp1252)")
    g.add_argument("--errors", default="strict",
                   choices=["strict", "replace", "ignore", "xmlcharrefreplace", "backslashreplace"],
                   help="what to do with characters the output encoding cannot represent (default: strict)")
    g.add_argument("--bom", choices=["auto", "yes", "no"], default="auto",
                   help="write a byte-order mark; auto adds one only where the format needs it, e.g. "
                        "non-ASCII PowerShell (default: auto)")

    g = p.add_argument_group("line endings")
    g.add_argument("--eol", choices=["auto", "lf", "crlf", "cr", "keep"], default="auto",
                   help="line ending style; auto picks CRLF for Windows formats and LF otherwise (default: auto)")
    g.add_argument("--no-fix", action="store_true", help="keep the original line endings (same as --eol keep)")

    g = p.add_argument_group("content")
    g.add_argument("-x", "--extract", action="store_true",
                   help="keep only the fenced code blocks (```lang ... ```) matching the target language")
    g.add_argument("--lang", action="append", default=[], metavar="LANG",
                   help="fence language(s) to extract (repeatable, or 'all'); default depends on the target")
    g.add_argument("-s", "--sanitize", action="store_true",
                   help="replace smart quotes, long dashes, ellipses, no-break and zero-width spaces with ASCII")
    g.add_argument("--strip-trailing", action="store_true", help="remove trailing whitespace from every line")
    g.add_argument("--tabs", type=int, metavar="N", help="expand tabs to N spaces")
    g.add_argument("--dedent", action="store_true", help="remove common leading indentation")
    g.add_argument("--trim", action="store_true", help="remove leading and trailing blank lines")
    g.add_argument("--no-final-newline", action="store_true", help="don't add a newline at the end of the file")
    g.add_argument("--header", nargs="?", const=DEFAULT_HEADER, metavar="TEXT",
                   help="add a comment at the top; placeholders {source} {date} {time} {version} "
                        "(default text: %(const)r)")
    sb = g.add_mutually_exclusive_group()
    sb.add_argument("--shebang", metavar="LINE", help="custom shebang line, e.g. '/usr/bin/python3.12'")
    sb.add_argument("--no-shebang", action="store_true", help="never add a shebang line")
    g.add_argument("--no-chmod", action="store_true", help="don't mark files with a shebang as executable")

    g = p.add_argument_group("html output")
    g.add_argument("--title", help="page title (default: first heading or file name)")
    g.add_argument("--css", metavar="FILE", help="embed this stylesheet instead of the built-in one")
    g.add_argument("--no-css", action="store_true", help="don't embed any stylesheet")
    g.add_argument("--toc", action="store_true", help="add a table of contents built from the headings")
    g.add_argument("--markdown", choices=["auto", "yes", "no"], default="auto",
                   help="render input as Markdown; auto does so for .md files (default: auto)")

    g = p.add_argument_group("validation")
    g.add_argument("-c", "--check", action="store_true",
                   help="syntax-check the output (python, json, toml, ini, xml built in; sh/bash/node/ruby/perl/php if installed)")
    g.add_argument("--strict", action="store_true", help="like --check, but don't write files that fail it")

    g = p.add_argument_group("output location")
    g.add_argument("-o", "--output", metavar="PATH",
                   help="output file (single input only) or existing directory; '-' writes to stdout")
    g.add_argument("-d", "--output-dir", metavar="DIR", help="write outputs here, mirroring folder structure")
    g.add_argument("--suffix", default="", metavar="TEXT", help="add TEXT to output names: notes.txt -> notes<TEXT>.py")
    g.add_argument("-f", "--force", action="store_true", help="overwrite existing files (same as --on-conflict overwrite)")
    g.add_argument("--on-conflict", choices=["error", "overwrite", "skip", "rename"], default=None,
                   help="when the destination exists (default: error)")
    g.add_argument("--backup", action="store_true", help="keep a .bak copy of files that get overwritten")
    g.add_argument("--remove-source", action="store_true", help="delete each source file after a successful conversion")

    g = p.add_argument_group("input selection")
    g.add_argument("-r", "--recursive", action="store_true", help="descend into sub-directories of directory inputs")
    g.add_argument("--include", action="append", metavar="GLOB",
                   help=f"file patterns picked up from directories (default: {' '.join(DEFAULT_INCLUDE)})")
    g.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="skip files matching this pattern")
    g.add_argument("--max-size", type=float, default=50, metavar="MB", help="skip files larger than this (default: 50)")

    g = p.add_argument_group("behaviour & reporting")
    g.add_argument("-n", "--dry-run", action="store_true", help="show what would happen without writing anything")
    g.add_argument("--diff", action="store_true", help="print a unified diff of the content changes")
    g.add_argument("-w", "--watch", action="store_true", help="keep running and re-convert inputs whenever they change")
    g.add_argument("--interval", type=float, default=1.0, metavar="SEC", help="polling interval for --watch (default: 1)")
    g.add_argument("--json", action="store_true", help="print a machine-readable JSON report")
    g.add_argument("-v", "--verbose", action="store_true", help="show more detail")
    g.add_argument("-q", "--quiet", action="store_true", help="only print errors")
    g.add_argument("--color", choices=["auto", "always", "never"], default="auto", help="colorize output (default: auto)")
    return p


def options_from_args(a: argparse.Namespace) -> Options:
    css = None
    if a.no_css:
        css = ""
    elif a.css:
        try:
            css = Path(a.css).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise ConversionError(f"cannot read --css file: {exc.strerror}: {a.css}") from None
    if a.tabs is not None and a.tabs < 1:
        raise ConversionError("--tabs must be at least 1")
    shebang = "none" if a.no_shebang else (a.shebang or "auto")
    return Options(
        encoding=canonical_encoding(a.encoding) if a.encoding else None,
        input_encoding=canonical_encoding(a.input_encoding) if a.input_encoding else None,
        errors=a.errors, eol="keep" if a.no_fix else a.eol, bom=a.bom, shebang=shebang,
        chmod=not a.no_chmod, extract=a.extract,
        langs=[s.strip() for item in a.lang for s in item.split(",") if s.strip()],
        sanitize=a.sanitize, strip_trailing=a.strip_trailing, expand_tabs=a.tabs, dedent=a.dedent,
        trim=a.trim, final_newline=not a.no_final_newline, header=a.header, markdown=a.markdown,
        title=a.title, css=css, toc=a.toc, check=a.check, strict=a.strict,
    )


def _watch(raw_inputs, cfg, a, st, sym, out, initial) -> int:
    outputs = {os.path.normcase(str(Path(r.dest).resolve())) for r in initial if r.dest and r.dest != "<stdout>"}
    mtimes = {}
    for src, _ in iter_inputs(raw_inputs, a.recursive, a.include or DEFAULT_INCLUDE, a.exclude):
        try:
            mtimes[src] = src.stat().st_mtime_ns
        except OSError:
            pass
    cfg.on_conflict = "overwrite"
    out.write(st.dim(f"watching {len(mtimes)} file(s); press Ctrl+C to stop\n"))
    out.flush()
    try:
        while True:
            time.sleep(max(a.interval, 0.1))
            try:
                found = list(iter_inputs(raw_inputs, a.recursive, a.include or DEFAULT_INCLUDE, a.exclude))
            except ConversionError:
                continue
            for src, root in found:
                if os.path.normcase(str(src.resolve())) in outputs:
                    continue
                try:
                    m = src.stat().st_mtime_ns
                except OSError:
                    continue
                if mtimes.get(src) == m:
                    continue
                mtimes[src] = m
                res = convert_one(src, root, cfg, diff_out=out)
                if res.dest and res.dest != "<stdout>":
                    outputs.add(os.path.normcase(str(Path(res.dest).resolve())))
                stamp = st.dim(time.strftime("[%H:%M:%S] "))
                for line in report_line(res, st, sym, a.verbose):
                    out.write(stamp + line + "\n")
                out.flush()
    except KeyboardInterrupt:
        out.write("\n")
        return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    a = parser.parse_intermixed_args(argv)

    if a.list_formats:
        list_formats(sys.stdout)
        return 0

    positional = list(a.args)
    if a.to:
        raw_ext, raw_inputs = a.to, positional
    elif len(positional) >= 2:
        raw_ext, raw_inputs = positional[-1], positional[:-1]
    elif len(positional) == 1 and Path(positional[0]).exists():
        parser.error("missing target extension, e.g.: %s %s py" % (PROG, positional[0]))
    else:
        parser.error("expected input file(s) followed by a target extension, e.g.: %s notes.txt py" % PROG)
    if not raw_inputs:
        parser.error("no input files given")

    to_stdout = a.output == "-"
    report_stream = sys.stderr if (to_stdout or a.json) else sys.stdout
    st = Style(want_color(a.color, report_stream))
    sym = _symbols(report_stream)

    def die(msg: str) -> int:
        sys.stderr.write(f"{PROG}: error: {msg}\n")
        return 2

    try:
        ext = normalize_ext(raw_ext)
        opts = options_from_args(a)
        inputs = list(iter_inputs(raw_inputs, a.recursive, a.include or DEFAULT_INCLUDE, a.exclude))
    except ConversionError as exc:
        return die(str(exc))

    if not inputs:
        return die("no matching input files found" + ("" if a.recursive else " (use -r to search sub-directories)"))
    if sum(1 for s, _ in inputs if str(s) == "-") > 1:
        return die("stdin ('-') can only be given once")
    if a.output and len(inputs) > 1 and a.output != "-" and not Path(a.output).is_dir():
        return die("-o/--output names a single file; use -d/--output-dir for several inputs")
    if to_stdout and len(inputs) > 1:
        return die("-o - (stdout) works with a single input only")
    if a.output and a.output_dir:
        return die("use either -o/--output or -d/--output-dir, not both")
    if a.watch and (to_stdout or any(str(s) == "-" for s, _ in inputs)):
        return die("--watch cannot be combined with stdin or stdout")
    if a.remove_source and a.dry_run:
        a.remove_source = False

    profile = get_profile(ext)
    if not profile.known and not a.quiet:
        sys.stderr.write(st.yellow(f"note: .{ext} is not a built-in format; using a generic LF profile "
                                   "(see --list-formats)") + "\n")

    if a.force and a.on_conflict not in (None, "overwrite"):
        return die("--force conflicts with --on-conflict " + a.on_conflict)
    cfg = RunConfig(
        ext=ext, profile=profile, opts=opts, output=a.output, output_dir=a.output_dir, suffix=a.suffix,
        on_conflict="overwrite" if a.force else (a.on_conflict or "error"), backup=a.backup,
        dry_run=a.dry_run, diff=a.diff, remove_source=a.remove_source, max_size=int(a.max_size * 1024 * 1024),
    )

    results: List[Result] = []
    diff_stream = sys.stderr if to_stdout else sys.stdout
    for src, root in inputs:
        res = convert_one(src, root, cfg, diff_out=diff_stream if a.diff else None)
        results.append(res)
        if a.json:
            continue
        if a.quiet and res.ok:
            continue
        for line in report_line(res, st, sym, a.verbose):
            report_stream.write(line + "\n")

    failed = sum(1 for r in results if r.status == "failed")
    if a.json:
        payload = {
            "version": __version__, "target": ext,
            "summary": {s: sum(1 for r in results if r.status == s)
                        for s in ("converted", "unchanged", "skipped", "dry-run", "failed")},
            "results": [asdict(r) for r in results],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    elif not a.quiet and len(results) > 1:
        counts = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        warn = sum(len(r.warnings) for r in results)
        parts = [f"{v} {k}" for k, v in counts.items()]
        if warn:
            parts.append(f"{warn} warning{'s' if warn != 1 else ''}")
        summary = ", ".join(parts)
        report_stream.write((st.red(summary) if failed else st.bold(summary)) + "\n")

    if a.watch:
        return _watch(raw_inputs, cfg, a, st, sym, report_stream, results)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:
        sys.exit(141 if os.name != "nt" else 1)

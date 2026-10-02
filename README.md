# CLI File Extension Converter

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![CI](https://github.com/nothikemu/cli/actions/workflows/ci.yml/badge.svg)

A single-file, dependency-free command-line tool that turns plain text and Markdown documents into **ready-to-run scripts, batch files, config files and web pages**.

Renaming `notes.txt` to `notes.sh` often produces a file that won't run. Common causes are Windows line endings, a missing shebang, a missing executable bit, curly quotes pasted from a word processor, a no-break space, or code still wrapped in Markdown fences. `convert.py` fixes these automatically and tells you about anything it can't fix.

```console
$ python convert.py notes.txt py
✓ notes.txt → notes.py (utf-8, LF, 12 lines) [shebang, +x]
  ! 3 typographic/invisible character(s) such as “ ” ’ — or no-break spaces found; they break most interpreters - rerun with --sanitize
```

---

## Features

**Correct output for the target platform**
- **Line endings per format.** CRLF for `.bat`, `.cmd`, `.ps1`, `.vbs`, `.reg` and `.csv`, and LF for `.py`, `.sh`, `.rb` and others. You can override this with `--eol`, or keep the original endings with `--no-fix`.
- **Encoding handling.** Input encoding is auto-detected (BOM → UTF-8 → Windows-1252). Output can be any Python codec (`utf-8`, `ascii`, `cp1252`, `cp437`, `utf-16`, …). If a character can't be encoded, the error gives its exact line and column.
- **Byte-order marks.** A BOM is added only where it's needed (for example, PowerShell scripts that contain non-ASCII text). A BOM is never placed in front of a shebang line.
- **Shebang and executable bit.** `#!/usr/bin/env python3`, `#!/bin/sh` and similar lines are added when missing, and the file is made executable (`chmod +x`). You can supply a custom line with `--shebang`, or turn this off with `--no-shebang` / `--no-chmod`.

**Content cleanup**
- **`--sanitize`** replaces smart quotes, en/em dashes, ellipses, and no-break and zero-width spaces with plain ASCII. Without it, you get a warning whenever these characters appear in a code file.
- **`--extract`** pulls the fenced code blocks for the target language out of a Markdown document. For example, `--extract` to `sh` keeps the `` ```sh `` and `` ```bash `` blocks and drops the prose.
- `--strip-trailing`, `--tabs N`, `--dedent` and `--trim` clean up whitespace, and a final newline is always ensured.
- `--header` adds a "generated from …" comment at the top, using the target format's comment syntax.

**Markdown → HTML**
- Converting to `.html` renders Markdown into a standalone page with responsive light/dark styling. Supported: headings, lists (nested, ordered, task lists), tables with alignment, code blocks, block quotes, links, images, emphasis and strikethrough.
- `--toc` adds a table of contents, and `--title`, `--css FILE` and `--no-css` control the page. Plain `.txt` input is wrapped in a `<pre>` block.

**Validation**
- `--check` syntax-checks the output. Python, JSON, TOML, INI and XML checks are built in. Shell (`sh`/`bash`/`zsh`/`fish`), Node, Ruby, Perl and PHP are checked when those tools are installed, and YAML when PyYAML is.
- `--strict` works like `--check` but refuses to write a file that fails.

**Batch work and safety**
- Accepts many files, directories (`-r` to recurse), glob patterns (these also work on Windows `cmd`), and stdin/stdout (`-`).
- `-d DIR` writes into another folder and mirrors the source tree.
- Existing files are never overwritten unless you ask. Use `--force`, `--on-conflict rename|skip`, and optionally `--backup`.
- Writes are atomic, so a crash never leaves a half-written file. Unchanged outputs aren't touched.
- `--dry-run` and `--diff` preview changes, and `--watch` re-converts whenever a source file changes.
- `--json` produces a machine-readable report, and exit codes are meaningful (`0` OK, `1` a file failed, `2` usage error).

---

## Installation

**Option A: just the script.** Download [`convert.py`](convert.py) anywhere and run it with Python 3.9 or newer. It has no dependencies.

**Option B: install as a command.**
```bash
pip install git+https://github.com/nothikemu/cli
convert-text notes.txt py
```

---

## Step-by-Step Usage Guide

1. **Save the script.** Put `convert.py` in a folder you can find again, such as `/path/to/your/scripts/`.
2. **Open a terminal.**
   - Windows: press the Windows key, type `cmd`, and press Enter.
   - macOS: press Cmd + Space, type `Terminal`, and press Enter.
   - Linux: open your terminal application.
3. **Go to the script folder.**
   ```bash
   cd "/path/to/your/scripts"
   ```
4. **Run a conversion.** Pass the file, then the extension you want. Put quotes around paths that contain spaces.
   ```bash
   python convert.py "/path/to/documents/notes.txt" py
   ```
   The new file appears next to the original, which is left untouched.

---

## Examples

```bash
# Python script: LF endings, shebang, executable
python convert.py notes.txt py

# Windows batch file using the classic Windows character set
python convert.py "C:\path\to\documents\notes.txt" bat -e cp1252

# Shell script from a Markdown draft: keep only the code blocks, fix curly quotes, syntax-check
python convert.py script_draft.md sh --extract --sanitize --check

# Render Markdown documentation to a web page with a table of contents
python convert.py README.md html --toc --title "Project docs"

# Convert a whole folder tree of .md/.txt files into a separate site/ folder
python convert.py docs/ html -r -d site/

# See exactly what would change, without writing anything
python convert.py *.txt py --dry-run --diff

# Use it as a filter in a pipeline
cat snippet.txt | python convert.py - ps1 -o - > snippet.ps1

# Rebuild automatically while you edit
python convert.py notes.md html --watch

# Put the target first when that reads better
python convert.py --to sh part1.txt part2.txt part3.txt
```

Run `python convert.py --list-formats` to see every built-in format. Any other extension also works and gets LF line endings with no extras. Common names such as `python`, `batch`, `powershell` and `markdown` are accepted as aliases.

| Format | Extensions | Line endings | Extras |
| :--- | :--- | :--- | :--- |
| Unix scripts | `py sh bash zsh fish rb pl awk command` | LF | shebang, `chmod +x`, syntax check |
| Windows scripts | `bat cmd ps1 psm1 vbs reg ahk pyw` | CRLF | BOM for non-ASCII PowerShell/AutoHotkey, code-page warning for batch |
| Source code | `js mjs cjs ts go rs c cpp java lua r php sql` | LF | `node --check` / `php -l` when installed |
| Data & config | `json yaml yml toml ini cfg env xml svg csv tsv` | LF (CSV: CRLF) | parsers for JSON/TOML/INI/XML/YAML |
| Documents | `html htm md txt css` | LF | Markdown → HTML rendering |

---

## Command Line Reference

```text
python convert.py [options] FILE [FILE ...] EXT
python convert.py [options] --to EXT FILE [FILE ...]
```

| Argument / Flag | Description | Default |
| :--- | :--- | :--- |
| `FILE` | One or more files, directories or glob patterns. Use `-` for stdin. | *required* |
| `EXT` | Target extension (e.g. `py`, `bat`, `sh`, `html`). A leading dot is fine. | *required* |
| `-t`, `--to EXT` | Give the target as an option; then every positional argument is an input. | |
| **Encoding** | | |
| `-e`, `--encoding ENC` | Output encoding (`utf-8`, `ascii`, `cp1252`, `utf-16`, …). | `utf-8` |
| `-i`, `--input-encoding ENC` | Input encoding. | auto-detect |
| `--errors MODE` | Handling for characters the output encoding can't represent: `strict`, `replace`, `ignore`, `xmlcharrefreplace`, `backslashreplace`. | `strict` |
| `--bom auto\|yes\|no` | Write a byte-order mark. | `auto` |
| **Line endings** | | |
| `--eol auto\|lf\|crlf\|cr\|keep` | Line-ending style. | `auto` (per format) |
| `--no-fix` | Keep the original line endings (same as `--eol keep`). | |
| **Content** | | |
| `-x`, `--extract` | Keep only the fenced code blocks for the target language. | |
| `--lang LANG` | Fence language(s) to extract. Repeatable; `all` takes every block. | per format |
| `-s`, `--sanitize` | Replace smart punctuation and invisible characters with ASCII. | |
| `--strip-trailing` | Remove trailing whitespace. | |
| `--tabs N` | Expand tabs to N spaces. | |
| `--dedent` | Remove common leading indentation. | |
| `--trim` | Remove leading and trailing blank lines. | |
| `--no-final-newline` | Don't add a newline at the end of the file. | |
| `--header [TEXT]` | Add a comment at the top. Placeholders: `{source}` `{date}` `{time}` `{version}`. | |
| `--shebang LINE` / `--no-shebang` | Set a custom shebang line, or never add one. | per format |
| `--no-chmod` | Don't mark scripts as executable. | |
| **HTML output** | | |
| `--title TEXT` | Page title. | first heading |
| `--css FILE` / `--no-css` | Use a custom stylesheet, or none. | built-in |
| `--toc` | Add a table of contents. | |
| `--markdown auto\|yes\|no` | Whether to render the input as Markdown. | `auto` (`.md` inputs) |
| **Validation** | | |
| `-c`, `--check` | Syntax-check the output and warn on errors. | |
| `--strict` | Syntax-check and don't write files that fail. | |
| **Output location** | | |
| `-o`, `--output PATH` | Output file (single input) or directory; `-` writes to stdout. | next to source |
| `-d`, `--output-dir DIR` | Output folder, mirroring the input tree. | |
| `--suffix TEXT` | `notes.txt` → `notes<TEXT>.py`. | |
| `-f`, `--force` | Overwrite existing files. | |
| `--on-conflict MODE` | What to do when the destination exists: `error`, `overwrite`, `skip`, `rename`. | `error` |
| `--backup` | Keep a `.bak` copy of files that get overwritten. | |
| `--remove-source` | Delete the source after a successful conversion. | |
| **Input selection** | | |
| `-r`, `--recursive` | Recurse into directories. | |
| `--include GLOB` / `--exclude GLOB` | Choose which files in directories get converted. | `*.txt *.md …` |
| `--max-size MB` | Skip files larger than this. | `50` |
| **Behaviour & reporting** | | |
| `-n`, `--dry-run` | Show what would happen without writing anything. | |
| `--diff` | Print a unified diff of the content changes. | |
| `-w`, `--watch` / `--interval SEC` | Re-convert inputs when they change. | `1` second |
| `--json` | Print a machine-readable JSON report. | |
| `-v`, `--verbose` / `-q`, `--quiet` | Show more detail / only print errors. | |
| `--color auto\|always\|never` | Colorize output. `NO_COLOR` and `FORCE_COLOR` are honoured. | `auto` |
| `--list-formats` | List built-in formats. | |
| `-V`, `--version` | Show the version. | |

> **Tip:** because `--header` takes an *optional* value, `--header notes.txt py` would use `notes.txt` as the header text. Put a bare `--header` after your file names, or pass the text explicitly: `--header "Built by CI"`.

---

## Development

```bash
python -m unittest discover -s tests -v
```

CI runs the test suite on Linux, macOS and Windows with Python 3.9 and 3.13.

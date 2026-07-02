# CLI File Extension Converter

![Python Version](https://shields.io)
![Platform](https://shields.io)
![License](https://shields.io)
![Maintained](https://shields.io)

A lightweight, practical command-line tool designed to convert plain text files (.txt or .md) into code scripts, batch files, or web documents. 

Unlike a simple file rename, this utility handles background compatibility by correcting operating system-specific line endings and character encodings automatically.

---

## Core Features

* **Line-Ending Adjustment**: Automatically applies Windows carriage returns (\r\n) for .bat files or Unix line feeds (\n) for .py and .sh scripts to prevent execution syntax errors.
* **Encoding Selection**: Allows explicit conversion between utf-8, ascii, or Windows-standard cp1252 character sets.
* **Safe Processing**: Leaves your source document completely untouched and outputs the new file in the original directory.

---

## Step-by-Step Usage Guide

### Step 1: Save the Script
Save the Python application code on your system as `convert.py`. Take note of the folder path where you place it (for example: `/path/to/your/scripts/`).

### Step 2: Open the Terminal
* **Windows**: Press the Windows Key, type `cmd`, and press Enter.
* **macOS/Linux**: Press Cmd + Space (or your system shortcut), type `Terminal`, and press Enter.

### Step 3: Navigate to the Script Directory
Use the change directory (`cd`) command to move your terminal focus to the folder containing `convert.py`:
```bash
cd "/path/to/your/scripts"
```

### Step 4: Execute the Conversion
Run the script by passing the target file path followed by your desired file extension. Wrap the path in quotation marks if your file name contains spaces.

#### Example 1: Convert to a Python Script (.py)
```bash
python convert.py "/path/to/documents/notes.txt" py
```

#### Example 2: Convert to a Windows Batch File (.bat)
This example enforces the standard Windows character set (cp1252):
```bash
python convert.py "C:\(\path\to\documents\notes.\)txt" bat -e cp1252
```

#### Example 3: Convert to a Linux/macOS Shell Script (.sh)
```bash
python convert.py "/path/to/documents/script_draft.md" sh
```

The newly formatted file will generate instantly inside the same directory, positioned right alongside your original text file.

---

## Command Line Arguments

You can display the built-in manual inside your terminal interface at any time by running:
```bash
python convert.py --help
```

| Argument / Flag | Description | Default |
| :--- | :--- | :--- |
| `file` | **Required.** The absolute file path to your source text document. | *None* |
| `ext` | **Required.** The target file extension to output (e.g., py, bat, sh). | *None* |
| `-e`, `--encoding` | Specifies the character encoding format (utf-8, ascii, cp1252). | `utf-8` |
| `--no-fix` | Disables automatic line-ending adjustments for cross-platform files. | *Enabled* |

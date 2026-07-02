# 🛠️ CLI File Extension Converter

<!-- Visual Badges for GitHub -->
![Python Version](https://shields.io)
![Platform](https://shields.io)
![License](https://shields.io)
![Maintained](https://shields.io)

A lightweight, practical command-line tool to instantly convert plain text pad files (`.txt` or `.md`) into functioning code scripts, batch files, or web documents. 

Unlike a simple rename, this tool handles background compatibility by automatically correcting operating system-specific line endings and character encodings.

---

## 🔥 Key Features

* **Smart Line-Ending Fixes**: Automatically applies Windows breaks (`\r\n`) for `.bat` files or Unix breaks (`\n`) for `.py` and `.sh` files to prevent script syntax errors.
* **Custom Encodings**: Easily switch between `utf-8`, `ascii`, or Windows-standard `cp1252`.
* **Safe Processing**: Never deletes or modifies your original text files; it generates a brand-new file right next to the source.

---

## 🚀 Step-by-Step Instructions

Follow these steps to set up and run the application on your machine.

### Step 1: Download the Script
Save the Python code onto your computer as a file named `convert.py`. Take note of which folder you save it in (for example: `C:\Users\lohit\Documents\Scripts`).

### Step 2: Open Your Terminal
* **Windows**: Press the `Windows Key`, type `cmd`, and press `Enter`.
* **Mac**: Press `Cmd + Space`, type `Terminal`, and press `Enter`.

### Step 3: Navigate to the Script Folder
Use the `cd` command to move your terminal into the exact folder where you saved `convert.py`:
```bash
cd "C:\Users\lohit\Documents\Scripts"
```

### Step 4: Run the Conversion Command
Use the following format to run your tool. Make sure to wrap your file path in **quotation marks** if your file name contains spaces.

#### 📝 Real-World Examples:

* **Convert to a Python Script (`.py`)**
  ```bash
  python convert.py "C:\Users\lohit\Documents\PC\Ready or Not.txt" py
  ```

* **Convert to a Windows Batch File (`.bat`)**
  ```bash
  python convert.py "C:\Users\lohit\Documents\PC\Ready or Not.txt" bat -e cp1252
  ```

* **Convert to a Linux/Mac Shell Script (`.sh`)**
  ```bash
  python convert.py "C:\Users\lohit\Documents\PC\Ready or Not.txt" sh
  ```

Your newly converted file will instantly appear in the `C:\Users\lohit\Documents\PC\` folder right next to your original file!

---

## ⚙️ Command Options & Flags

You can view the built-in user manual inside your terminal at any time by running:
```bash
python convert.py --help
```

| Argument / Flag | Description | Default |
| :--- | :--- | :--- |
| `file` | **(Required)** The full absolute path to your source text file. | *None* |
| `ext` | **(Required)** The target file extension you want to output. | *None* |
| `-e`, `--encoding` | Specify character encoding (e.g., `utf-8`, `ascii`, `cp1252`). | `utf-8` |
| `--no-fix` | Disables the automatic line-ending adjustments. | *Enabled* |

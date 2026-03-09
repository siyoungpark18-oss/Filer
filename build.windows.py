"""
Build script for File & Folder Manager — Windows
Run this from the project folder: python build_windows.py

Prerequisites:
  1. Python 3.8+ installed from python.org (with tkinter checked)
  2. Download poppler for Windows from:
     https://github.com/oschwartz10612/poppler-windows/releases
     Extract it and place the folder as 'poppler' next to this script.
     Expected structure:
       poppler/
         bin/
           pdftoppm.exe
           pdfinfo.exe
           ... etc

The build will bundle poppler inside the .exe distribution so end
users do not need to install it separately.
"""

import subprocess
import sys
import shutil
from pathlib import Path

APP_NAME    = "File & Folder Manager"
MAIN_SCRIPT = "gui.py"
DIST        = Path("dist")
APP_DIR     = DIST / APP_NAME
POPPLER_SRC = Path("poppler")


def run(cmd):
    print(f"\n>>> {' '.join(str(c) for c in cmd)}\n")
    subprocess.run(cmd, check=True)


def clean():
    print("Cleaning previous build artifacts...")
    for folder in ["build", "dist", "__pycache__"]:
        if Path(folder).exists():
            shutil.rmtree(folder)
            print(f"  Removed {folder}/")
    for spec in Path(".").glob("*.spec"):
        spec.unlink()
        print(f"  Removed {spec.name}")


def check_poppler():
    if not POPPLER_SRC.exists() or not (POPPLER_SRC / "bin").exists():
        print("\n  ERROR: poppler folder not found.")
        print("  Download from: https://github.com/oschwartz10612/poppler-windows/releases")
        print("  Extract and place as 'poppler/' next to this script.")
        print("  Expected: poppler/bin/pdftoppm.exe")
        sys.exit(1)
    print(f"  Found poppler at: {POPPLER_SRC.resolve()}")


REQUIREMENTS = """\
pyinstaller
pillow
img2pdf
pypdf
pdf2image
psutil
"""

def ensure_requirements():
    if not Path("requirements.txt").exists():
        Path("requirements.txt").write_text(REQUIREMENTS)
        print("  Created requirements.txt")

def install_dependencies():
    print("Installing dependencies...")
    ensure_requirements()
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])


def build_app():
    print("Building with PyInstaller...")
    poppler_bin = str(POPPLER_SRC / "bin")
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onedir",
        "--name", APP_NAME,
        "--hidden-import", "psutil",
        "--hidden-import", "pdf2image",
        "--hidden-import", "PIL._tkinter_finder",
        "--add-data", f"Manager.py;.",
        "--add-data", f"{poppler_bin};poppler/bin",
        MAIN_SCRIPT,
    ])
    print(f"\nBuild output: {APP_DIR}")


def patch_manager_for_windows():
    """
    Inject poppler_path detection into the built Manager.py so that
    convert_from_path finds the bundled poppler at runtime.
    We patch the copy inside the dist folder, not the source.
    """
    target = APP_DIR / "Manager.py"
    if not target.exists():
        print("  Warning: could not find Manager.py in dist to patch.")
        return

    original = target.read_text(encoding="utf-8")
    patch = '''
import platform as _platform
import sys as _sys

def _get_poppler_path():
    if _platform.system() == "Windows":
        base = getattr(_sys, "_MEIPASS", None)
        if base:
            return str(__import__("pathlib").Path(base) / "poppler" / "bin")
    return None

_POPPLER_PATH = _get_poppler_path()
'''
    insert_after = "from pypdf import PdfReader, PdfWriter"
    if insert_after in original and "_POPPLER_PATH" not in original:
        patched = original.replace(insert_after, insert_after + "\n" + patch)
        patched = patched.replace(
            "convert_from_path(str(pdf_path)",
            "convert_from_path(str(pdf_path), poppler_path=_POPPLER_PATH"
        )
        target.write_text(patched, encoding="utf-8")
        print("  Patched Manager.py with bundled poppler path.")
    else:
        print("  Manager.py already patched or insert point not found.")


if __name__ == "__main__":
    try:
        clean()
        check_poppler()
        install_dependencies()
        build_app()
        patch_manager_for_windows()
        print(f"\n✓ Done! Distribute the folder: dist/{APP_NAME}/")
        print(f"  Run with: dist/{APP_NAME}/{APP_NAME}.exe")
    except subprocess.CalledProcessError as e:
        print(f"\nBuild failed: {e}")
        sys.exit(1)
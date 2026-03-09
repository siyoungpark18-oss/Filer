
"""
Build script for File & Folder Manager
Run this from the project folder: python build.py
"""

import subprocess
import sys
import shutil
from pathlib import Path

APP_NAME    = "File & Folder Manager"
MAIN_SCRIPT = "gui.py"
DIST        = Path("dist")
APP_PATH    = DIST / f"{APP_NAME}.app"
DMG_PATH    = Path(f"{APP_NAME}.dmg")


def run(cmd):
    print(f"\n>>> {' '.join(cmd)}\n")
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
    print("Installing build dependencies...")
    ensure_requirements()
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    print("\nNote: pdf2image requires poppler to be installed separately.")
    print("  Mac:     brew install poppler")
    print("  Windows: download from https://github.com/oschwartz10612/poppler-windows")


def build_app():
    print("Building .app with PyInstaller...")
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onedir",
        "--name", APP_NAME,
        "--hidden-import", "psutil",
        "--hidden-import", "pdf2image",
        "--hidden-import", "PIL._tkinter_finder",
        "--add-data", "Manager.py:.",
        MAIN_SCRIPT,
    ])
    print(f"\n.app built at: {APP_PATH}")


def build_dmg():
    print("Building .dmg...")
    if DMG_PATH.exists():
        DMG_PATH.unlink()

    staging = Path("dist/dmg_staging")
    staging.mkdir(parents=True, exist_ok=True)

    app_dest = staging / APP_PATH.name
    if app_dest.exists():
        shutil.rmtree(app_dest)
    shutil.copytree(str(APP_PATH), str(app_dest))

    applications_link = staging / "Applications"
    if not applications_link.exists():
        applications_link.symlink_to("/Applications")

    run([
        "hdiutil", "create",
        "-volname", APP_NAME,
        "-srcfolder", str(staging),
        "-ov",
        "-format", "UDZO",
        str(DMG_PATH),
    ])
    shutil.rmtree(staging)
    print(f"\n.dmg built at: {DMG_PATH}")


if __name__ == "__main__":
    try:
        clean()
        install_dependencies()
        build_app()
        build_dmg()
        print(f"\n✓ Done! '{DMG_PATH}' is ready to distribute.")
    except subprocess.CalledProcessError as e:
        print(f"\nBuild failed: {e}")
        sys.exit(1)




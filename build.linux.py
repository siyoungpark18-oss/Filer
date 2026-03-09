"""
Build script for File & Folder Manager — Linux
Produces a standalone AppImage that runs on most x86_64 Linux distros.

Run this from the project folder: python build_linux.py

Prerequisites (system packages):
  Debian/Ubuntu:  sudo apt install python3-tk poppler-utils fuse
  Fedora:         sudo dnf install python3-tkinter poppler-utils fuse
  Arch:           sudo pacman -S tk poppler fuse2

appimagetool is downloaded automatically.
"""

import subprocess
import sys
import shutil
import platform
import urllib.request
from pathlib import Path

APP_NAME     = "File-and-Folder-Manager"
APP_DISPLAY  = "File & Folder Manager"
MAIN_SCRIPT  = "gui.py"
DIST         = Path("dist")
APP_DIR      = DIST / APP_DISPLAY
APPDIR       = DIST / "AppDir"
APPIMAGE_OUT = Path(f"{APP_NAME}.AppImage")
APPIMAGETOOL = Path("appimagetool-x86_64.AppImage")
APPIMAGETOOL_URL = (
    "https://github.com/AppImage/AppImageKit/releases/download/continuous/"
    "appimagetool-x86_64.AppImage"
)


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
    if APPIMAGE_OUT.exists():
        APPIMAGE_OUT.unlink()
        print(f"  Removed {APPIMAGE_OUT}")


def check_platform():
    if platform.system() != "Linux":
        print(f"\n  ERROR: This script must be run on Linux (detected: {platform.system()}).")
        print("  Use build.py for Mac or build_windows.py for Windows.")
        sys.exit(1)
    if platform.machine() != "x86_64":
        print(f"\n  ERROR: Only x86_64 is supported (detected: {platform.machine()}).")
        sys.exit(1)


def check_system_dependencies():
    print("Checking system dependencies...")
    missing = []
    for binary in ["pdftoppm", "pdfinfo"]:
        if subprocess.run(["which", binary], capture_output=True).returncode != 0:
            missing.append(binary)
    if missing:
        print(f"\n  ERROR: poppler not found ({', '.join(missing)}).")
        print("  Install it first:")
        print("    Debian/Ubuntu:  sudo apt install poppler-utils")
        print("    Fedora:         sudo dnf install poppler-utils")
        print("    Arch:           sudo pacman -S poppler")
        sys.exit(1)
    print("  poppler found.")

    # fuse is required to run AppImages (including appimagetool itself)
    fuse_ok = (
        subprocess.run(["modinfo", "fuse"], capture_output=True).returncode == 0 or
        Path("/dev/fuse").exists()
    )
    if not fuse_ok:
        print("\n  WARNING: fuse may not be available. appimagetool requires it.")
        print("    Debian/Ubuntu:  sudo apt install fuse")
        print("    Arch:           sudo pacman -S fuse2")


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

def install_python_dependencies():
    print("Installing Python dependencies...")
    ensure_requirements()
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])


def fetch_appimagetool():
    if APPIMAGETOOL.exists():
        print(f"  appimagetool already present, skipping download.")
        return
    print(f"  Downloading appimagetool...")
    urllib.request.urlretrieve(APPIMAGETOOL_URL, APPIMAGETOOL)
    APPIMAGETOOL.chmod(0o755)
    print(f"  Saved: {APPIMAGETOOL}")


def build_with_pyinstaller():
    print("Building with PyInstaller...")
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onedir",
        "--name", APP_DISPLAY,
        "--hidden-import", "psutil",
        "--hidden-import", "pdf2image",
        "--hidden-import", "PIL._tkinter_finder",
        "--add-data", "Manager.py:.",
        MAIN_SCRIPT,
    ])


def build_appdir():
    print("Assembling AppDir...")
    if APPDIR.exists():
        shutil.rmtree(APPDIR)
    APPDIR.mkdir(parents=True)

    # Copy PyInstaller output into AppDir/usr/bin
    usr_bin = APPDIR / "usr" / "bin"
    shutil.copytree(str(APP_DIR), str(usr_bin / APP_DISPLAY))

    # AppRun — entry point that AppImage calls on launch
    apprun = APPDIR / "AppRun"
    apprun.write_text(
        '#!/bin/bash\n'
        'SELF=$(readlink -f "$0")\n'
        'HERE=$(dirname "$SELF")\n'
        f'exec "$HERE/usr/bin/{APP_DISPLAY}/{APP_DISPLAY}" "$@"\n'
    )
    apprun.chmod(0o755)

    # Minimal .desktop file (required by AppImage spec)
    desktop = APPDIR / f"{APP_NAME}.desktop"
    desktop.write_text(
        f"[Desktop Entry]\n"
        f"Name={APP_DISPLAY}\n"
        f"Exec={APP_NAME}\n"
        f"Icon={APP_NAME}\n"
        f"Type=Application\n"
        f"Categories=Utility;\n"
    )

    # Placeholder icon (required — 256x256 PNG ideal, this is a 1x1 fallback)
    # Replace with a real icon by dropping a 256x256 PNG named {APP_NAME}.png
    # into the project folder before building.
    icon_src = Path(f"{APP_NAME}.png")
    icon_dst = APPDIR / f"{APP_NAME}.png"
    if icon_src.exists():
        shutil.copy2(icon_src, icon_dst)
    else:
        # Write a minimal valid 1x1 PNG so appimagetool doesn't fail
        import base64
        PNG_1x1 = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
            "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        )
        icon_dst.write_bytes(PNG_1x1)
        print("  No icon found — using placeholder. Drop a 256x256 PNG named "
              f"'{APP_NAME}.png' into the project folder for a real icon.")

    print(f"  AppDir ready: {APPDIR}")


def build_appimage():
    print("Building AppImage...")
    run([str(APPIMAGETOOL), str(APPDIR), str(APPIMAGE_OUT)])
    print(f"\n  AppImage: {APPIMAGE_OUT}")


if __name__ == "__main__":
    try:
        check_platform()
        clean()
        check_system_dependencies()
        install_python_dependencies()
        fetch_appimagetool()
        build_with_pyinstaller()
        build_appdir()
        build_appimage()
        print(f"\n✓ Done! Distribute: {APPIMAGE_OUT}")
        print(f"  Recipients just need to: chmod +x {APPIMAGE_OUT} && ./{APPIMAGE_OUT}")
        print(f"  (Most file managers will run it with a double-click.)")
    except subprocess.CalledProcessError as e:
        print(f"\nBuild failed: {e}")
        sys.exit(1)
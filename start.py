"""Launcher satu perintah untuk Google Rank Tracker Bot.

Jalankan:  python start.py
Semua akan diurus otomatis:
  1. Cek & install dependencies Python (requirements.txt)
  2. Cek & install browser Firefox untuk Playwright (+ install-deps di Linux)
  3. Cek & install Puppeteer/Node (opsional, untuk solver CAPTCHA manual)
  4. Bersihkan file parent.lock sisa crash
  5. Jalankan bot (rank.py) dengan auto-restart jika crash

Opsi:
  python start.py --setup-only   -> hanya install/persiapan, tanpa menjalankan bot
  python start.py --no-install   -> langsung jalankan bot tanpa cek dependencies
"""

import os
import sys
import glob
import time
import shutil
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IS_WINDOWS = os.name == "nt"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def banner(text):
    print(f"\n{'=' * 55}\n  {text}\n{'=' * 55}")


def run(cmd, check=True, **kwargs):
    """Jalankan perintah dan tampilkan outputnya langsung."""
    print(f"[start] Menjalankan: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=BASE_DIR, check=check, **kwargs)


# ---------- 1. Dependencies Python ----------

# peta: nama package pip -> nama module untuk import
REQUIRED_MODULES = {
    "requests": "requests",
    "beautifulsoup4": "bs4",
    "python-telegram-bot": "telegram",
    "playwright": "playwright",
    "playwright-stealth": "playwright_stealth",
    "ddgs": "ddgs",
}


def ensure_python_deps():
    banner("LANGKAH 1/4: Dependencies Python")
    missing = []
    for pkg, module in REQUIRED_MODULES.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pkg)

    if not missing:
        print("[start] Semua dependencies Python sudah terinstal. ✔")
        return

    print(f"[start] Package belum terinstal: {', '.join(missing)}")
    print("[start] Menginstal dari requirements.txt ...")
    try:
        run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("[start] Dependencies Python berhasil diinstal. ✔")
    except subprocess.CalledProcessError:
        print("[start] GAGAL menginstal dependencies Python. Cek koneksi internet/pip Anda.")
        sys.exit(1)


# ---------- 2. Browser Firefox Playwright ----------

def playwright_firefox_installed():
    """Cek apakah browser Firefox milik Playwright sudah terunduh."""
    if IS_WINDOWS:
        cache = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
    elif sys.platform == "darwin":
        cache = os.path.expanduser("~/Library/Caches/ms-playwright")
    else:
        cache = os.path.expanduser("~/.cache/ms-playwright")
    return bool(glob.glob(os.path.join(cache, "firefox-*")))


def ensure_playwright_browser():
    banner("LANGKAH 2/4: Browser Firefox (Playwright)")
    if playwright_firefox_installed():
        print("[start] Browser Firefox Playwright sudah terinstal. ✔")
        return

    print("[start] Browser Firefox belum ada. Mengunduh ...")
    try:
        run([sys.executable, "-m", "playwright", "install", "firefox"])
    except subprocess.CalledProcessError:
        print("[start] GAGAL mengunduh browser Firefox Playwright.")
        sys.exit(1)

    # Di Linux VPS, library sistem (GTK, fonts, dll.) juga wajib ada
    if not IS_WINDOWS and sys.platform != "darwin":
        print("[start] Linux terdeteksi — menginstal dependensi sistem browser ...")
        try:
            run([sys.executable, "-m", "playwright", "install-deps", "firefox"], check=False)
        except Exception as e:
            print(f"[start] Peringatan: install-deps gagal ({e}). "
                  "Jalankan manual: sudo playwright install-deps firefox")

    print("[start] Browser Firefox Playwright siap. ✔")


# ---------- 3. Puppeteer / Node (opsional) ----------

def puppeteer_chrome_ok(node):
    """Cek apakah browser Chrome milik Puppeteer sudah terunduh & utuh."""
    check_js = ("const p=require('puppeteer');"
                "require('fs').accessSync(p.executablePath());")
    result = subprocess.run([node, "-e", check_js], cwd=BASE_DIR,
                            capture_output=True, text=True)
    return result.returncode == 0


def ensure_node_deps():
    banner("LANGKAH 3/4: Puppeteer Solver (opsional)")
    npm = shutil.which("npm")
    node = shutil.which("node")
    npx = shutil.which("npx")
    if not npm or not node:
        print("[start] npm/Node.js tidak ditemukan — dilewati.")
        print("        (Hanya dibutuhkan untuk solver CAPTCHA manual: node solve_puppeteer.js)")
        return

    node_modules = os.path.join(BASE_DIR, "node_modules", "puppeteer")
    if not os.path.isdir(node_modules):
        print("[start] Menginstal Puppeteer via npm ...")
        try:
            run([npm, "install"], check=False)
        except Exception as e:
            print(f"[start] Peringatan: npm install gagal ({e}) — solver manual tidak tersedia, "
                  "bot tetap bisa jalan.")
            return

    # Pastikan browser Chrome-nya juga terunduh utuh (npm install saja tidak cukup)
    if puppeteer_chrome_ok(node):
        print("[start] Puppeteer + browser Chrome siap. ✔")
        return

    if npx:
        print("[start] Browser Chrome Puppeteer belum ada/rusak. Mengunduh ...")
        run([npx, "puppeteer", "browsers", "install", "chrome"], check=False)
        if puppeteer_chrome_ok(node):
            print("[start] Puppeteer + browser Chrome siap. ✔")
        else:
            print("[start] Peringatan: browser Chrome Puppeteer masih bermasalah. "
                  "Coba manual: npx puppeteer browsers install chrome")


# ---------- 4. Bersih-bersih & jalankan bot ----------

def cleanup_locks():
    lock_file = os.path.join(BASE_DIR, "firefox_profile", "parent.lock")
    if os.path.exists(lock_file):
        try:
            os.remove(lock_file)
            print("[start] File parent.lock sisa crash dihapus. ✔")
        except Exception as e:
            print(f"[start] Peringatan: gagal menghapus parent.lock: {e}")


def run_bot():
    banner("LANGKAH 4/4: Menjalankan Bot (auto-restart)")
    print("[start] Tekan Ctrl+C untuk berhenti.\n")
    restart_delay = 10
    while True:
        cleanup_locks()
        try:
            result = subprocess.run([sys.executable, "-u", "rank.py"], cwd=BASE_DIR)
        except KeyboardInterrupt:
            print("\n[start] Dihentikan oleh pengguna. Sampai jumpa!")
            return

        if result.returncode == 0:
            print("[start] Bot berhenti normal.")
            return

        print(f"\n[start] Bot crash (exit code {result.returncode}). "
              f"Restart otomatis dalam {restart_delay} detik... (Ctrl+C untuk batal)")
        try:
            time.sleep(restart_delay)
        except KeyboardInterrupt:
            print("\n[start] Dihentikan oleh pengguna. Sampai jumpa!")
            return


def main():
    setup_only = "--setup-only" in sys.argv
    no_install = "--no-install" in sys.argv

    banner("GOOGLE RANK TRACKER — ONE COMMAND LAUNCHER")

    if not no_install:
        ensure_python_deps()
        ensure_playwright_browser()
        ensure_node_deps()
    else:
        print("[start] Mode --no-install: melewati pengecekan dependencies.")

    if setup_only:
        print("\n[start] Setup selesai (mode --setup-only). "
              "Jalankan 'python start.py' untuk memulai bot.")
        return

    run_bot()


if __name__ == "__main__":
    main()

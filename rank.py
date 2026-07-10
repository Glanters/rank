import sys
import os
import json
import re
import html
import asyncio
import random
import time
import secrets
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs
import requests
# pyrefly: ignore [missing-import]
from bs4 import BeautifulSoup
# pyrefly: ignore [missing-import]
from ddgs import DDGS
# pyrefly: ignore [missing-import]
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
# pyrefly: ignore [missing-import]
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
# pyrefly: ignore [missing-import]
from playwright.async_api import async_playwright
# pyrefly: ignore [missing-import]
from playwright_stealth import Stealth

# Configure standard output to use UTF-8 to support emoji/special characters in Windows terminals
sys.stdout.reconfigure(encoding='utf-8')

# ==================== KONFIGURASI ====================
TELEGRAM_TOKEN = "8804541161:AAGpcO1se7k9v_ImqZLQoTPjwIVAdKHMcA8"
LOCATION = "Jakarta, Indonesia"
TIMEZONE = timezone(timedelta(hours=7))   # GMT+7

# Chat ID admin yang akan menerima notifikasi saat CAPTCHA Google perlu di-solve
# Isi dengan chat_id Anda. Cari tau dengan /start ke bot, lalu lihat di log terminal.
ADMIN_CHAT_ID = 6769855876   # Contoh: 123456789

# Backend metasearch (fallback):
BACKENDS = "google, bing, brave, duckduckgo"
REGION = "id-id"

# Opsional: pakai proxy residensial biar backend Google lebih sering tembus.
# Contoh: "socks5h://user:pass@host:port" atau "http://user:pass@host:port"
PROXY = {
    "http": "http://7LmoLRicjfmGcKj:XUdhrrU5YyGRG6r@178.93.21.231:48883",
    "https": "http://7LmoLRicjfmGcKj:XUdhrrU5YyGRG6r@178.93.21.231:48883"
}

# Pakai proxy untuk pencarian Google via browser?
# False = SEMUA percobaan Google lewat IP langsung (rumah) — direkomendasikan bila
#         proxy Anda adalah datacenter (pasti diblokir Google / kena CAPTCHA 429).
# True  = 2 percobaan pertama lewat proxy, percobaan ke-3 tanpa proxy.
# Catatan: proxy TETAP dipakai untuk fallback metasearch (DDGS) apa pun nilainya.
USE_PROXY_FOR_GOOGLE = False

# Jalankan browser headless (tak terlihat) atau headed (terlihat)?
# True  = headless — TAPI Google gampang mendeteksinya sebagai bot -> sering CAPTCHA.
# False = headed (jendela browser muncul) — JAUH lebih jarang kena CAPTCHA.
#         Cocok bila bot jalan di PC rumah yang punya layar. Di VPS tanpa layar,
#         biarkan True (atau pakai xvfb).
HEADLESS_BROWSER = True

# Jeda (detik) antar-keyword saat scan. Makin lama makin kecil resiko CAPTCHA
# karena laju pencarian tidak seperti bot. Dipakai di /scan & cron otomatis.
SCAN_DELAY_MIN = 12.0
SCAN_DELAY_MAX = 30.0

# Gunakan satu perangkat (User-Agent) yang KONSISTEN, bukan acak tiap request.
# Merotasi perangkat pada profil cookies yang sama = sinyal bot yang kuat.
STABLE_DEVICE = True

# --- Solve CAPTCHA jarak jauh via Telegram Mini App (untuk VPS headless) ---
# Saat CAPTCHA muncul, bot membuka sesi browser DI VPS lalu menyiarkan CAPTCHA-nya
# ke Mini App; tap Anda dikirim balik ke browser VPS. Butuh URL HTTPS publik.
CAPTCHA_WEB_ENABLED = True
# Domain HTTPS Anda yang mengarah ke server ini (WAJIB https, tanpa slash di akhir).
# Contoh: "https://rank.domainanda.com". Kosongkan ("") untuk menonaktifkan Mini App.
PUBLIC_BASE_URL = "https://rank.smbabsen.site/"
# Port lokal server relay (di belakang reverse proxy/HTTPS Anda).
CAPTCHA_WEB_PORT = 8099
# Perbarui exemption secara proaktif bila sisa masa berlaku < menit ini (0 = mati).
EXEMPTION_REFRESH_MIN = 25
# =====================================================

# Flag global: apakah notifikasi CAPTCHA sudah dikirim (hindari spam)
_captcha_notified = False
_bot_app_ref = None   # Referensi global ke aplikasi bot
_web_solver = None    # Instance CaptchaWebSolver (Mini App)
_web_solve_active = False  # Sedang ada sesi solve web berjalan
_web_solve_started_at = 0.0  # Waktu mulai sesi solve (untuk timeout)
WEB_SOLVE_TIMEOUT = 900      # Sesi solve dianggap basi setelah ini (detik)
CTR = {1: 28, 2: 15, 3: 11, 4: 8, 5: 7}
TAG = {"amp": "[AMP]", "landing": "[LND]", "biasa": "[REG]"}
BAR_W = 30


def get_exemption_seconds_left():
    """Sisa masa berlaku (detik) cookie GOOGLE_ABUSE_EXEMPTION valid, atau None."""
    try:
        best = None
        for c in collect_google_cookies("./firefox_profile"):
            if c.get("name") != "GOOGLE_ABUSE_EXEMPTION":
                continue
            exp = c.get("expires")
            try:
                exp = float(exp)
            except (ValueError, TypeError):
                continue
            if exp < 0:
                continue
            left = exp - time.time()
            if left > 0 and (best is None or left > best):
                best = left
        return best
    except Exception:
        return None


def _web_captcha_configured():
    return bool(CAPTCHA_WEB_ENABLED and PUBLIC_BASE_URL.startswith("https://"))


async def _on_web_solved():
    """Callback saat CAPTCHA di Mini App berhasil diselesaikan."""
    global _captcha_notified, _web_solve_active
    _captcha_notified = False
    _web_solve_active = False
    if _bot_app_ref and ADMIN_CHAT_ID:
        left = get_exemption_seconds_left()
        info = f" (berlaku ~{int(left/60)} menit)" if left else ""
        try:
            await _bot_app_ref.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"✅ <b>CAPTCHA selesai!</b> Cookies exemption diperbarui{info}. "
                     "Bot lanjut memakai Google-direct.",
                parse_mode="HTML",
            )
        except Exception:
            pass


async def trigger_web_captcha(reason="CAPTCHA terdeteksi"):
    """Buka sesi solve di VPS & kirim tombol Mini App ke admin."""
    global _web_solver, _web_solve_active, _web_solve_started_at
    if not _web_captcha_configured() or not _bot_app_ref or not ADMIN_CHAT_ID:
        return False
    # Blokir hanya bila ada sesi yang MASIH baru (belum timeout); sesi basi di-reset.
    if _web_solve_active and (time.time() - _web_solve_started_at) < WEB_SOLVE_TIMEOUT:
        return False
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
        import captcha_web

        if _web_solver is None:
            _web_solver = captcha_web.CaptchaWebSolver(
                profile_dir="./firefox_profile",
                save_cookies_fn=save_google_cookies,
                on_solved=_on_web_solved,
                ua=get_stable_ua(),
            )
        _web_solve_active = True
        _web_solve_started_at = time.time()
        token = secrets.token_urlsafe(16)
        await _web_solver.start(token)
        if _web_solver.state == "error":
            _web_solve_active = False
            await _bot_app_ref.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text="⚠️ Gagal membuka sesi solve di server. Coba lagi dengan /solveweb.",
            )
            return False

        url = f"{PUBLIC_BASE_URL}/solve?token={token}"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
            "🧩 Buka & Solve CAPTCHA di sini", web_app=WebAppInfo(url=url)
        )]])
        await _bot_app_ref.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"🧩 <b>Solve CAPTCHA (Mini App)</b>\n"
                "──────────────────────────\n"
                f"{reason}.\n\n"
                "Tekan tombol di bawah — CAPTCHA dari server VPS akan muncul. "
                "Selesaikan (centang / pilih gambar / Verify), lalu cookies "
                "otomatis diperbarui. Solve terjadi di IP VPS, jadi langsung berlaku."
            ),
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        print(f"[CaptchaWeb] Tombol Mini App dikirim ke admin ({reason}).")
        return True
    except Exception as e:
        _web_solve_active = False
        print(f"[CaptchaWeb] trigger gagal: {e}")
        return False

async def notify_captcha_needed():
    """Kirim notifikasi ke admin bahwa Google CAPTCHA perlu di-solve."""
    global _captcha_notified, _bot_app_ref
    if _captcha_notified or not ADMIN_CHAT_ID or not _bot_app_ref:
        return
    _captcha_notified = True

    # Jika Mini App dikonfigurasi, pakai solve jarak jauh (cocok untuk VPS headless)
    if _web_captcha_configured():
        ok = await trigger_web_captcha("Bot terkena CAPTCHA saat mengambil hasil Google")
        if ok:
            return  # tombol Mini App sudah dikirim; tidak perlu notifikasi lama

    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔗 Buka Google untuk Solve CAPTCHA",
                url="https://www.google.co.id/"
            )]
        ])
        await _bot_app_ref.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                "⚠️ <b>Google CAPTCHA Terdeteksi!</b>\n"
                "──────────────────────────\n"
                "Bot tidak bisa mengambil hasil Google karena terkena CAPTCHA.\n\n"
                "<b>Cara solve:</b>\n"
                "1. Klik tombol di bawah (beranda Google)\n"
                "2. Ketik pencarian apa saja secara manual\n"
                "3. Selesaikan CAPTCHA yang muncul sampai hasil tampil normal\n"
                "4. Ketik /solved di sini setelah selesai\n\n"
                "<i>Bot akan otomatis reload cookies setelah /solved.</i>"
            ),
            parse_mode="HTML",
            reply_markup=keyboard
        )
        print(f"[CAPTCHA] Notifikasi dikirim ke admin (chat_id: {ADMIN_CHAT_ID})")
    except Exception as e:
        print(f"[CAPTCHA] Gagal mengirim notifikasi: {e}")

# Pool 50 mobile User-Agents dari berbagai jenis perangkat
MOBILE_USER_AGENTS = [
    # Apple iPhone
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/114.0.5735.99 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/123.0 Mobile/15E148 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/122.0.2365.79 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_7_9 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.7.9 Mobile/15E148 Safari/604.1",
    
    # Apple iPad
    "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
    
    # Samsung Galaxy Series
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.105 Mobile Safari/537.36", # S24 Ultra
    "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.90 Mobile Safari/537.36",  # S24
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36", # S23 Ultra
    "Mozilla/5.0 (Linux; Android 13; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.163 Mobile Safari/537.36", # S23
    "Mozilla/5.0 (Linux; Android 12; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.111 Mobile Safari/537.36", # S22 Ultra
    "Mozilla/5.0 (Linux; Android 13; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.164 Mobile Safari/537.36", # A54 5G
    "Mozilla/5.0 (Linux; Android 13; SM-A346B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.210 Mobile Safari/537.36", # A34 5G
    "Mozilla/5.0 (Linux; Android 12; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.5938.140 Mobile Safari/537.36", # S21 Ultra
    "Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.5790.138 Mobile Safari/537.36", # S21
    "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.5735.196 Mobile Safari/537.36", # S10
    "Mozilla/5.0 (Linux; Android 13; SM-F946B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36", # Z Fold5
    "Mozilla/5.0 (Linux; Android 13; SM-F731B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.210 Mobile Safari/537.36", # Z Flip5
    
    # Google Pixel Series
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.105 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.89 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.210 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.193 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Pixel 6 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.80 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.5938.153 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.5790.166 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel Fold) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.143 Mobile Safari/537.36",
    
    # Xiaomi / Redmi / POCO
    "Mozilla/5.0 (Linux; Android 13; Xiaomi 13 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.105 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Mi 11 Ultra) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Redmi Note 11 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.163 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; POCO F5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.143 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; Redmi Note 10 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.5845.163 Mobile Safari/537.36",
    
    # OnePlus Series
    "Mozilla/5.0 (Linux; Android 14; OnePlus 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.105 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; OnePlus 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.210 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; OnePlus 10 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.111 Mobile Safari/537.36",
    
    # Oppo & Vivo & Realme
    "Mozilla/5.0 (Linux; Android 13; CPH2521) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.178 Mobile Safari/537.36", # Oppo Find X6 Pro
    "Mozilla/5.0 (Linux; Android 13; CPH2437) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36", # Oppo Reno8 T
    "Mozilla/5.0 (Linux; Android 14; V2303A) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.105 Mobile Safari/537.36", # Vivo X100 Pro
    "Mozilla/5.0 (Linux; Android 13; V2231A) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.210 Mobile Safari/537.36", # Vivo X90
    "Mozilla/5.0 (Linux; Android 13; RMX3701) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.164 Mobile Safari/537.36", # Realme GT3
    
    # Huawei & Honor
    "Mozilla/5.0 (Linux; Android 12; MNA-AL00) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.193 Mobile Safari/537.36", # Huawei P60 Pro
    "Mozilla/5.0 (Linux; Android 10; NOH-NX9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.5790.166 Mobile Safari/537.36",  # Huawei Mate 40 Pro
    "Mozilla/5.0 (Linux; Android 13; ADY-LX9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.143 Mobile Safari/537.36", # Honor 90
    
    # Sony Xperia, Motorola, Asus ROG
    "Mozilla/5.0 (Linux; Android 13; Xperia 1 V) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.178 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Motorola Edge 40) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; ASUS_AI2205) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.90 Mobile Safari/537.36"   # ROG Phone 7
]

DEVICE_UA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "device_ua.txt")

def get_stable_ua():
    """Kembalikan satu User-Agent yang KONSISTEN untuk profil ini.

    Merotasi UA tiap request membuat Google melihat 1 profil (cookies sama)
    memakai puluhan perangkat berbeda -> sinyal bot yang kuat & memicu CAPTCHA.
    UA dipilih sekali lalu disimpan ke device_ua.txt agar identitas perangkat
    tetap stabil. Hapus file itu untuk memilih ulang perangkat.
    Jika STABLE_DEVICE=False, kembali ke perilaku acak lama.
    """
    if not STABLE_DEVICE:
        return random.choice(MOBILE_USER_AGENTS)
    try:
        if os.path.exists(DEVICE_UA_FILE):
            with open(DEVICE_UA_FILE, "r", encoding="utf-8") as f:
                ua = f.read().strip()
                if ua:
                    return ua
    except Exception:
        pass
    ua = random.choice(MOBILE_USER_AGENTS)
    try:
        with open(DEVICE_UA_FILE, "w", encoding="utf-8") as f:
            f.write(ua)
        print(f"[Device] Perangkat tetap dipilih untuk profil ini: {ua}")
    except Exception:
        pass
    return ua


def detect_link_type(url):
    if not url:
        return "biasa"
    parsed = urlparse(url)
    path = parsed.path.lower()
    netloc = parsed.netloc.lower()
    if "/amp/" in path or netloc.startswith("amp.") or "google.com/amp/" in url:
        return "amp"
    tracking_params = ['utm_source', 'utm_medium', 'utm_campaign', 'fbclid', 'gclid', 'dclid', 'msclkid', 'gclsrc']
    if parsed.query:
        for param in tracking_params:
            if param in parsed.query.lower():
                return "landing"
    redirect_domains = ['ad.doubleclick.net', 'go.skimresources.com', 'click.linksynergy.com', 'r.rdv.ninja', 'go.shopify.com']
    if netloc in redirect_domains:
        return "landing"
    return "biasa"


def get_domain(url):
    if not url:
        return "?"
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    return domain if domain else "?"


def clean_google_title(a_element, url, domain):
    # 1. Cari element heading internal (h3 atau role="heading")
    h3 = a_element.find('h3')
    if h3:
        t = h3.get_text(strip=True)
        if t:
            return t
            
    heading = a_element.find(attrs={"role": "heading"})
    if heading:
        t = heading.get_text(strip=True)
        if t:
            return t
            
    # 2. Fallback: Bersihkan teks mentah secara cerdas dari domain/URL breadcrumbs
    text = a_element.get_text(strip=True)
    
    if domain and text.lower().startswith(domain.lower()):
        text = text[len(domain):].strip()
        
    if url and text.lower().startswith(url.lower()):
        text = text[len(url):].strip()
        
    url_no_proto = url.replace("https://", "").replace("http://", "")
    if url_no_proto and text.lower().startswith(url_no_proto.lower()):
        text = text[len(url_no_proto):].strip()
        
    return text if text else "Tanpa Judul"


def is_url_amp_format(url):
    try:
        url_lower = url.lower()
        parsed = urlparse(url_lower)
        path = parsed.path
        query = parsed.query
        netloc = parsed.netloc
        
        # 1. Subdomain 'amp.' atau segmen path '/amp/', '/amp', '.amp'
        if netloc.startswith("amp.") or "/amp/" in path or path.endswith("/amp") or path.endswith(".amp"):
            return True
        # 2. Query param seperti ?amp, ?amp=1, ?format=amp, atau &amp
        if "amp=" in query or query == "amp" or "&amp" in query or "format=amp" in query:
            return True
        return False
    except Exception:
        return False


def is_indonesian_block_page(url, original_domain):
    try:
        url_lower = url.lower()
        parsed = urlparse(url_lower)
        netloc = parsed.netloc
        path = parsed.path
        
        # 1. Kata kunci standar internet positif
        standard_block_keywords = [
            "internetpositif", "internet-positif", "mercusuar", 
            "trustpositif", "trust-positif", "nawala", "menkominfo"
        ]
        for kw in standard_block_keywords:
            if kw in url_lower:
                return True
                
        # 2. Deteksi decoy page Telkomsel / Indihome (.web.id)
        original_domain_lower = original_domain.lower().replace("www.", "")
        final_domain_lower = netloc.replace("www.", "")
        
        if final_domain_lower != original_domain_lower:
            # Jika dialihkan ke domain .web.id
            if final_domain_lower.endswith(".web.id"):
                decoy_patterns = ["parfum", "sehat", "kerja", "lagu", "puisi", "rakyat", "sejarah", "kuliner", "wisata", "tebak", "baca", "info", "artikel"]
                for pat in decoy_patterns:
                    if pat in final_domain_lower or pat in path:
                        return True
        return False
    except Exception:
        return False


def check_url_online_sync(url):
    # Cek format URL di awal secara lokal (instan)
    is_amp = is_url_amp_format(url)
    original_domain = get_domain(url)
    linked_domain = None
    # Domain CDN/aset/infrastruktur yang tidak relevan untuk pendeteksian brand
    SKIP_DOMAINS = {
        "fonts.googleapis.com", "fonts.gstatic.com", "googleapis.com", "gstatic.com",
        "challenges.cloudflare.com", "cloudflare.com", "cdn.ampproject.org",
        "jquery.com", "bootstrapcdn.com", "cdnjs.cloudflare.com",
        "izin-join.xyz", "fb.com", "facebook.com", "twitter.com",
        "instagram.com", "whatsapp.com", "t.me", "bit.ly", "tinyurl.com",
    }
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        with requests.get(url, headers=headers, timeout=4.0, stream=True, allow_redirects=True) as res:
            if res.status_code >= 400:
                return False, is_amp, res.url, linked_domain
                
            final_url = res.url
            # Deteksi pemblokiran ISP Indonesia
            if is_indonesian_block_page(final_url, original_domain):
                return False, False, final_url, linked_domain
                
            final_url_lower = final_url.lower()
            # Cek ulang format URL di url tujuan akhir (jika ada pengalihan)
            if is_url_amp_format(final_url_lower):
                is_amp = True
                
            # Baca hingga 100KB pertama teks konten HTML
            html_chunk = ""
            for chunk in res.iter_content(chunk_size=4096, decode_unicode=True):
                if chunk:
                    html_chunk += chunk
                if len(html_chunk) > 100000:
                    break
                    
            html_lower = html_chunk.lower()
            
            is_amp_itself = bool(re.search(r'<html[^>]*\s(amp|⚡|\u26a1)[>\s]', html_lower))
            has_amp_link = "amphtml" in html_lower or "rel=\"amphtml\"" in html_lower or "rel='amphtml'" in html_lower
            
            if is_amp_itself or has_amp_link:
                is_amp = True
            
            # Ekstrak semua href link eksternal dari halaman (tombol login/daftar/join)
            # Gunakan original html_chunk (case-preserved) untuk ekstrak URL
            hrefs = re.findall(r'href=["\']([^"\']+)["\']', html_chunk, re.I)
            orig_dom_clean = original_domain.lower().replace("www.", "")
            linked_domains = []
            for href in hrefs:
                if not href.startswith("http"):
                    continue
                href_domain = get_domain(href).lower().replace("www.", "")
                # Ambil domain eksternal yang bukan domain scan itu sendiri dan bukan CDN/aset
                if (
                    href_domain
                    and href_domain != orig_dom_clean
                    and len(href_domain) > 3
                    and href_domain not in SKIP_DOMAINS
                    and not any(skip in href_domain for skip in ["googleapis", "gstatic", "cloudflare", "ampproject"])
                    and href_domain not in linked_domains
                ):
                    linked_domains.append(href_domain)
            # Simpan semua domain yang ditemukan sebagai string dipisahkan koma
            linked_domain = ",".join(linked_domains) if linked_domains else None
                
            return True, is_amp, final_url, linked_domain
    except Exception:
        # Jika gagal request tetapi format URL secara fisik mengandung AMP, tetap laporkan is_amp = True
        return False, is_amp, url, linked_domain


async def check_url_online_async(url):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, check_url_online_sync, url)


COOKIES_JSON_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_cookies.json")

def _sanitize_cookie(c):
    """Rapikan cookie agar selalu valid untuk Playwright add_cookies."""
    expires = c.get("expires")
    try:
        expires = float(expires) if expires is not None else -1
    except (ValueError, TypeError):
        expires = -1
    same_site = c.get("sameSite")
    if same_site not in ("Strict", "Lax", "None"):
        same_site = "Lax"
    secure = bool(c.get("secure"))
    # SameSite=None WAJIB Secure=True; kalau tidak, browser membuang cookie.
    # Turunkan ke "Lax" agar cookie (mis. GOOGLE_ABUSE_EXEMPTION) tetap diterima.
    if same_site == "None" and not secure:
        same_site = "Lax"
    return {
        "name": c.get("name", ""),
        "value": c.get("value", ""),
        "domain": c.get("domain", ""),
        "path": c.get("path", "/") or "/",
        "expires": expires,
        "httpOnly": bool(c.get("httpOnly")),
        "secure": secure,
        "sameSite": same_site,
    }


def collect_google_cookies(profile_dir):
    """Ambil cookies Google terbaru secara otomatis setiap request.

    Menggabungkan cookies dari:
    1. google_cookies.json (portable, mis. untuk VPS) — dimuat DULU sebagai dasar
    2. firefox_profile/cookies.sqlite (hasil solve.py — berisi GOOGLE_ABUSE_EXEMPTION)
       dimuat BELAKANGAN sehingga MENANG bila ada duplikat. Profil live lebih tepercaya
       daripada JSON yang bisa basi/tidak lengkap (mis. tanpa cookie exemption).
    """
    merged = {}

    # 1. Dari google_cookies.json sebagai dasar (bisa basi/tidak lengkap)
    if os.path.exists(COOKIES_JSON_FILE):
        try:
            with open(COOKIES_JSON_FILE, "r", encoding="utf-8") as f:
                for c in json.load(f).get("cookies", []):
                    cookie = _sanitize_cookie(c)
                    if cookie["name"] and cookie["domain"]:
                        merged[(cookie["name"], cookie["domain"], cookie["path"])] = cookie
        except Exception as e:
            print(f"[Cookies] Gagal membaca {COOKIES_JSON_FILE}: {e}")

    # 2. Dari profil Firefox (dibaca ulang tiap request; MENANG atas JSON yang basi)
    try:
        from pathlib import Path
        from cookie_helper import get_google_cookies
        for c in get_google_cookies(Path(profile_dir)):
            cookie = _sanitize_cookie(c)
            if cookie["name"] and cookie["domain"]:
                merged[(cookie["name"], cookie["domain"], cookie["path"])] = cookie
    except Exception as e:
        print(f"[Cookies] Gagal membaca cookies dari firefox_profile: {e}")

    # Cerminkan GOOGLE_ABUSE_EXEMPTION yang masih valid ke KEDUA domain Google.
    # Google men-set cookie ini pada domain penyaji /sorry (biasanya .google.com),
    # padahal bot menavigasi google.co.id — cookie domain lain tak akan terkirim.
    # Token exemption terikat IP (validasi server-side), jadi aman disalin lintas domain.
    def _valid(c):
        exp = c.get("expires")
        try:
            return exp is None or float(exp) < 0 or float(exp) > time.time()
        except (ValueError, TypeError):
            return True

    valid_ex = next((c for c in merged.values()
                     if c["name"] == "GOOGLE_ABUSE_EXEMPTION" and _valid(c)), None)
    if valid_ex:
        for dom in (".google.com", ".google.co.id"):
            key = ("GOOGLE_ABUSE_EXEMPTION", dom, valid_ex.get("path", "/") or "/")
            existing = merged.get(key)
            if existing is None or not _valid(existing):
                clone = dict(valid_ex)
                clone["domain"] = dom
                merged[key] = clone
        print("[Cookies] GOOGLE_ABUSE_EXEMPTION valid dicerminkan ke .google.com & .google.co.id")

    return list(merged.values())


def save_google_cookies(all_cookies):
    """Simpan cookies Google terbaru dari sesi browser kembali ke google_cookies.json.

    HANYA dipanggil setelah pencarian benar-benar sukses (ada hasil), agar
    cookies dari sesi yang kena CAPTCHA/terblokir tidak menimpa cookies bagus
    hasil solver.
    """
    try:
        google_cookies = [
            _sanitize_cookie(c) for c in (all_cookies or [])
            if "google." in (c.get("domain") or "")
        ]
        if not google_cookies:
            return
        with open(COOKIES_JSON_FILE, "w", encoding="utf-8") as f:
            json.dump({"cookies": google_cookies, "origins": []}, f, indent=2, ensure_ascii=False)
        print(f"[Cookies] {len(google_cookies)} cookies Google terbaru otomatis disimpan ke google_cookies.json")
    except Exception as e:
        print(f"[Cookies] Gagal menyimpan cookies terbaru: {e}")


def get_normalized_proxies():
    """Menormalisasi PROXY agar kompatibel dengan requests (dict) dan ddgs (string)."""
    if not PROXY:
        return None, None
    if isinstance(PROXY, dict):
        requests_proxies = PROXY
        ddgs_proxy = PROXY.get("https") or PROXY.get("http") or list(PROXY.values())[0]
        return requests_proxies, ddgs_proxy
    if isinstance(PROXY, str):
        requests_proxies = {"http": PROXY, "https": PROXY}
        ddgs_proxy = PROXY
        return requests_proxies, ddgs_proxy
    return None, None


def _ddgs_fetch(keyword, ddgs_proxy):
    """Fungsi pembantu sinkron untuk mengambil data dari DDGS."""
    with DDGS(proxy=ddgs_proxy, timeout=20) as ddgs:
        return list(ddgs.text(
            keyword,
            region=REGION,
            backend=BACKENDS,
            max_results=10
        ))


async def get_top5(keyword):
    """Ambil Top 5 pencarian Google secara acak menggunakan Playwright (headless browser) dengan persistent context."""
    requests_proxies, ddgs_proxy = get_normalized_proxies()
    
    profile_dir = "./firefox_profile"
    if not os.path.exists(profile_dir):
        os.makedirs(profile_dir)
    
    # 1. Coba menggunakan Playwright untuk mengakses Google secara langsung
    # Coba hingga 3 kali dengan User-Agent berbeda dan IP proxy yang berotasi
    for attempt in range(1, 4):
        # Pakai satu perangkat KONSISTEN (bukan acak) agar tidak terlihat seperti
        # 1 profil memakai puluhan perangkat berbeda -> pemicu CAPTCHA.
        ua = get_stable_ua()
        
        playwright_proxy = None
        use_proxy_this_attempt = bool(ddgs_proxy and attempt < 3 and USE_PROXY_FOR_GOOGLE)
        if use_proxy_this_attempt:
            print(f"[Direct Search] Percobaan {attempt}/3 (Dengan Proxy): Menghubungi Google dengan perangkat: {ua}")
            try:
                parsed = urlparse(ddgs_proxy)
                server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
                playwright_proxy = {"server": server}
                if parsed.username and parsed.password:
                    playwright_proxy["username"] = parsed.username
                    playwright_proxy["password"] = parsed.password
            except Exception as pe:
                print(f"[Warning] Gagal memparsing proxy untuk Playwright: {pe}")
                playwright_proxy = None
        else:
            if not USE_PROXY_FOR_GOOGLE and ddgs_proxy:
                proxy_log_type = "IP Langsung (proxy Google dimatikan)"
            elif ddgs_proxy:
                proxy_log_type = "Tanpa Proxy (Penyelamat)"
            else:
                proxy_log_type = "Tanpa Proxy"
            print(f"[Direct Search] Percobaan {attempt}/3 ({proxy_log_type}): Menghubungi Google dengan perangkat: {ua}")

        # Selalu pakai profil utama (berisi cookies exemption hasil solve CAPTCHA)
        # dan injeksi cookies. INILAH yang memungkinkan browser headless lolos
        # CAPTCHA di IP rumah selama exemption dari solve.py masih berlaku
        # (tes membuktikan: tanpa cookie exemption, headless selalu kena CAPTCHA).
        active_profile_dir = profile_dir
        inject_cookies = True

        # Hapus file parent.lock jika ada sisa dari Windows/crash sebelumnya agar tidak crash di Linux/VPS
        lock_file = os.path.join(active_profile_dir, "parent.lock")
        if os.path.exists(lock_file):
            try:
                os.remove(lock_file)
            except Exception as e:
                print(f"[Warning] Gagal menghapus parent.lock sebelum launch: {e}")

        try:
            async with async_playwright() as p:
                # Gunakan launch_persistent_context agar sesi cookies tersimpan dan bisa dipakai kembali
                context = await p.firefox.launch_persistent_context(
                    user_data_dir=active_profile_dir,
                    headless=HEADLESS_BROWSER,
                    proxy=playwright_proxy,
                    user_agent=ua,
                    viewport={"width": 375, "height": 667},
                    is_mobile=True,
                    locale="id-ID"
                )
                
                page = context.pages[0] if context.pages else await context.new_page()
                # Terapkan stealth agar tidak terdeteksi headless
                await Stealth().apply_stealth_async(page)
                
                # Ambil cookies Google terbaru secara OTOMATIS setiap request
                # (gabungan firefox_profile/cookies.sqlite + google_cookies.json).
                # Untuk percobaan tanpa-proxy (IP rumah bersih), injeksi dilewati.
                cookies = collect_google_cookies(profile_dir) if inject_cookies else []
                if cookies:
                    try:
                        await context.add_cookies(cookies)
                        print(f"[Direct Search] Otomatis menginjeksi {len(cookies)} cookies Google terbaru")
                    except Exception as ce:
                        # Jika gagal batch, injeksi satu per satu agar cookie rusak tidak menggagalkan semua
                        injected = 0
                        for c in cookies:
                            try:
                                await context.add_cookies([c])
                                injected += 1
                            except Exception:
                                pass
                        print(f"[Direct Search] Injeksi parsial: {injected}/{len(cookies)} cookies berhasil ({ce})")
                
                # JANGAN buka URL /search langsung — Google langsung melempar ke
                # /sorry/index. Buka BERANDA dulu, lalu ketik keyword seperti manusia.
                await page.goto("https://www.google.co.id/", wait_until="domcontentloaded", timeout=20000)

                # Tangani halaman consent/persetujuan cookie jika muncul
                if "consent.google" in page.url:
                    for sel in [
                        "button:has-text('Terima semua')",
                        "button:has-text('Accept all')",
                        "button:has-text('Setuju')",
                        "button[aria-label*='Accept']",
                        "form[action*='consent'] button",
                    ]:
                        try:
                            btn = await page.query_selector(sel)
                            if btn:
                                await btn.click()
                                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                                break
                        except Exception:
                            pass

                # Jika beranda saja sudah kena blokir CAPTCHA
                if "sorry/index" in page.url:
                    print(f"[WARNING] Percobaan {attempt} terdeteksi CAPTCHA Google di beranda!")
                    await notify_captcha_needed()
                    await context.close()
                    await asyncio.sleep(random.uniform(1.0, 2.5))
                    continue

                # Ketik keyword di kolom pencarian secara manusiawi lalu tekan Enter
                search_box = None
                for sel in ["textarea[name='q']", "input[name='q']"]:
                    try:
                        search_box = await page.wait_for_selector(sel, timeout=5000)
                        if search_box:
                            break
                    except Exception:
                        search_box = None

                if search_box:
                    await search_box.click()
                    await page.wait_for_timeout(random.uniform(200, 500))
                    # Ketik per karakter dengan jeda acak agar mirip pengetikan manusia
                    await search_box.type(keyword, delay=random.uniform(90, 190))
                    await page.wait_for_timeout(random.uniform(300, 800))
                    await search_box.press("Enter")
                    # Pastikan Enter benar-benar men-submit (URL pindah ke /search)
                    submitted = True
                    try:
                        await page.wait_for_url("**/search**", timeout=15000)
                    except Exception:
                        submitted = False
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    if not submitted and "/search" not in page.url:
                        # Enter tidak submit — fallback klik tombol cari atau URL langsung
                        print(f"[INFO] Percobaan {attempt}: Enter tidak men-submit, memakai URL langsung.")
                        try:
                            await page.goto(f"https://www.google.co.id/search?q={keyword}",
                                            wait_until="domcontentloaded", timeout=20000)
                        except Exception:
                            pass
                else:
                    # Fallback terakhir jika kolom pencarian tidak ketemu
                    print(f"[INFO] Percobaan {attempt}: kolom pencarian tidak ditemukan, memakai URL langsung.")
                    await page.goto(f"https://www.google.co.id/search?q={keyword}",
                                    wait_until="domcontentloaded", timeout=20000)

                # Pastikan tidak diarahkan ke halaman retry/enablejs atau sorry/index
                current_url = page.url
                if "sorry/index" in current_url:
                    print(f"[WARNING] Percobaan {attempt} terdeteksi CAPTCHA Google! Silakan jalankan 'python solve.py' jika masalah berlanjut.")
                    await notify_captcha_needed()
                    await context.close()
                    await asyncio.sleep(random.uniform(1.0, 2.5))
                    continue
                elif "enablejs" in current_url:
                    print(f"[WARNING] Percobaan {attempt} terdeteksi redirect JS challenge (enablejs) oleh Google.")
                    await context.close()
                    await asyncio.sleep(random.uniform(1.0, 2.5))
                    continue
                
                # Tunggu me-render hasil pencarian beberapa detik
                await page.wait_for_timeout(2000)
                
                html_content = await page.content()

                # Ambil snapshot cookies sesi ini — baru DISIMPAN nanti jika pencarian sukses
                try:
                    session_cookies = await context.cookies()
                except Exception:
                    session_cookies = []

                await context.close()
                
            soup = BeautifulSoup(html_content, 'html.parser')
            
            top5 = []
            # Di browser nyata, Google mengembalikan link langsung (href="https://target.com/...")
            # Cari link hasil penelusuran yang valid (non-Google, non-Youtube, dll.)
            for a in soup.find_all('a', href=True):
                href = a['href']

                # Google sering membungkus link hasil dalam redirect: /url?q=<target>&...
                # Link seperti ini diawali "/url", bukan "http", jadi harus diurai dulu
                # agar tidak terbuang oleh filter di bawah (penyebab 0 hasil).
                if href.startswith('/url?') or href.startswith('/url;'):
                    try:
                        real = parse_qs(urlparse(href).query).get('q', [None])[0]
                        if real and real.startswith('http'):
                            href = real
                    except Exception:
                        pass

                if href.startswith('http') and 'google.' not in href and 'youtube.com' not in href and 'support.google.com' not in href and 'gstatic.com' not in href:
                    domain = get_domain(href)
                    title = clean_google_title(a, href, domain)
                    top5.append({
                        "title": title,
                        "url": href,
                        "type": detect_link_type(href),
                        "domain": domain
                    })
                    if len(top5) >= 5:
                        break
                        
            if len(top5) >= 3:
                print(f"[Success] Berhasil mengambil {len(top5)} link secara langsung dari Google pada percobaan {attempt}.")
                # Pencarian sukses — sekarang aman menyimpan cookies terbaru sesi ini
                save_google_cookies(session_cookies)
                # Cek status online secara paralel
                status_tasks = [check_url_online_async(r["url"]) for r in top5]
                statuses = await asyncio.gather(*status_tasks)
                for r, status in zip(top5, statuses):
                    if isinstance(status, tuple) and len(status) == 4:
                        is_online, is_amp, final_url, linked_domain = status
                    elif isinstance(status, tuple) and len(status) == 3:
                        is_online, is_amp, final_url = status
                        linked_domain = None
                    else:
                        is_online, is_amp, final_url, linked_domain = status, False, r["url"], None
                    r["is_online"] = is_online
                    r["is_amp"] = is_amp or (r.get("type") == "amp")
                    r["final_url"] = final_url if final_url else r["url"]
                    r["final_domain"] = get_domain(r["final_url"])
                    r["linked_domain"] = linked_domain or ""
                return top5, "Google"
            else:
                print(f"[INFO] Percobaan {attempt}: Jumlah link hasil pencarian langsung kurang ({len(top5)}) atau terblokir.")
                # === DIAGNOSTIK: cari tahu kenapa 0 hasil ===
                try:
                    title_txt = soup.title.get_text(strip=True) if soup.title else "(tanpa title)"
                    total_a = len(soup.find_all('a', href=True))
                    on_search = "/search" in current_url
                    print(f"[DEBUG] URL akhir : {current_url}")
                    print(f"[DEBUG] Title     : {title_txt}")
                    print(f"[DEBUG] Di /search: {on_search} | total <a>: {total_a} | panjang HTML: {len(html_content)}")
                    if not on_search:
                        print("[DEBUG] -> Belum sampai halaman hasil (kemungkinan masih beranda / pencarian tidak ter-submit).")
                    elif total_a < 5:
                        print("[DEBUG] -> Di /search tapi link sangat sedikit (kemungkinan halaman blokir/consent).")
                    else:
                        print("[DEBUG] -> Di /search & banyak link, tapi tak lolos filter (struktur DOM berubah).")
                    debug_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_last_attempt.html")
                    with open(debug_file, "w", encoding="utf-8") as df:
                        df.write(html_content)
                    print(f"[DEBUG] HTML halaman terakhir disimpan ke: {debug_file}")
                except Exception as de:
                    print(f"[DEBUG] Gagal menulis diagnostik: {de}")
                # Kemungkinan kena CAPTCHA invisible / halaman kosong Google
                if len(top5) == 0 and attempt == 3:
                    print("[WARNING] Semua percobaan Google gagal dengan 0 hasil — kemungkinan kena CAPTCHA!")
                    await notify_captcha_needed()
        except Exception as e:
            print(f"[Error] Gagal mengakses Google secara langsung pada percobaan {attempt}: {e}")
            
        # Tunggu sebentar sebelum mencoba lagi dengan User-Agent / IP baru
        await asyncio.sleep(random.uniform(1.0, 2.5))

    # 2. Fallback: Menggunakan Metasearch DDGS jika direct Google diblokir
    print("[Fallback] Mengalihkan pencarian ke metasearch node (Bing, Brave, DuckDuckGo)...")
    raw = None
    used_proxy = True
    try:
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, _ddgs_fetch, keyword, ddgs_proxy)
    except Exception as e:
        print(f"[Warning] Fallback metasearch dengan proxy gagal: {e}. Mencoba tanpa proxy...")
        try:
            loop = asyncio.get_running_loop()
            raw = await loop.run_in_executor(None, _ddgs_fetch, keyword, None)
            used_proxy = False
        except Exception as e2:
            print(f"[Error] Fallback metasearch tanpa proxy juga gagal: {e2}")
            return [], None

    if not raw:
        return [], None

    try:
        top5 = []
        for item in raw:
            url = item.get("href", "") or ""
            if not url:
                continue
            top5.append({
                "title": item.get("title", "") or "Tanpa Judul",
                "url": url,
                "type": detect_link_type(url),
                "domain": get_domain(url),
            })
            if len(top5) >= 5:
                break
        # Cek status online secara paralel untuk fallback
        status_tasks = [check_url_online_async(r["url"]) for r in top5]
        statuses = await asyncio.gather(*status_tasks)
        for r, status in zip(top5, statuses):
            if isinstance(status, tuple) and len(status) == 4:
                is_online, is_amp, final_url, linked_domain = status
            elif isinstance(status, tuple) and len(status) == 3:
                is_online, is_amp, final_url = status
                linked_domain = None
            else:
                is_online, is_amp, final_url, linked_domain = status, False, r["url"], None
            r["is_online"] = is_online
            r["is_amp"] = is_amp or (r.get("type") == "amp")
            r["final_url"] = final_url if final_url else r["url"]
            r["final_domain"] = get_domain(r["final_url"])
            r["linked_domain"] = linked_domain or ""
        source_name = "Bing/Brave/DDG" if used_proxy else "Bing/Brave/DDG (Direct)"
        return top5, source_name
    except Exception as e:
        print(f"[Error] Gagal memproses hasil fallback metasearch: {e}")
        return [], None


def _signal_bar(ctr, width=10, cap=28):
    filled = min(width, max(1, round(ctr / cap * width)))
    return "█" * filled + "░" * (width - filled)


def build_cyberpunk_message(keyword, results, source):
    # Tampilan respon sederhana, bersih, dan sesuai dengan screenshot dari user
    lines = [
        f"🎯 <b>RANK CHECKER | {keyword.upper()}</b>",
        f"📡 <b>Source:</b> {source}",
        "──────────────────────",
        ""
    ]

    kw_clean = keyword.lower().replace(" ", "")

    for i, r in enumerate(results):
        pos = i + 1
        url = html.escape(r["url"], quote=True)
        domain = html.escape(r["domain"])
        
        # 1. Emoji 1: ⚠️ (static warning)
        # 2. Emoji 2: ⚡ (AMP) atau ✖ (Non-AMP)
        amp_emoji = "⚡" if r.get("is_amp") else "✖"
        
        # Dapatkan domain tujuan akhir (redirect) jika ada
        final_domain = html.escape(r.get("final_domain", r["domain"]))
        final_url = html.escape(r.get("final_url", r["url"]), quote=True)
        
        orig_dom_clean = domain.lower().replace("www.", "")
        final_dom_clean = final_domain.lower().replace("www.", "")
        linked_domain_clean = r.get("linked_domain", "") or ""
        
        # Cek kepemilikan: keyword brand harus muncul di domain tujuan redirect
        # ATAU di salah satu domain link/tombol yang ada di halaman tersebut
        linked_domain_match = any(kw_clean in d for d in linked_domain_clean.split(",") if d)
        is_ours = (kw_clean in final_dom_clean) or linked_domain_match
        
        # 3. Emoji 3: ⭐ jika milik sendiri, 🔴 jika milik kompetitor/luar
        circle_emoji = "⭐" if is_ours else "🔴"
        
        # 4. Emoji 4: ✅ (Online/Unblocked) atau ❌ (Offline/Blocked)
        status_emoji = "✅" if r.get("is_online", True) else "❌"
        
        if orig_dom_clean == final_dom_clean:
            domain_display = f"<a href=\"{url}\">{domain}</a>"
        else:
            domain_display = f"<a href=\"{url}\">{domain}</a> ➔ <a href=\"{final_url}\">{final_domain}</a>"
        
        lines.append(f"{pos}. ⚠️{amp_emoji}{circle_emoji}{status_emoji} {domain_display}")

    return "\n".join(lines)


KEYWORDS_FILE = "keywords.json"

def load_keywords_data():
    default_structure = {"users": {}}
    if not os.path.exists(KEYWORDS_FILE):
        return default_structure
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
            # Migrasi data format lama (single user) ke format baru (multi-user)
            if "users" not in data:
                print("[Migration] Mendeteksi database format lama. Melakukan migrasi ke format multi-user...")
                chat_id = data.get("chat_id")
                keywords = data.get("keywords", [])
                next_index = data.get("next_index", 0)
                
                data = {"users": {}}
                if chat_id and keywords:
                    data["users"][str(chat_id)] = {
                        "keywords": keywords,
                        "next_index": next_index
                    }
            
            # Self-healing database untuk masing-masing user dari kata kunci gabungan
            changed = False
            for user_id_str, user_data in data.get("users", {}).items():
                keywords = user_data.get("keywords", [])
                cleaned_keywords = []
                user_changed = False
                for kw in keywords:
                    if len(kw) > 50 and (" " in kw or "\n" in kw or "\r" in kw):
                        normalized = kw.replace("\n", " ").replace("\r", " ").replace(",", " ")
                        parts = [p.strip() for p in normalized.split(" ") if p.strip()]
                        cleaned_keywords.extend(parts)
                        user_changed = True
                        changed = True
                    else:
                        cleaned_keywords.append(kw)
                if user_changed:
                    user_data["keywords"] = cleaned_keywords
                    
            if changed or "users" not in data or not os.path.exists(KEYWORDS_FILE):
                try:
                    with open(KEYWORDS_FILE, "w", encoding="utf-8") as f_out:
                        json.dump(data, f_out, indent=4, ensure_ascii=False)
                    print("[Self-Healing] Database berhasil dirapikan otomatis dari kata kunci gabungan.")
                except Exception as ex:
                    print(f"[Warning] Gagal menyimpan database hasil self-healing: {ex}")
                    
            return data
    except Exception as e:
        print(f"[Error] Gagal membaca {KEYWORDS_FILE}: {e}")
        return default_structure

def save_keywords_data(data):
    try:
        with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[Error] Gagal menulis ke {KEYWORDS_FILE}: {e}")

async def cron_job(application):
    print("[Cron] Penjadwal pengecekan otomatis berkala (30 menit) aktif (memindai SEMUA kata kunci setiap interval).")
    while True:
        # Tunggu 30 menit (1800 detik)
        await asyncio.sleep(1800)
        
        data = load_keywords_data()
        users_dict = data.get("users", {})
        
        if not users_dict:
            print("[Cron] Pengecekan otomatis dilewati: tidak ada user terdaftar.")
            continue
            
        print("[Cron] Memulai pengecekan berkala untuk semua kata kunci...")
        
        for chat_id_str, user_data in list(users_dict.items()):
            try:
                chat_id = int(chat_id_str)
            except ValueError:
                continue
                
            keywords = user_data.get("keywords", [])
            if not keywords:
                continue
                
            print(f"[Cron] User {chat_id}: Memindai {len(keywords)} kata kunci...")
            for i, kw in enumerate(keywords):
                print(f"[Cron] User {chat_id}: Memindai ({i+1}/{len(keywords)}): {kw}")
                results, source = await get_top5(kw)
                if results:
                    msg = build_cyberpunk_message(kw, results, source)
                    try:
                        await application.bot.send_message(
                            chat_id=chat_id,
                            text=msg,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                    except Exception as ex:
                        print(f"[Cron] Gagal mengirim pesan ke user {chat_id} untuk {kw}: {ex}")
                else:
                    print(f"[Cron] Gagal memindai {kw} pada pengecekan otomatis berkala.")
                
                # Jeda antar kata kunci agar laju tidak seperti bot (kurangi CAPTCHA)
                await asyncio.sleep(random.uniform(SCAN_DELAY_MIN, SCAN_DELAY_MAX))

async def exemption_monitor(application):
    """Pantau masa berlaku exemption; picu solve proaktif sebelum habis."""
    if not _web_captcha_configured() or EXEMPTION_REFRESH_MIN <= 0:
        return
    print(f"[CaptchaWeb] Monitor exemption aktif (refresh proaktif < {EXEMPTION_REFRESH_MIN} menit).")
    while True:
        await asyncio.sleep(120)  # cek tiap 2 menit
        try:
            left = get_exemption_seconds_left()
            # Picu hanya bila: ada exemption yang MAU habis (bukan yang sudah tidak ada),
            # tidak ada sesi solve berjalan, dan belum ada notifikasi tertunda.
            if left is not None and left < EXEMPTION_REFRESH_MIN * 60 \
                    and not _web_solve_active and not _captcha_notified:
                print(f"[CaptchaWeb] Exemption sisa {int(left/60)} menit — memicu refresh proaktif.")
                await trigger_web_captcha(
                    f"Exemption tinggal ~{int(left/60)} menit — perbarui agar tidak putus")
        except Exception as e:
            print(f"[CaptchaWeb] monitor error: {e}")


async def post_init(application):
    global _bot_app_ref, _web_solver
    _bot_app_ref = application
    asyncio.create_task(cron_job(application))

    # Jalankan server relay Mini App + monitor exemption jika dikonfigurasi
    if _web_captcha_configured():
        try:
            import captcha_web
            _web_solver = captcha_web.CaptchaWebSolver(
                profile_dir="./firefox_profile",
                save_cookies_fn=save_google_cookies,
                on_solved=_on_web_solved,
                ua=get_stable_ua(),
            )
            await captcha_web.start_server(_web_solver, CAPTCHA_WEB_PORT)
            asyncio.create_task(exemption_monitor(application))
            print(f"[CaptchaWeb] Mini App siap. URL publik: {PUBLIC_BASE_URL}/solve")
        except Exception as e:
            print(f"[CaptchaWeb] Gagal memulai server Mini App: {e}")
    elif CAPTCHA_WEB_ENABLED:
        print("[CaptchaWeb] Mini App dinonaktifkan: PUBLIC_BASE_URL belum diisi (harus https://...).")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    print(f"[INFO] /start dari chat_id: {chat_id}")
    await update.message.reply_text(
        "🤖 <b>JEMBUT SCANNER — ONLINE</b>\n"
        "──────────────────────────────\n"
        "Kirim keyword untuk memindai Top 5 SERP secara instan.\n\n"
        "<b>Perintah Otomatis (30 Menit):</b>\n"
        "• <code>/add [keyword]</code> - Tambahkan keyword (bisa multi-line)\n"
        "• <code>/del [keyword]</code> - Hapus keyword (bisa multi-line)\n"
        "• <code>/list</code> - Tampilkan semua keyword terpantau Anda\n"
        "• <code>/clear</code> - Kosongkan semua daftar keyword terpantau Anda\n"
        "• <code>/scan</code> - Jalankan semua pemantau instan sekarang\n"
        "• <code>/menu</code> - Pilih 1 keyword untuk discan sekarang\n"
        "• <code>/solved</code> - Beritahu bot bahwa CAPTCHA Google sudah di-solve\n\n"
        f"<i>Chat ID Anda: <code>{chat_id}</code></i>",
        parse_mode="HTML"
    )

async def add_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text
    words = raw_text.split(None, 1)
    if len(words) < 2:
        return await update.message.reply_text("⚠️ Format salah. Contoh:\n<code>/add depobos</code>\n\natau tulis multi-line:\n<code>/add\ndepobos\nwdbos</code>", parse_mode="HTML")
        
    remaining = words[1].strip()
    
    # Deteksi jika ada baris baru (multi-line paste)
    if "\n" in remaining:
        candidates = [line.strip() for line in remaining.split("\n") if line.strip()]
    else:
        candidates = [remaining]
        
    data = load_keywords_data()
    chat_id = str(update.effective_chat.id)
    
    # Inisialisasi user jika belum ada di database
    if chat_id not in data["users"]:
        data["users"][chat_id] = {"keywords": [], "next_index": 0}
        
    user_keywords = data["users"][chat_id]["keywords"]
    
    added = []
    already_exists = []
    
    for kw in candidates:
        if kw.lower() in [k.lower() for k in user_keywords]:
            already_exists.append(kw)
        else:
            user_keywords.append(kw)
            added.append(kw)
            
    if added:
        save_keywords_data(data)
        
    msg_parts = []
    if added:
        msg_parts.append(f"✅ <b>Berhasil memantau {len(added)} keyword baru:</b>\n" + "\n".join([f"- <code>{html.escape(k)}</code>" for k in added]))
    if already_exists:
        msg_parts.append(
            f"🚫 <b>{len(already_exists)} keyword ditolak — sudah terdaftar di daftar Anda:</b>\n"
            + "\n".join([f"- <code>{html.escape(k)}</code>" for k in already_exists])
            + "\n\n<i>Hapus terlebih dahulu dengan /del jika ingin mengganti.</i>"
        )
        
    await update.message.reply_text("\n\n".join(msg_parts), parse_mode="HTML")

async def del_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text
    words = raw_text.split(None, 1)
    if len(words) < 2:
        return await update.message.reply_text("⚠️ Format salah. Contoh:\n<code>/del depobos</code>\n\natau tulis multi-line:\n<code>/del\ndepobos\nwdbos</code>", parse_mode="HTML")
        
    remaining = words[1].strip()
    
    # Deteksi jika ada baris baru
    if "\n" in remaining:
        candidates = [line.strip() for line in remaining.split("\n") if line.strip()]
    else:
        candidates = [remaining]
        
    data = load_keywords_data()
    chat_id = str(update.effective_chat.id)
    
    if chat_id not in data["users"] or not data["users"][chat_id]["keywords"]:
        return await update.message.reply_text("📭 Daftar keyword Anda kosong.", parse_mode="HTML")
        
    user_keywords = data["users"][chat_id]["keywords"]
    
    removed = []
    not_found = []
    
    for kw in candidates:
        found = None
        for k in user_keywords:
            if k.lower() == kw.lower():
                found = k
                break
        if found:
            user_keywords.remove(found)
            removed.append(found)
        else:
            not_found.append(kw)
            
    if removed:
        # Reset next_index jika out of bounds akibat penghapusan
        if data["users"][chat_id]["next_index"] >= len(user_keywords):
            data["users"][chat_id]["next_index"] = 0
        save_keywords_data(data)
        
    msg_parts = []
    if removed:
        msg_parts.append(f"🗑️ <b>Berhasil menghapus {len(removed)} keyword Anda:</b>\n" + "\n".join([f"- <code>{html.escape(k)}</code>" for k in removed]))
    if not_found:
        msg_parts.append(f"❌ <b>{len(not_found)} keyword tidak ditemukan:</b>\n" + "\n".join([f"- <code>{html.escape(k)}</code>" for k in not_found]))
        
    await update.message.reply_text("\n\n".join(msg_parts), parse_mode="HTML")

async def clear_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_keywords_data()
    chat_id = str(update.effective_chat.id)
    if chat_id in data["users"]:
        data["users"][chat_id]["keywords"] = []
        data["users"][chat_id]["next_index"] = 0
        save_keywords_data(data)
    await update.message.reply_text("🧹 <b>Daftar keyword Anda berhasil dikosongkan!</b>", parse_mode="HTML")

async def list_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_keywords_data()
    chat_id = str(update.effective_chat.id)
    keywords = []
    if chat_id in data["users"]:
        keywords = data["users"][chat_id].get("keywords", [])
        
    if not keywords:
        return await update.message.reply_text("📭 Daftar keyword Anda kosong. Tambahkan dengan <code>/add [keyword]</code>.", parse_mode="HTML")
        
    msg = "📋 <b>Daftar Keyword Terpantau Anda (30 Menit):</b>\n\n"
    for i, kw in enumerate(keywords):
        msg += f"{i+1}. <code>{html.escape(kw)}</code>\n"
    await update.message.reply_text(msg, parse_mode="HTML")

async def scan_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_keywords_data()
    chat_id = str(update.effective_chat.id)
    keywords = []
    if chat_id in data["users"]:
        keywords = data["users"][chat_id].get("keywords", [])
        
    if not keywords:
        return await update.message.reply_text("📭 Daftar keyword Anda kosong.", parse_mode="HTML")
        
    await update.message.reply_text(f"🚀 Memulai pemindaian instan untuk {len(keywords)} keyword Anda...", parse_mode="HTML")
    
    for kw in keywords:
        results, source = await get_top5(kw)
        if results:
            msg = build_cyberpunk_message(kw, results, source)
            await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
        else:
            await update.message.reply_text(f"❌ Gagal memindai keyword: <code>{html.escape(kw)}</code>", parse_mode="HTML")
        await asyncio.sleep(random.uniform(SCAN_DELAY_MIN, SCAN_DELAY_MAX))

async def cek_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.strip()
    if not keyword:
        return await update.message.reply_text("⚠️ Masukkan keyword.")

    await update.message.reply_text(
        "<pre>> init jembut_scanner…\n"
        f"> target locked: {html.escape(keyword[:20])}\n"
        "> pinging metasearch node ▓▓▓▒░░</pre>",
        parse_mode="HTML"
    )

    results, source = await get_top5(keyword)

    if not results:
        return await update.message.reply_text(
            "<pre>⛔ NO DATA · semua backend gagal/limit</pre>", parse_mode="HTML"
        )

    msg = build_cyberpunk_message(keyword, results, source)
    await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)


async def solved_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin konfirmasi CAPTCHA sudah di-solve, bot reload status dan memverifikasi cookies."""
    global _captcha_notified
    chat_id = str(update.effective_chat.id)
    
    # Hanya admin yang bisa akses
    if ADMIN_CHAT_ID and int(chat_id) != ADMIN_CHAT_ID:
        return await update.message.reply_text("⛔ Perintah ini hanya untuk admin.")
    
    await update.message.reply_text(
        "🔄 <b>Memproses pembaruan sesi cookies dari firefox_profile...</b>",
        parse_mode="HTML"
    )
    
    profile_dir = "./firefox_profile"
    lock_file = os.path.join(profile_dir, "parent.lock")
    
    # Hapus file parent.lock jika tersisa dari windows agar tidak crash di Linux
    removed_lock = False
    if os.path.exists(lock_file):
        try:
            os.remove(lock_file)
            removed_lock = True
        except Exception as e:
            print(f"[Warning] Gagal menghapus parent.lock: {e}")
            
    # Hitung jumlah cookies google aktif
    from pathlib import Path
    from cookie_helper import get_google_cookies
    
    cookies = get_google_cookies(Path(profile_dir))
    cookies_count = len(cookies)
    
    # Hitung jumlah cookies dari google_cookies.json
    json_cookies_count = 0
    json_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_cookies.json")
    if os.path.exists(json_file):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                json_data = json.load(f)
                json_cookies_count = len(json_data.get("cookies", []))
        except Exception:
            pass
            
    _captcha_notified = False  # Reset status notifikasi CAPTCHA
    
    status_msg = (
        "✅ <b>Sesi CAPTCHA Berhasil Direset!</b>\n"
        "──────────────────────────\n"
        f"• Status Lock File: {'🗑️ Dihapus' if removed_lock else '✔️ Bersih (Tidak ada lock)'}\n"
        f"• Firefox Profile Cookies: <b>{cookies_count}</b>\n"
        f"• JSON File Cookies: <b>{json_cookies_count}</b>\n\n"
        "Bot akan menggunakan cookies dari profil Firefox dan google_cookies.json pada pencarian berikutnya."
    )
    
    await update.message.reply_text(status_msg, parse_mode="HTML")



async def scan_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tampilkan daftar keyword sebagai tombol inline — pilih 1 untuk discan sekarang."""
    data = load_keywords_data()
    chat_id = str(update.effective_chat.id)
    keywords = []
    if chat_id in data["users"]:
        keywords = data["users"][chat_id].get("keywords", [])

    if not keywords:
        return await update.message.reply_text(
            "📭 Daftar keyword Anda kosong.\nTambahkan dengan <code>/add [keyword]</code>.",
            parse_mode="HTML"
        )

    # Buat tombol inline: 2 per baris, maks 50 tombol
    buttons = []
    row = []
    for i, kw in enumerate(keywords[:50]):
        row.append(InlineKeyboardButton(kw, callback_data=f"scan1:{kw}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(
        "🔍 <b>Pilih keyword yang ingin discan sekarang:</b>",
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback saat tombol keyword di /menu ditekan."""
    query = update.callback_query
    await query.answer()

    data_str = query.data or ""
    if not data_str.startswith("scan1:"):
        return

    keyword = data_str[len("scan1:"):].strip()
    if not keyword:
        return

    await query.edit_message_text(
        f"🔍 Memindai: <b>{html.escape(keyword)}</b>\n"
        "‣ pinging metasearch node ▓▓▓▒░░",
        parse_mode="HTML"
    )

    results, source = await get_top5(keyword)

    if not results:
        await query.edit_message_text(
            f"⛔ <b>Gagal memindai</b> <code>{html.escape(keyword)}</code>\n"
            "Semua backend gagal / Google limit.",
            parse_mode="HTML"
        )
        return

    msg = build_cyberpunk_message(keyword, results, source)
    # Hapus pesan loading, kirim hasil baru
    await query.edit_message_text(msg, parse_mode="HTML", disable_web_page_preview=True)


async def solveweb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Picu manual sesi solve CAPTCHA via Mini App."""
    chat_id = str(update.effective_chat.id)
    if ADMIN_CHAT_ID and int(chat_id) != ADMIN_CHAT_ID:
        return await update.message.reply_text("⛔ Perintah ini hanya untuk admin.")
    if not _web_captcha_configured():
        return await update.message.reply_text(
            "⚠️ Mini App belum aktif. Isi <code>PUBLIC_BASE_URL</code> (https://...) "
            "di rank.py dan pastikan <code>CAPTCHA_WEB_ENABLED = True</code>.",
            parse_mode="HTML")
    left = get_exemption_seconds_left()
    info = f"\nExemption saat ini sisa ~{int(left/60)} menit." if left else ""
    await update.message.reply_text(f"🧩 Membuka sesi solve CAPTCHA...{info}", parse_mode="HTML")
    ok = await trigger_web_captcha("Permintaan manual /solveweb")
    if not ok:
        await update.message.reply_text(
            "⚠️ Tidak bisa memulai sesi (mungkin sudah ada sesi berjalan). Coba lagi sebentar.")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_keyword))
    app.add_handler(CommandHandler("del", del_keyword))
    app.add_handler(CommandHandler("clear", clear_keywords))
    app.add_handler(CommandHandler("list", list_keywords))
    app.add_handler(CommandHandler("scan", scan_all))
    app.add_handler(CommandHandler("menu", scan_menu))
    app.add_handler(CommandHandler("solved", solved_captcha))
    app.add_handler(CommandHandler("solveweb", solveweb_command))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^scan1:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cek_keyword))
    print("Cyberpunk bot online…")
    app.run_polling()


if __name__ == "__main__":
    main()
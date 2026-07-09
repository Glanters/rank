import sys
import os
import json
import re
import html
import asyncio
import random
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs
import requests
# pyrefly: ignore [missing-import]
from bs4 import BeautifulSoup
# pyrefly: ignore [missing-import]
from ddgs import DDGS
# pyrefly: ignore [missing-import]
from telegram import Update
# pyrefly: ignore [missing-import]
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
# pyrefly: ignore [missing-import]
from playwright.async_api import async_playwright
# pyrefly: ignore [missing-import]
from playwright_stealth import Stealth

# Configure standard output to use UTF-8 to support emoji/special characters in Windows terminals
sys.stdout.reconfigure(encoding='utf-8')

# ==================== KONFIGURASI ====================
TELEGRAM_TOKEN = "8360476610:AAEqBzP2fLUS84LO4gdfwIcolx8PEneD7KQ"
LOCATION = "Jakarta, Indonesia"
TIMEZONE = timezone(timedelta(hours=7))   # GMT+7

# Backend metasearch (fallback):
BACKENDS = "google, bing, brave, duckduckgo"
REGION = "id-id"

# Opsional: pakai proxy residensial biar backend Google lebih sering tembus.
# Contoh: "socks5h://user:pass@host:port" atau "http://user:pass@host:port"
PROXY = {
    "http": "http://7LmoLRicjfmGcKj:XUdhrrU5YyGRG6r@178.93.21.231:48883",
    "https": "http://7LmoLRicjfmGcKj:XUdhrrU5YyGRG6r@178.93.21.231:48883"
}
# =====================================================

CTR = {1: 28, 2: 15, 3: 11, 4: 8, 5: 7}
TAG = {"amp": "[AMP]", "landing": "[LND]", "biasa": "[REG]"}
BAR_W = 30

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
        # Pilih User-Agent perangkat mobile secara acak untuk percobaan ini
        ua = random.choice(MOBILE_USER_AGENTS)
        print(f"[Direct Search] Percobaan {attempt}/3: Menghubungi Google dengan perangkat: {ua}")
        
        playwright_proxy = None
        if ddgs_proxy:
            # Playwright proxy format: {'server': 'http://...', 'username': '...', 'password': '...'}
            # Kita parsing proxy string: http://username:password@host:port
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
        
        try:
            async with async_playwright() as p:
                # Gunakan launch_persistent_context agar sesi cookies tersimpan dan bisa dipakai kembali
                context = await p.firefox.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=True,
                    proxy=playwright_proxy,
                    user_agent=ua,
                    viewport={"width": 375, "height": 667},
                    is_mobile=True,
                    locale="id-ID"
                )
                
                page = context.pages[0] if context.pages else await context.new_page()
                # Terapkan stealth agar tidak terdeteksi headless
                await Stealth().apply_stealth_async(page)
                
                # Buka google search (tanpa &num=50 untuk mengurangi resiko captcha)
                google_url = f"https://www.google.co.id/search?q={keyword}"
                await page.goto(google_url, wait_until="domcontentloaded", timeout=20000)
                
                # Pastikan tidak diarahkan ke halaman retry/enablejs atau sorry/index
                current_url = page.url
                if "sorry/index" in current_url:
                    print(f"[WARNING] Percobaan {attempt} terdeteksi CAPTCHA Google! Silakan jalankan 'python solve.py' jika masalah berlanjut.")
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
                await context.close()
                
            soup = BeautifulSoup(html_content, 'html.parser')
            
            top5 = []
            # Di browser nyata, Google mengembalikan link langsung (href="https://target.com/...")
            # Cari link hasil penelusuran yang valid (non-Google, non-Youtube, dll.)
            for a in soup.find_all('a', href=True):
                href = a['href']
                
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
        except Exception as e:
            print(f"[Error] Gagal mengakses Google secara langsung pada percobaan {attempt}: {e}")
            
        # Tunggu sebentar sebelum mencoba lagi dengan User-Agent / IP baru
        await asyncio.sleep(random.uniform(1.0, 2.5))

    # 2. Fallback: Menggunakan Metasearch DDGS jika direct Google diblokir
    print("[Fallback] Mengalihkan pencarian ke metasearch node (Bing, Brave, DuckDuckGo)...")
    try:
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, _ddgs_fetch, keyword, ddgs_proxy)
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
        return top5, "Bing/Brave/DDG"
    except Exception as e:
        print(f"[Error] Fallback metasearch juga gagal: {e}")
        return [], None


def _signal_bar(ctr, width=10, cap=28):
    filled = min(width, max(1, round(ctr / cap * width)))
    return "█" * filled + "░" * (width - filled)


def build_cyberpunk_message(keyword, results, source):
    # Tampilan respon sederhana, bersih, dan sesuai dengan screenshot dari user
    lines = [
        f"🎯 <b>RANK CHECKER | {keyword.upper()}</b>",
        "──────────────────────",
        f"Search Results: Found {len(results)}",
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
    print("[Cron] Penjadwal pengecekan otomatis berkala (30 menit) aktif (mode antrean 1-per-1 per user).")
    while True:
        # Tunggu 30 menit (1800 detik)
        await asyncio.sleep(1800)
        
        data = load_keywords_data()
        users_dict = data.get("users", {})
        
        if not users_dict:
            print("[Cron] Pengecekan otomatis dilewati: tidak ada user terdaftar.")
            continue
            
        print("[Cron] Memulai pengecekan berkala...")
        
        # Jalankan pengecekan untuk masing-masing user secara bergiliran 1 kata kunci
        for chat_id_str, user_data in list(users_dict.items()):
            try:
                chat_id = int(chat_id_str)
            except ValueError:
                continue
                
            keywords = user_data.get("keywords", [])
            if not keywords:
                continue
                
            next_index = user_data.get("next_index", 0)
            
            if next_index >= len(keywords):
                next_index = 0
                
            kw = keywords[next_index]
            print(f"[Cron] User {chat_id}: Memindai kata kunci ke-{next_index + 1}: {kw}")
            
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
                
            # Update index untuk pemindaian user ini berikutnya
            user_data["next_index"] = (next_index + 1) % len(keywords)
            
        save_keywords_data(data)

async def post_init(application):
    asyncio.create_task(cron_job(application))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 <b>JEMBUT SCANNER — ONLINE</b>\n"
        "──────────────────────────────\n"
        "Kirim keyword untuk memindai Top 5 SERP secara instan.\n\n"
        "<b>Perintah Otomatis (30 Menit):</b>\n"
        "• <code>/add [keyword]</code> - Tambahkan keyword (bisa multi-line)\n"
        "• <code>/del [keyword]</code> - Hapus keyword (bisa multi-line)\n"
        "• <code>/list</code> - Tampilkan semua keyword terpantau Anda\n"
        "• <code>/clear</code> - Kosongkan semua daftar keyword terpantau Anda\n"
        "• <code>/scan</code> - Jalankan semua pemantau instan sekarang",
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
        await asyncio.sleep(random.uniform(3.0, 5.0))

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


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_keyword))
    app.add_handler(CommandHandler("del", del_keyword))
    app.add_handler(CommandHandler("clear", clear_keywords))
    app.add_handler(CommandHandler("list", list_keywords))
    app.add_handler(CommandHandler("scan", scan_all))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cek_keyword))
    print("Cyberpunk bot online…")
    app.run_polling()


if __name__ == "__main__":
    main()
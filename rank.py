import sys
import os
import html
import asyncio
import random
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright
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
        return top5, "Bing/Brave/DDG"
    except Exception as e:
        print(f"[Error] Fallback metasearch juga gagal: {e}")
        return [], None


def _signal_bar(ctr, width=10, cap=28):
    filled = min(width, max(1, round(ctr / cap * width)))
    return "█" * filled + "░" * (width - filled)


def build_cyberpunk_message(keyword, results, source):
    now = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M")
    
    # Emas, perak, perunggu, dan biru untuk visualisasi rank
    rank_emojis = {1: "🥇", 2: "🥈", 3: "🥉", 4: "🔹", 5: "🔹"}
    
    lines = [
        "🤖 <b>JEMBUT SCANNER</b>",
        "⚡ <i>Stay in the Grid · Realtime Status</i>",
        "──────────────────────────────",
        f"🎯 <b>Target  :</b> <code>{html.escape(keyword)}</code>",
        f"📡 <b>Source  :</b> <code>{source if source else 'N/A'}</code>",
        f"📅 <b>Stamp   :</b> <code>{now}</code>",
        f"🔋 <b>Nodes   :</b> <code>{len(results)}/5 locked</code>",
        "──────────────────────────────",
        ""
    ]

    for i, r in enumerate(results):
        pos = i + 1
        ctr = CTR.get(pos, 5)
        tag = TAG.get(r["type"], "[REG]")
        sig = _signal_bar(ctr)
        title = html.escape(r["title"][:50]) # Mengizinkan judul lebih panjang
        url = html.escape(r["url"], quote=True)
        domain = html.escape(r["domain"][:30])
        
        emoji = rank_emojis.get(pos, "🔹")
        
        lines.append(f"{emoji} <b>RANK {pos:02d}</b>  ·  <code>{tag}</code>")
        lines.append(f"   <code>{sig}  {ctr}% est.CTR</code>")
        lines.append(f"   🔗 <a href=\"{url}\"><b>{title}</b></a>")
        lines.append(f"   🌐 <i>{domain}</i>")
        
        if pos < len(results):
            lines.append("──────────────────────────────")

    lines += [
        "",
        "💾 <b>Scan complete · System online</b>",
        "──────────────────────────────"
    ]
    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<pre>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓\n"
        " JEMBUT RANK — ONLINE\n"
        "▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</pre>\n"
        "Kirim keyword untuk memindai Top 5 SERP.\n"
        "Contoh: <code>wdbos</code>",
        parse_mode="HTML"
    )


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
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cek_keyword))
    print("Cyberpunk bot online…")
    app.run_polling()


if __name__ == "__main__":
    main()
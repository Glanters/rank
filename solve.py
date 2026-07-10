import asyncio
from playwright.async_api import async_playwright
import os
import sys
from urllib.parse import urlparse
from rank import PROXY, get_normalized_proxies

sys.stdout.reconfigure(encoding='utf-8')

async def main():
    profile_dir = "./firefox_profile"
    if not os.path.exists(profile_dir):
        os.makedirs(profile_dir)
        
    requests_proxies, ddgs_proxy = get_normalized_proxies()
    playwright_proxy = None
    if ddgs_proxy:
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
        
    async with async_playwright() as p:
        print("Membuka browser Firefox dengan PROXY untuk menyelesaikan CAPTCHA Google...")
        try:
            context = await p.firefox.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False,
                proxy=playwright_proxy,
                viewport={"width": 800, "height": 600}
            )
            page = context.pages[0] if context.pages else await context.new_page()
            
            # Buka BERANDA Google dulu (bukan URL pencarian langsung) agar tidak
            # langsung dilempar ke halaman blokir /sorry/index
            print("Membuka beranda Google...")
            await page.goto("https://www.google.co.id/", wait_until="domcontentloaded")

            print("\n=======================================================")
            print(" PETUNJUK:")
            print(" 1. Ketik pencarian secara MANUAL di kolom pencarian Google")
            print("    (contoh: wdbos) lalu tekan Enter di browser.")
            print(" 2. Jika muncul CAPTCHA, selesaikan centangnya sampai hasil")
            print("    pencarian tampil normal.")
            print(" 3. Setelah itu tutup jendela browser atau tekan Ctrl+C di sini.")
            print("=======================================================\n")
            
            # Keep browser open until closed or interrupted
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nMenutup browser dan menyimpan sesi...")
            try:
                await context.close()
            except:
                pass
            print("Sesi berhasil disimpan!")
        except Exception as e:
            err_msg = str(e)
            print(f"\nError: Sesi gagal dijalankan: {err_msg}", file=sys.stderr)
            if "displayName" in err_msg or "display" in err_msg or "X11" in err_msg or "Wayland" in err_msg:
                print("\n[Bantuan] Lingkungan Anda tidak mendukung GUI (Headless / VPS tanpa layar).\n"
                      "Silakan jalankan 'python solve.py' di PC lokal Anda (yang memiliki layar/GUI),\n"
                      "lalu upload seluruh folder 'firefox_profile' ke VPS Anda.", file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSelesai.")

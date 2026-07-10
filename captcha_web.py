"""Remote CAPTCHA solver via Telegram Mini App.

Alur:
1. Bot mendeteksi CAPTCHA Google (atau exemption mau habis).
2. Sesi browser DI VPS dibuka (headless), menuju halaman yang memicu CAPTCHA
   Google (/sorry) — sehingga tantangan muncul PADA IP VPS.
3. Screenshot halaman itu di-relay ke Telegram Mini App (via HTTP polling).
4. Tap/klik Anda di Mini App dikirim balik ke browser VPS (koordinat pecahan),
   sehingga solve BENAR-BENAR terjadi di sesi + IP VPS.
5. Begitu lolos (URL keluar dari /sorry & cookie GOOGLE_ABUSE_EXEMPTION muncul),
   cookies ditangkap, disimpan, dan sesi ditutup.

Server ini mendengarkan HTTP di localhost:PORT; taruh di belakang reverse proxy
(nginx/Caddy/Cloudflare Tunnel) yang menyediakan HTTPS untuk domain Anda —
Telegram Mini App WAJIB HTTPS.
"""

import os
import asyncio

from aiohttp import web
from playwright.async_api import async_playwright

try:
    from playwright_stealth import Stealth
    _HAS_STEALTH = True
except Exception:
    _HAS_STEALTH = False


class CaptchaWebSolver:
    """Kelola SATU sesi solve CAPTCHA aktif melalui browser Playwright."""

    def __init__(self, profile_dir, save_cookies_fn=None, on_solved=None,
                 ua=None, trigger_keyword="wdbos"):
        self.profile_dir = profile_dir
        self.save_cookies_fn = save_cookies_fn
        self.on_solved = on_solved
        self.ua = ua
        self.trigger_keyword = trigger_keyword

        self._pw = None
        self._context = None
        self._page = None
        self._lock = asyncio.Lock()
        self.state = "idle"          # idle | starting | solving | solved | error
        self.token = None            # token sesi (validasi akses Mini App)
        self.viewport = {"width": 400, "height": 820}

    # ---------- lifecycle ----------

    async def start(self, token):
        """Buka browser & picu CAPTCHA. Aman dipanggil ulang (menutup sesi lama)."""
        async with self._lock:
            await self._cleanup()
            self.token = token
            self.state = "starting"
            try:
                self._pw = await async_playwright().start()
                self._context = await self._pw.firefox.launch_persistent_context(
                    user_data_dir=self.profile_dir + "_solve",
                    headless=True,
                    user_agent=self.ua,
                    viewport=self.viewport,
                    is_mobile=True,
                    locale="id-ID",
                )
                self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
                if _HAS_STEALTH:
                    try:
                        await Stealth().apply_stealth_async(self._page)
                    except Exception:
                        pass
                # Picu CAPTCHA: langsung ke URL /search agar Google memunculkan /sorry
                url = f"https://www.google.co.id/search?q={self.trigger_keyword}"
                await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
                self.state = "solving"
                print("[CaptchaWeb] Sesi solve dimulai — menunggu Anda menyelesaikan CAPTCHA di Mini App.")
            except Exception as e:
                self.state = "error"
                print(f"[CaptchaWeb] Gagal memulai sesi: {e}")
                await self._cleanup()

    async def _cleanup(self):
        for closer in (
            lambda: self._context.close() if self._context else None,
            lambda: self._pw.stop() if self._pw else None,
        ):
            try:
                res = closer()
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass
        self._context = None
        self._page = None
        self._pw = None

    async def stop(self):
        async with self._lock:
            await self._cleanup()
            if self.state not in ("solved",):
                self.state = "idle"

    # ---------- interaksi ----------

    async def frame(self):
        """JPEG screenshot viewport saat ini (bytes) atau None."""
        if not self._page:
            return None
        try:
            return await self._page.screenshot(type="jpeg", quality=55)
        except Exception:
            return None

    async def tap(self, fx, fy):
        """Klik pada koordinat pecahan (0..1) relatif viewport."""
        if not self._page:
            return
        try:
            x = max(0.0, min(1.0, float(fx))) * self.viewport["width"]
            y = max(0.0, min(1.0, float(fy))) * self.viewport["height"]
            await self._page.mouse.click(x, y)
        except Exception as e:
            print(f"[CaptchaWeb] tap error: {e}")

    async def scroll(self, dy):
        if not self._page:
            return
        try:
            await self._page.mouse.wheel(0, float(dy))
        except Exception:
            pass

    async def reload(self):
        if not self._page:
            return
        try:
            await self._page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass

    async def check_solved(self):
        """Periksa apakah CAPTCHA sudah lolos; jika ya, tangkap & simpan cookies."""
        if self.state in ("solved", "idle", "error"):
            return self.state
        if not self._page or not self._context:
            return self.state
        try:
            url = self._page.url or ""
            cookies = await self._context.cookies()
            has_ex = any(c.get("name") == "GOOGLE_ABUSE_EXEMPTION" for c in cookies)
            if "sorry" not in url and has_ex:
                self.state = "solved"
                print("[CaptchaWeb] CAPTCHA lolos! Menangkap cookies exemption...")
                if self.save_cookies_fn:
                    try:
                        self.save_cookies_fn(cookies)
                    except Exception as e:
                        print(f"[CaptchaWeb] gagal simpan cookies: {e}")
                if self.on_solved:
                    try:
                        await self.on_solved()
                    except Exception as e:
                        print(f"[CaptchaWeb] on_solved error: {e}")
                await self._cleanup()
        except Exception as e:
            print(f"[CaptchaWeb] check_solved error: {e}")
        return self.state


# ==================== HTTP server (aiohttp) ====================

def _check_token(request):
    solver = request.app["solver"]
    tok = request.query.get("token") or (request.headers.get("X-Token"))
    return solver.token is not None and tok == solver.token


async def _h_page(request):
    if not _check_token(request):
        return web.Response(status=403, text="token tidak valid / sesi tidak aktif")
    return web.Response(text=MINIAPP_HTML, content_type="text/html")


async def _h_frame(request):
    if not _check_token(request):
        return web.Response(status=403, text="forbidden")
    data = await request.app["solver"].frame()
    if not data:
        return web.Response(status=204)
    return web.Response(body=data, content_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})


async def _h_tap(request):
    if not _check_token(request):
        return web.json_response({"ok": False}, status=403)
    body = await request.json()
    await request.app["solver"].tap(body.get("fx", 0), body.get("fy", 0))
    return web.json_response({"ok": True})


async def _h_scroll(request):
    if not _check_token(request):
        return web.json_response({"ok": False}, status=403)
    body = await request.json()
    await request.app["solver"].scroll(body.get("dy", 0))
    return web.json_response({"ok": True})


async def _h_reload(request):
    if not _check_token(request):
        return web.json_response({"ok": False}, status=403)
    await request.app["solver"].reload()
    return web.json_response({"ok": True})


async def _h_status(request):
    if not _check_token(request):
        return web.json_response({"state": "forbidden"}, status=403)
    state = await request.app["solver"].check_solved()
    return web.json_response({"state": state})


def build_app(solver):
    app = web.Application()
    app["solver"] = solver
    app.router.add_get("/solve", _h_page)
    app.router.add_get("/solve/frame", _h_frame)
    app.router.add_post("/solve/tap", _h_tap)
    app.router.add_post("/solve/scroll", _h_scroll)
    app.router.add_post("/solve/reload", _h_reload)
    app.router.add_get("/solve/status", _h_status)
    return app


async def start_server(solver, port, host="127.0.0.1"):
    """Jalankan server di dalam event loop yang sedang berjalan. Kembalikan runner.

    Default bind ke 127.0.0.1 (hanya reverse proxy di host yang sama yang bisa
    mengakses) demi keamanan. Ubah ke '0.0.0.0' hanya bila proxy di host lain.
    """
    app = build_app(solver)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"[CaptchaWeb] Server relay aktif di http://{host}:{port} (taruh di belakang HTTPS reverse proxy).")
    return runner


# ==================== Mini App HTML ====================

MINIAPP_HTML = r"""<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Solve CAPTCHA</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body { margin:0; font-family: system-ui, sans-serif; background:#111; color:#eee;
         display:flex; flex-direction:column; align-items:center; min-height:100vh; }
  #bar { width:100%; padding:8px 10px; background:#1b1b1b; display:flex; gap:8px;
         align-items:center; position:sticky; top:0; z-index:5; }
  #status { flex:1; font-size:13px; }
  button { background:#2b6cff; color:#fff; border:0; border-radius:8px; padding:8px 10px;
           font-size:13px; }
  #wrap { position:relative; width:100%; max-width:440px; margin-top:6px; touch-action:none; }
  #shot { width:100%; display:block; border-radius:8px; background:#000; user-select:none; }
  #hint { font-size:12px; color:#aaa; padding:8px 12px; text-align:center; line-height:1.5; }
  #done { display:none; padding:24px; text-align:center; font-size:16px; color:#31d07a; }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:#f5a623; margin-right:6px; }
</style>
</head>
<body>
  <div id="bar">
    <span id="status"><span class="dot"></span>Memuat CAPTCHA…</span>
    <button id="btnReload">Muat ulang</button>
  </div>
  <div id="wrap">
    <img id="shot" alt="captcha" draggable="false">
  </div>
  <div id="hint">
    Ketuk langsung pada CAPTCHA seperti di layar Google (centang kotak / pilih gambar,
    lalu tekan tombol Verify). Geser dengan menyeret bila perlu.
  </div>
  <div id="done">✅ CAPTCHA selesai! Cookies diperbarui. Anda bisa menutup halaman ini.</div>

<script>
(function(){
  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) { try { tg.ready(); tg.expand(); } catch(e){} }

  var qs = new URLSearchParams(location.search);
  var token = qs.get('token') || '';
  var img = document.getElementById('shot');
  var statusEl = document.getElementById('status');
  var doneEl = document.getElementById('done');
  var wrap = document.getElementById('wrap');
  var solved = false;

  function api(path, body){
    return fetch(path + '?token=' + encodeURIComponent(token), {
      method: body ? 'POST' : 'GET',
      headers: body ? {'Content-Type':'application/json'} : {},
      body: body ? JSON.stringify(body) : undefined
    });
  }

  // Ambil frame terbaru
  function pollFrame(){
    if (solved) return;
    fetch('/solve/frame?token=' + encodeURIComponent(token) + '&t=' + Date.now())
      .then(function(r){ if (r.status === 200) return r.blob(); return null; })
      .then(function(b){ if (b) img.src = URL.createObjectURL(b); })
      .catch(function(){});
  }

  // Kirim tap sebagai pecahan koordinat viewport
  function sendTap(clientX, clientY){
    var rect = img.getBoundingClientRect();
    var fx = (clientX - rect.left) / rect.width;
    var fy = (clientY - rect.top) / rect.height;
    if (fx < 0 || fx > 1 || fy < 0 || fy > 1) return;
    api('/solve/tap', {fx: fx, fy: fy});
  }

  img.addEventListener('click', function(ev){ sendTap(ev.clientX, ev.clientY); });
  img.addEventListener('touchend', function(ev){
    if (ev.changedTouches && ev.changedTouches.length){
      var t = ev.changedTouches[0];
      sendTap(t.clientX, t.clientY);
      ev.preventDefault();
    }
  }, {passive:false});

  document.getElementById('btnReload').addEventListener('click', function(){ api('/solve/reload', {}); });

  // Status polling
  function pollStatus(){
    if (solved) return;
    api('/solve/status').then(function(r){ return r.json(); }).then(function(j){
      if (j.state === 'solved'){
        solved = true;
        wrap.style.display = 'none';
        document.getElementById('hint').style.display = 'none';
        statusEl.innerHTML = 'Selesai';
        doneEl.style.display = 'block';
        if (tg) { try { tg.HapticFeedback.notificationOccurred('success'); } catch(e){} setTimeout(function(){ try{ tg.close(); }catch(e){} }, 2500); }
      } else if (j.state === 'solving' || j.state === 'starting'){
        statusEl.innerHTML = '<span class="dot"></span>Selesaikan CAPTCHA di atas';
      } else if (j.state === 'error'){
        statusEl.textContent = '⚠️ Sesi error — coba /solveweb lagi dari bot.';
      }
    }).catch(function(){});
  }

  setInterval(pollFrame, 900);
  setInterval(pollStatus, 1600);
  pollFrame();
})();
</script>
</body>
</html>
"""

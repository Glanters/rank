const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

// UA mobile yang selaras dengan bot (Chrome Android)
const MOBILE_UA = "Mozilla/5.0 (Linux; Android 13; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.164 Mobile Safari/537.36";

// Baca URL proxy dari konfigurasi rank.py
function getProxyFromRankPy() {
    try {
        const rankPyPath = path.join(__dirname, 'rank.py');
        if (fs.existsSync(rankPyPath)) {
            const content = fs.readFileSync(rankPyPath, 'utf8');
            const match = content.match(/"https?":\s*"([^"]+)"/);
            if (match && match[1]) return match[1];
        }
    } catch (e) {
        console.warn("[Warning] Gagal membaca proxy dari rank.py:", e.message);
    }
    return null;
}

// Baca flag USE_PROXY_FOR_GOOGLE dari rank.py (default False)
function useProxyForGoogle() {
    try {
        const content = fs.readFileSync(path.join(__dirname, 'rank.py'), 'utf8');
        const m = content.match(/USE_PROXY_FOR_GOOGLE\s*=\s*(True|False)/);
        return m ? m[1] === 'True' : false;
    } catch (e) {
        return false;
    }
}

const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
const ask = (q) => new Promise((resolve) => rl.question(q, resolve));

// SameSite=None WAJIB Secure=True; kalau tidak, browser membuang cookie saat injeksi.
function normalizeSameSite(ss, secure) {
    let v = ss || "Lax";
    if (v !== "Strict" && v !== "Lax" && v !== "None") v = "Lax";
    if (v === "None" && !secure) v = "Lax";
    return v;
}

async function captureGoogleCookies(page) {
    const client = await page.target().createCDPSession();
    // Network.getAllCookies mengambil SEMUA cookie termasuk HttpOnly & Secure
    const { cookies } = await client.send('Network.getAllCookies');
    return cookies.filter(c => (c.domain || '').includes('google.'));
}

function saveCookies(googleCookies) {
    const formatted = googleCookies.map(c => {
        const secure = !!c.secure;
        return {
            name: c.name,
            value: c.value,
            domain: c.domain,
            path: c.path,
            expires: (c.expires && c.expires > 0) ? c.expires : -1,
            httpOnly: !!c.httpOnly,
            secure: secure,
            sameSite: normalizeSameSite(c.sameSite, secure)
        };
    });
    const outputPath = path.join(__dirname, 'google_cookies.json');
    fs.writeFileSync(outputPath, JSON.stringify({ cookies: formatted, origins: [] }, null, 2), 'utf-8');
    console.log(`\n🎉 ${formatted.length} cookie Google disimpan ke:`);
    console.log(`👉 ${outputPath}`);

    const exp = formatted.find(c => c.name === 'GOOGLE_ABUSE_EXEMPTION');
    if (exp) {
        const when = exp.expires > 0 ? new Date(exp.expires * 1000).toISOString() : '(session)';
        console.log(`\n✅ GOOGLE_ABUSE_EXEMPTION tersimpan (berlaku s/d ${when}).`);
        console.log("   Catatan: exemption berumur pendek (beberapa jam) & terikat pada IP ini.");
        console.log("   Jalankan bot SEGERA selagi masih berlaku.");
    }
}

async function main() {
    // Preflight: solve CAPTCHA butuh browser yang TERLIHAT, sedangkan VPS Linux
    // biasanya tak punya layar (DISPLAY). Beri panduan, jangan crash mentah.
    if (process.platform === 'linux' && !process.env.DISPLAY) {
        console.error("\n❌ Tidak ada layar (DISPLAY tidak diset) — sepertinya ini VPS headless.");
        console.error("   Menyelesaikan CAPTCHA butuh browser yang bisa DILIHAT & diklik.\n");
        console.error("   PILIHAN:");
        console.error("   A. Layar virtual + VNC (solve DARI VPS, exemption terikat IP VPS — yang benar):");
        console.error("        sudo apt install -y xvfb x11vnc");
        console.error("        xvfb-run -a --server-args=\"-screen 0 1280x800x24\" node solve_puppeteer.js");
        console.error("      lalu di terminal lain jalankan x11vnc, sambungkan VNC dari PC Anda,");
        console.error("      selesaikan CAPTCHA, baru tekan ENTER di terminal solver.");
        console.error("   B. Andalkan fallback Bing/Brave/DDG (bot tetap jalan headless, tanpa solve).\n");
        console.error("   ⚠️  PENTING: cookie exemption TERIKAT IP. Solve di PC rumah TIDAK berlaku");
        console.error("      di IP VPS. Untuk Google-direct di VPS, solve harus DARI IP VPS (opsi A).");
        process.exit(1);
    }

    // Keputusan proxy: hormati USE_PROXY_FOR_GOOGLE di rank.py.
    //   --no-proxy / --direct  -> paksa tanpa proxy
    //   --proxy                -> paksa pakai proxy
    const forceNoProxy = process.argv.includes('--no-proxy') || process.argv.includes('--direct');
    const forceProxy = process.argv.includes('--proxy');
    let proxyUrl = null;
    if (forceProxy) proxyUrl = getProxyFromRankPy();
    else if (forceNoProxy) proxyUrl = null;
    else proxyUrl = useProxyForGoogle() ? getProxyFromRankPy() : null;

    const args = ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=430,800'];
    let username = null, password = null;

    if (proxyUrl) {
        console.log(`Memakai proxy: ${proxyUrl}`);
        try {
            const u = new URL(proxyUrl);
            args.push(`--proxy-server=${u.protocol}//${u.host}`);
            if (u.username && u.password) {
                username = decodeURIComponent(u.username);
                password = decodeURIComponent(u.password);
            }
        } catch (e) {
            console.error("Gagal parse proxy URL:", e.message);
        }
    } else {
        console.log("Berjalan TANPA proxy (IP langsung). Ini HARUS sama dengan IP yang dipakai bot,");
        console.log("karena cookie exemption terikat ke IP. (USE_PROXY_FOR_GOOGLE di rank.py = False)");
    }

    console.log("Membuka browser Chromium (headed) via Puppeteer...");
    const browser = await puppeteer.launch({ headless: false, args, defaultViewport: null });

    try {
        const page = (await browser.pages())[0] || await browser.newPage();
        await page.setUserAgent(MOBILE_UA);
        await page.setViewport({ width: 390, height: 780, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
        if (username && password) await page.authenticate({ username, password });

        console.log("Membuka beranda Google (google.co.id)...");
        await page.goto("https://www.google.co.id/", { waitUntil: 'domcontentloaded' });

        console.log(`
=======================================================
 PETUNJUK (penting agar exemption tertangkap):
 1. Di browser yang terbuka, KETIK pencarian (mis. "wdbos")
    di kolom Google lalu tekan Enter.
 2. Google akan menampilkan CAPTCHA "I'm not a robot".
    SELESAIKAN sampai hasil pencarian benar-benar tampil.
    -> Justru CAPTCHA inilah yang memberi cookie
       GOOGLE_ABUSE_EXEMPTION. Tanpa menyelesaikannya,
       cookie kunci itu TIDAK akan didapat.
 3. Setelah hasil tampil normal, kembali ke sini & tekan ENTER.
=======================================================
`);

        // Ulang sampai exemption tertangkap atau user memilih berhenti
        while (true) {
            await ask("Tekan [ENTER] setelah CAPTCHA selesai & hasil pencarian tampil...");

            const googleCookies = await captureGoogleCookies(page);
            const names = googleCookies.map(c => c.name);
            const hasExemption = names.includes('GOOGLE_ABUSE_EXEMPTION');

            console.log(`\nTertangkap ${googleCookies.length} cookie Google: ${names.join(', ') || '(kosong)'}`);
            console.log(`GOOGLE_ABUSE_EXEMPTION: ${hasExemption ? 'ADA ✅' : 'BELUM ADA ❌'}`);

            if (hasExemption) {
                saveCookies(googleCookies);
                break;
            }

            console.log("\n⚠️  Cookie exemption belum ada — artinya CAPTCHA belum benar-benar");
            console.log("    diselesaikan, atau Google belum menantang sesi ini.");
            console.log("    Coba lagi: ketik pencarian di browser, SELESAIKAN CAPTCHA-nya");
            console.log("    sampai hasil tampil, baru tekan ENTER di sini.");
            const again = (await ask("Ulangi? (y = coba lagi / n = simpan apa adanya lalu keluar): ")).trim().toLowerCase();
            if (again === 'n') {
                saveCookies(googleCookies);
                console.log("Disimpan tanpa exemption — bot kemungkinan masih akan kena CAPTCHA.");
                break;
            }
        }

        console.log("\nSelesai. Upload 'google_cookies.json' ke VPS bila perlu.");
    } catch (error) {
        console.error("Terjadi error:", error);
    } finally {
        await browser.close();
        rl.close();
    }
}

main();

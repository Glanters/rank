const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

// Fungsi untuk membaca proxy dari konfigurasi rank.py secara otomatis
function getProxyFromRankPy() {
    try {
        const rankPyPath = path.join(__dirname, 'rank.py');
        if (fs.existsSync(rankPyPath)) {
            const content = fs.readFileSync(rankPyPath, 'utf8');
            const match = content.match(/"https?":\s*"([^"]+)"/);
            if (match && match[1]) {
                return match[1];
            }
        }
    } catch (e) {
        console.warn("[Warning] Gagal membaca proxy dari rank.py:", e.message);
    }
    return null;
}

// Setup input terminal
const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
});

const askQuestion = (query) => new Promise((resolve) => rl.question(query, resolve));

async function main() {
    const disableProxy = process.argv.includes('--no-proxy') || process.argv.includes('--direct');
    const proxyUrl = disableProxy ? null : getProxyFromRankPy();
    const args = [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--window-size=900,700'
    ];

    let username = null;
    let password = null;

    if (proxyUrl) {
        console.log(`Menggunakan proxy dari rank.py: ${proxyUrl}`);
        try {
            const parsed = new URL(proxyUrl);
            args.push(`--proxy-server=${parsed.protocol}//${parsed.host}`);
            if (parsed.username && parsed.password) {
                username = decodeURIComponent(parsed.username);
                password = decodeURIComponent(parsed.password);
            }
        } catch (err) {
            console.error("Gagal parse proxy URL:", err.message);
        }
    } else {
        console.log(disableProxy ? "Berjalan tanpa proxy (Mode Direct)." : "Berjalan tanpa proxy (Tidak terkonfigurasi di rank.py).");
    }

    console.log("Membuka browser Chromium via Puppeteer...");
    
    const browser = await puppeteer.launch({
        headless: false,
        args: args,
        defaultViewport: null
    });

    try {
        const page = (await browser.pages())[0] || await browser.newPage();
        
        // Atur User-Agent mobile
        await page.setUserAgent("Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1");

        // Autentikasi proxy jika diperlukan
        if (username && password) {
            await page.authenticate({ username, password });
        }

        console.log("Membuka Google Search...");
        await page.goto("https://www.google.co.id/search?q=wdbos", { waitUntil: 'domcontentloaded' });

        console.log("\n=======================================================");
        console.log(" PETUNJUK:");
        console.log(" 1. Selesaikan tantangan CAPTCHA di browser yang terbuka.");
        console.log(" 2. Setelah hasil pencarian Google muncul dengan normal:");
        console.log("    KEMBALI KE TERMINAL INI dan tekan ENTER untuk menyimpan.");
        console.log("=======================================================\n");

        await askQuestion("Tekan [ENTER] di sini setelah Anda selesai menyelesaikan CAPTCHA...");

        console.log("Mendapatkan cookies Google...");
        const client = await page.target().createCDPSession();
        // Gunakan Network.getAllCookies agar bisa mengambil semua cookie (termasuk HttpOnly & Secure)
        const { cookies } = await client.send('Network.getAllCookies');
        
        // Filter hanya cookies yang mengarah ke Google
        const googleCookies = cookies.filter(c => c.domain.includes('google.'));

        // Format agar kompatibel dengan Playwright / standard format
        const formattedCookies = googleCookies.map(c => {
            return {
                name: c.name,
                value: c.value,
                domain: c.domain,
                path: c.path,
                expires: c.expires || -1,
                httpOnly: !!c.httpOnly,
                secure: !!c.secure,
                sameSite: c.sameSite || "Lax"
            };
        });

        const outputPath = path.join(__dirname, 'google_cookies.json');
        fs.writeFileSync(outputPath, JSON.stringify({ cookies: formattedCookies, origins: [] }, null, 2), 'utf-8');
        
        console.log(`\n🎉 Selesai! ${formattedCookies.length} Cookie Google berhasil disimpan ke:`);
        console.log(`👉 ${outputPath}`);
        console.log("\nAnda sekarang cukup meng-upload file 'google_cookies.json' ini saja ke VPS!");

    } catch (error) {
        console.error("Terjadi error:", error);
    } finally {
        await browser.close();
        rl.close();
    }
}

main();

const Database = require('better-sqlite3');
const path = require('path');
const fs = require('fs');

// Path menuju file cookies.sqlite di dalam firefox_profile
const dbPath = path.join(__dirname, 'firefox_profile', 'cookies.sqlite');

if (!fs.existsSync(dbPath)) {
    console.error(`Database cookies tidak ditemukan di: ${dbPath}`);
    console.error("Pastikan folder 'firefox_profile' sudah ada di direktori ini.");
    process.exit(1);
}

try {
    // Membuka database dengan mode read-only agar tidak crash / lock browser yang aktif
    const db = new Database(dbPath, { readonly: true, fileMustExist: true });

    // Mengambil cookie yang ber-domain google (.google.com, .google.co.id, dll)
    const query = db.prepare(`
        SELECT name, value, host, path, expiry, isSecure, isHttpOnly, sameSite
        FROM moz_cookies
        WHERE host LIKE '%google.%'
    `);

    const rows = query.all();
    console.log(`Berhasil membaca ${rows.length} baris cookie Google dari database.\n`);

    // Konversi format Firefox ke format JSON Playwright storageState
    const cookies = rows.map(row => {
        let expires = row.expiry;
        // Normalisasi timestamp jika berbentuk milidetik atau mikrodetik
        if (expires > 10**11) {
            expires = expires > 10**14 ? expires / 1000000.0 : expires / 1000.0;
        }

        // Konversi tipe SameSite Firefox (2 = Lax, 3 = Strict, selain itu = None)
        let sameSite = "None";
        if (row.sameSite === 2) sameSite = "Lax";
        else if (row.sameSite === 3) sameSite = "Strict";

        return {
            name: row.name,
            value: row.value,
            domain: row.host,
            path: row.path,
            expires: expires,
            httpOnly: !!row.isHttpOnly,
            secure: !!row.isSecure,
            sameSite: sameSite
        };
    });

    const outputData = {
        cookies: cookies,
        origins: []
    };

    const outputPath = path.join(__dirname, 'google_cookies.json');
    fs.writeFileSync(outputPath, JSON.stringify(outputData, null, 2), 'utf-8');
    console.log(`🎉 Sukses! File cookie disimpan ke: ${outputPath}`);

} catch (error) {
    console.error("Gagal membaca database cookies.sqlite:", error);
}

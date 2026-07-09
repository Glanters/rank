# Panduan Panduan Deploy Bot di Server Linux (Ubuntu/Debian)

Agar bot dapat berjalan dengan lancar di server Linux VPS, ikuti langkah-langkah instalasi dan konfigurasi berikut.

---

## Langkah 1: Persiapan Python & Project
1. **Clone project** atau salin folder project ke Linux VPS Anda.
2. Masuk ke direktori project:
   ```bash
   cd /path/to/Google-rank-tracker
   ```
3. Update package manager Linux:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```
4. Pastikan Python 3.10+ dan pip terinstal:
   ```bash
   sudo apt install python3 python3-pip python3-venv -y
   ```
5. Buat virtual environment (opsional tapi disarankan):
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

---

## Langkah 2: Instalasi Dependencies & Playwright
1. Instal package Python yang dibutuhkan:
   ```bash
   pip install -r requirements.txt
   ```
2. Download browser driver Firefox untuk Playwright:
   ```bash
   playwright install firefox
   ```
3. **PENTING:** Karena Linux VPS biasanya tidak memiliki GUI/grafis, Anda wajib menginstal dependensi sistem operasi (libraries GTK, fonts, dll.) yang dibutuhkan Firefox agar bisa berjalan di mode headless (latar belakang):
   ```bash
   sudo playwright install-deps
   ```

---

## Langkah 3: Penanganan CAPTCHA di Headless VPS Linux
Karena Linux VPS tidak memiliki tampilan layar (headless), Anda **tidak bisa** menjalankan `python solve.py` langsung di VPS untuk mencentang CAPTCHA secara visual.

### Cara Melewati CAPTCHA untuk Linux VPS:
1. Jalankan `python solve.py` di **komputer lokal (Windows)** Anda seperti biasa.
2. Centang CAPTCHA di browser yang muncul di Windows sampai selesai.
3. Setelah selesai dan sesi tersimpan, salin/upload folder **`firefox_profile`** dari komputer lokal Anda ke dalam direktori project di Linux VPS Anda (bisa menggunakan FTP, SFTP/FileZilla, atau SCP).
4. Bot di Linux VPS akan otomatis membaca cookies yang sudah terverifikasi tersebut dan langsung bypass CAPTCHA Google!

---

## Langkah 4: Menjalankan Bot 24 Jam di Background Linux
Agar bot tetap berjalan meskipun Anda menutup terminal SSH, gunakan manager proses seperti **Systemd** atau **PM2**.

### Opsi A: Menggunakan Systemd (Rekomendasi Linux)
1. Buat file service baru:
   ```bash
   sudo nano /etc/systemd/system/telegram-bot.service
   ```
2. Tempel konfigurasi berikut (sesuaikan `/path/to/...` dengan direktori Anda):
   ```ini
   [Unit]
   Description=Telegram Google Rank Tracker Bot
   After=network.target

   [Service]
   Type=simple
   User=root
   WorkingDirectory=/path/to/Google-rank-tracker
   ExecStart=/path/to/Google-rank-tracker/venv/bin/python -u rank.py
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```
3. Reload systemd, jalankan bot, dan aktifkan auto-start saat VPS booting:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl start telegram-bot
   sudo systemctl enable telegram-bot
   ```
4. Untuk melihat log aktivitas bot di Linux:
   ```bash
   sudo journalctl -u telegram-bot -f
   ```

---

### Opsi B: Menggunakan Screen (Lebih Instan)
1. Instal screen:
   ```bash
   sudo apt install screen -y
   ```
2. Buat sesi layar baru:
   ```bash
   screen -S rankbot
   ```
3. Jalankan bot:
   ```bash
   python3 rank.py
   ```
4. Keluar dari sesi (bot tetap berjalan di background): Tekan `Ctrl + A`, kemudian tekan `D`.
5. Untuk masuk kembali ke log bot nanti:
   ```bash
   screen -r rankbot
   ```

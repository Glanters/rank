"""Utility to extract Google cookies from a Firefox profile.

This helper opens the cookies.sqlite database inside the Firefox profile,
extracts cookies matching Google domains, and returns them in a format
compatible with Playwright's storage_state.
"""

import os
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import List, Dict

def normalize_expiry(expiry_val):
    """Normalize the cookie expiry timestamp to seconds."""
    if expiry_val is None:
        return None
    try:
        val = float(expiry_val)
        # If timestamp is in milliseconds (13 digits, > 10^11) or microseconds (16 digits)
        if val > 10**11:
            if val > 10**14:  # Microseconds
                return val / 1000000.0
            return val / 1000.0
        return val
    except (ValueError, TypeError):
        return expiry_val

def get_google_cookies(profile_path: Path, verbose: bool = True) -> List[Dict]:
    """Read Google cookies from the cookies.sqlite database inside the given profile path.

    Firefox yang sedang berjalan MENGUNCI cookies.sqlite, sehingga membaca file itu
    langsung memicu 'database is locked'. Untuk itu DB (beserta -wal & -shm) disalin
    dulu ke lokasi sementara, baru dibaca dari salinan tsb.

    verbose=False menekan log "Extracted N cookies" (dipakai oleh pemanggil berkala
    seperti monitor exemption agar tidak spam).
    """
    db_path = profile_path / "cookies.sqlite"
    if not db_path.exists():
        print(f"[cookie_helper] No cookies.sqlite database found at: {db_path}")
        return []

    # Salin DB + WAL + SHM ke temp agar tidak bentrok lock dengan Firefox aktif.
    tmp_dir = tempfile.mkdtemp(prefix="ckread_")
    read_path = str(db_path)
    try:
        tmp_db = os.path.join(tmp_dir, "cookies.sqlite")
        shutil.copy2(str(db_path), tmp_db)
        for ext in ("-wal", "-shm"):
            src = str(db_path) + ext
            if os.path.exists(src):
                try:
                    shutil.copy2(src, tmp_db + ext)
                except Exception:
                    pass
        read_path = tmp_db
    except Exception as e:
        print(f"[cookie_helper] Gagal menyalin DB (baca langsung, mode immutable): {e}")

    cookies = []
    conn = None
    # Open SQLite database in read-only mode using a URI
    try:
        if read_path == str(db_path):
            # Fallback: baca file asli dengan immutable=1 agar tidak kena lock
            conn = sqlite3.connect(f"file:{read_path}?immutable=1", uri=True)
        else:
            conn = sqlite3.connect(f"file:{read_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='moz_cookies';")
        if not cursor.fetchone():
            print("[cookie_helper] moz_cookies table not found in database.")
            conn.close()
            return []
            
        # Select google-related cookies
        query = """
            SELECT name, value, host, path, expiry, isSecure, isHttpOnly, sameSite
            FROM moz_cookies
            WHERE host LIKE '%google.%'
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        
        for name, value, host, path, expiry, is_secure, is_http_only, same_site in rows:
            secure = bool(is_secure)
            # Firefox sameSite: 3 = Strict, 1/2 = Lax, 0/256/lainnya = unset.
            # PENTING: sameSite "None" WAJIB secure=True; jika tidak, browser
            # membuang cookie saat injeksi. Karena kita hanya navigasi first-party
            # ke google.co.id (cookie Lax tetap terkirim), default aman = "Lax".
            if same_site == 3:
                ss = "Strict"
            elif same_site in (1, 2):
                ss = "Lax"
            elif secure:
                ss = "None"   # boleh None hanya bila cookie memang Secure
            else:
                ss = "Lax"    # None + insecure ilegal -> pakai Lax agar tidak dibuang
            cookies.append({
                "name": name,
                "value": value,
                "domain": host,
                "path": path,
                "expires": normalize_expiry(expiry),
                "httpOnly": bool(is_http_only),
                "secure": secure,
                "sameSite": ss
            })
            
        if verbose:
            print(f"[cookie_helper] Extracted {len(cookies)} Google cookies successfully.")
    except Exception as e:
        print(f"[cookie_helper] Error reading cookies: {e}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return cookies

def generate_storage_state(profile_path: Path, output_file: Path) -> bool:
    """Generate a Playwright storage state file containing Google cookies."""
    cookies = get_google_cookies(profile_path)
    if not cookies:
        return False
        
    storage_state = {
        "cookies": cookies,
        "origins": []
    }
    
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(storage_state, f, indent=2, ensure_ascii=False)
        print(f"[cookie_helper] Saved storage state to {output_file}")
        return True
    except Exception as e:
        print(f"[cookie_helper] Failed to write storage state: {e}")
        return False

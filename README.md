# VD Auto Generator (Violence District Skill Check Bot)

Bot otomatis presisi tinggi untuk memenangkan skill check generator pada game Roblox **Violence District** (*Dead by Daylight style*). Dilengkapi dengan deteksi UI otomatis, pelacakan kecepatan jarum sirkular, kompensasi latensi input perangkat keras, serta visualizer capture untuk debugging.

---

## Fitur Utama

1. **Center UI Validator (Anti-Ghost Click)**:
   * Memvalidasi keberadaan kotak ikon spasi `[_]` di bagian tengah layar sebelum melakukan pemindaian.
   * 100% kebal terhadap false positive dari baju karakter, topi kupluk putih (*cat beanie*), lampu, atau partikel dunia 3D.
2. **Multi-Radius Contiguous Clustering**:
   * Memindai balok putih target *Great/Perfect* dan jarum merah melintasi 5 lapisan radius konsentris.
   * Mengabaikan outline lingkaran tipis (1 pixel) dan noise piksel acak.
3. **Smart Velocity Engine**:
   * Melacak pergerakan sudut jarum ($\Delta \theta / \Delta t$) dan memverifikasi putaran searah jarum jam (*clockwise*).
   * Menolak objek merah statis atau lonjakan sudut liar akibat pergerakan kamera.
4. **Predictive Lead & Sub-Frame Micro-Sleep**:
   * Memprediksi momen kedatangan jarum ke titik tengah target dan mengompensasi latensi hardware Windows (~16ms).
   * Menggunakan timer resolusi sub-milidetik (`timeBeginPeriod(1)`).
5. **Fail-Safe Hit Trigger**:
   * Menjamin eksekusi klik spasi bahkan jika terjadi sedikit stutter/frame drop di Roblox saat jarum memasuki area balok putih.
6. **Live Debug Capture & Montage Visualizer**:
   * Otomatis merekam 4 frame *Pre-Hit*, 1 frame *Hit*, dan 2 frame *Post-Hit* setiap kali tombol Spasi ditekan.
   * Menampilkan ringkasan visual panorama secara instan di jendela GUI terpisah tanpa mengganggu performa loop utama (150+ FPS).

---

## Persyaratan Sistem

* Windows 10 / 11
* Python 3.9+
* Administrator privileges (diperlukan untuk direct scancode `SendInput` dan global hotkey)

---

## Instalasi

1. Clone repositori ini:
   ```bash
   git clone <URL_REPOSITORY_ANDA>
   cd "VD Auto Generator"
   ```

2. Instal dependensi:
   ```bash
   pip install -r requirements.txt
   ```

---

## Cara Menjalankan

Jalankan script launcher otomatis (dengan hak Administrator):
```bat
start.bat
```
Atau langsung jalankan via terminal administrator:
```powershell
python vd_perfect_bot.py
```

---

## Tombol Hotkey

| Tombol | Fungsi |
|---|---|
| **`[INSERT]`** | Pause / Resume bot |
| **`[X]`** | Simpan snapshot kalibrasi sensor ke `cek_kalibrasi.png` |
| **`[O]`** | Buka folder capture screenshot terakhir di Windows Explorer |
| **`[END]`** | Keluar dari program dengan aman |

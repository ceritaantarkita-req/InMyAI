# InMyAI

**Model kecil. Konteks tepat. Kerja lokal nyata.**

InMyAI adalah workspace AI lokal ringan untuk laptop konsumen dengan RAM 8–16 GB. Sistem memilih model atau tool lokal sesuai tugas, menyimpan konteks project di luar model, membaca folder yang diizinkan, dan hanya menulis file melalui alur diff, approval, serta backup.

## Mulai

```powershell
Copy-Item .env.example .env
npm run setup
npm run dev
```

Buka `http://127.0.0.1:3000`.

Core bisa dijalankan tanpa model menggunakan **Safe Mock**. Untuk jawaban generatif, install Ollama dan model kecil yang sesuai perangkat. Model weights, data project, database lokal, dan dokumen pribadi tidak disimpan di GitHub.

Baca README utama dan folder `docs/` untuk arsitektur, keamanan, memory, model routing, OCR, image generation, serta rencana repository publik.

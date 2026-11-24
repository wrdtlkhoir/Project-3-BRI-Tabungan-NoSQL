"""Bangun PPT presentasi Project 3 dari screenshot + hasil nyata (docs/*.json|txt)."""
import json, pathlib
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
SS = ROOT / "docs" / "screenshots"
S = json.load(open(ROOT / "docs" / "stress_result.json"))["hasil"]
NAVY, BLUE, GREY, LIGHT = RGBColor(0x0F, 0x23, 0x4D), RGBColor(0x1D, 0x4E, 0xD8), RGBColor(0x47, 0x55, 0x69), RGBColor(0xF1, 0xF5, 0xF9)
GREEN, RED, AMBER = RGBColor(0x16, 0xA3, 0x4A), RGBColor(0xDC, 0x26, 0x26), RGBColor(0xD9, 0x77, 0x06)

prs = Presentation(); prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]
W, H = 13.333, 7.5


def text(slide, x, y, w, h, t, size=18, bold=False, color=NAVY, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)); tf = tb.text_frame; tf.word_wrap = True
    tf.vertical_anchor = anchor
    lines = t if isinstance(t, list) else [t]
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run(); r.text = ln; r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = color; r.font.name = "Calibri"
    return tb


def bullets(slide, x, y, w, h, items, size=18, color=GREY, gap=6):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)); tf = tb.text_frame; tf.word_wrap = True
    for i, it in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(gap)
        head, _, rest = it.partition("||")
        r = p.add_run(); r.text = "• " + head; r.font.size = Pt(size); r.font.color.rgb = NAVY if rest else color; r.font.bold = bool(rest); r.font.name = "Calibri"
        if rest:
            r2 = p.add_run(); r2.text = rest; r2.font.size = Pt(size); r2.font.color.rgb = color; r2.font.name = "Calibri"
    return tb


def header(slide, title, sub=None):
    bar = slide.shapes.add_shape(1, 0, 0, Inches(W), Inches(1.0)); bar.fill.solid(); bar.fill.fore_color.rgb = NAVY; bar.line.fill.background()
    text(slide, 0.5, 0.12, 12.3, 0.6, title, 28, True, RGBColor(255, 255, 255))
    if sub:
        text(slide, 0.5, 0.58, 12.3, 0.4, sub, 14, False, RGBColor(0x93, 0xC5, 0xFD))


def image(slide, name, x, y, w, h):
    path = SS / name; im = Image.open(path); iw, ih = im.size
    sc = min(w / iw, h / ih) * 1.0
    pw, ph = iw * sc, ih * sc
    slide.shapes.add_picture(str(path), Inches(x + (w - pw) / 2), Inches(y + (h - ph) / 2), Inches(pw), Inches(ph))


def notes(slide, t): slide.notes_slide.notes_text_frame.text = t


def table(slide, x, y, w, rows, col_w, size=13, row_h=0.4, head_color=BLUE):
    shp = slide.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y), Inches(w), Inches(row_h * len(rows)))
    t = shp.table
    for j, cw in enumerate(col_w): t.columns[j].width = Inches(cw)
    for i, r in enumerate(rows):
        t.rows[i].height = Inches(row_h)
        for j, v in enumerate(r):
            c = t.cell(i, j); c.text = str(v)
            for p in c.text_frame.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(size); run.font.name = "Calibri"; run.font.bold = (i == 0)
                    run.font.color.rgb = RGBColor(255, 255, 255) if i == 0 else NAVY
            c.fill.solid(); c.fill.fore_color.rgb = head_color if i == 0 else (LIGHT if i % 2 else RGBColor(255, 255, 255))
            c.margin_left = c.margin_right = Inches(0.08); c.margin_top = c.margin_bottom = Inches(0.03)
    return t


# ============ 1. Judul
s = prs.slides.add_slide(BLANK)
bg = s.shapes.add_shape(1, 0, 0, Inches(W), Inches(H)); bg.fill.solid(); bg.fill.fore_color.rgb = NAVY; bg.line.fill.background()
text(s, 0.8, 1.7, 11.7, 1.2, "Project 3 — Sistem Tabungan BRI", 44, True, RGBColor(255, 255, 255))
text(s, 0.8, 2.8, 11.7, 1.0, "Couchbase sebagai Main Database + Cassandra sebagai Event Ledger", 28, False, RGBColor(0x93, 0xC5, 0xFD))
text(s, 0.8, 4.0, 11.7, 0.5, "Implementasi lokal (Docker Desktop) · Backend Python FastAPI · Demo end-to-end", 18, False, RGBColor(0xCB, 0xD5, 0xE1))
text(s, 0.8, 5.4, 11.7, 1.4, ["Kelompok 1 — IF5101 Manajemen Data", "Wardatul Khoiroh (13523001) · Ananda Myzza Marhelio (23526008)", "Muhammad Luthfan Ar-Rayyan (23526029) · Naufal Gusliandi (23526907)"], 16, False, RGBColor(0xCB, 0xD5, 0xE1))
notes(s, "Pembuka: kami mengimplementasikan sistem tabungan BRI dari Project 2 (PostgreSQL) ke dua database NoSQL yang benar-benar saling terhubung lewat backend, bukan dua database yang berjalan terpisah.")

# ============ 2. Latar
s = prs.slides.add_slide(BLANK); header(s, "Latar belakang & tujuan", "Dari relasional (Project 2) ke dua database NoSQL yang saling berinteraksi")
bullets(s, 0.6, 1.4, 6.2, 5.5, [
    "Project 2:|| sistem tabungan BRI di PostgreSQL (10 tabel, 20 query Read/Write, 494.347 transaksi).",
    "Project 3:|| implementasi pada NoSQL. Satu database tidak cukup untuk semua pola akses.",
    "Pembagian peran:|| Couchbase = data operasional & saldo (document, ACID multi-dokumen). Cassandra = riwayat transaksi append-only (Event Ledger).",
    "Masalah inti:|| dua database tidak punya distributed transaction. Bagaimana saldo dan ledger tetap konsisten, tanpa event hilang atau ganda?",
], 18)
card = s.shapes.add_shape(1, Inches(7.2), Inches(1.5), Inches(5.6), Inches(5.0)); card.fill.solid(); card.fill.fore_color.rgb = LIGHT; card.line.fill.background()
text(s, 7.5, 1.7, 5.0, 0.5, "Tujuan sistem", 20, True, BLUE)
bullets(s, 7.5, 2.3, 5.0, 4.2, ["Saldo selalu benar (ACID di Couchbase)", "Setiap transaksi punya jejak audit di ledger", "Retry aman: tidak tercatat dua kali (idempotensi)", "Cassandra mati ≠ event hilang (outbox + relay)", "Seluruh query Project 2 tetap punya implementasi"], 17)
notes(s, "Jelaskan kenapa dua database: Couchbase unggul untuk dokumen operasional dan transaksi pada saldo; Cassandra unggul untuk tulis append-only berskala besar. Tantangannya adalah menjaga konsistensi lintas keduanya.")

# ============ 3. Catatan reviewer
s = prs.slides.add_slide(BLANK); header(s, "Menjawab catatan reviewer laporan", "Setiap catatan ditindaklanjuti di implementasi")
rows = [["Catatan reviewer", "Tindak lanjut di implementasi"],
        ["Pembagian DB tidak tegas (semua tabel di dua DBMS)", "Couchbase = main (operasional + saldo); Cassandra = HANYA ledger transaksi (R-01, R-03, W-07). Couchbase tidak menyimpan transaksi"],
        ["Data Couchbase dan Cassandra beda (saldo 155,7 jt vs 151,2 jt)", "Seed SEKALI dari satu dump PostgreSQL; kedua DBMS dimuat dari dump yang sama + validasi rekonsiliasi"],
        ["Uang disimpan float → sisa desimal", "Saldo disimpan integer sen (saldo_efektif_sen); agregasi dibagi 100. Cassandra pakai decimal"],
        ["Dua UPDATE terpisah, kalau gagal tidak konsisten", "Transaksi ACID Couchbase multi-dokumen (transfer = debit + kredit atomik)"],
        ["last_transaction_at: BERHASIL saja atau semua status?", "Hanya event BERHASIL (sama dengan R-04 Project 2)"],
        ["Hasil query belum dicocokkan, hanya satu run", "Validasi seed + tes otomatis + stress test beberapa ratus request"],
        ["Lingkungan: DBMS jalan di perangkat mana?", "Semua lokal: Docker Desktop satu laptop (Couchbase CE 7.6.1, Cassandra 5.0, PostgreSQL 16)"]]
table(s, 0.5, 1.3, 12.3, rows, [4.4, 7.9], size=12.5, row_h=0.64)
notes(s, "Slide ini menunjukkan kami membaca dan menindaklanjuti komentar reviewer. Tekankan tiga yang paling penting: pembagian peran database, data identik dari satu dump, dan uang tidak disimpan sebagai float.")

# ============ 4. Arsitektur
s = prs.slides.add_slide(BLANK); header(s, "Arsitektur", "Python backend sebagai penghubung; semua berjalan lokal")
image(s, "01_arsitektur.png", 0.5, 1.2, 12.3, 5.0)
text(s, 0.6, 6.4, 12.1, 0.9, "Backend: FastAPI · Couchbase SDK (transaksi ACID) · cassandra-driver · konfigurasi lewat .env (tidak ada credential di kode) · cloud ↔ local cukup ganti .env", 15, False, GREY)
notes(s, "Client hanya bicara ke backend. Backend memvalidasi, menjalankan transaksi ACID di Couchbase, lalu menerbitkan event ke Cassandra. Konfigurasi koneksi lewat environment variable sehingga bisa dipindah ke cloud tanpa mengubah kode.")

# ============ 5. Pemetaan query
s = prs.slides.add_slide(BLANK); header(s, "Pembagian database & pemetaan query Project 2", "Setiap query Project 2 punya implementasi di Project 3")
rows = [["Query", "Deskripsi", "DB", "Implementasi"],
        ["R-01", "Riwayat transaksi rekening", "Cassandra", "GET /rekening/{no}/histori"],
        ["R-02", "Nasabah > 1 rekening", "Couchbase", "N1QL UNNEST + JOIN KEYS"],
        ["R-03", "Laporan per bulan per kanal", "Cassandra", "ledger_by_kanal_bulan"],
        ["R-04", "Rekening tak aktif > 90 hari", "Couchbase", "last_transaction_at (BERHASIL)"],
        ["R-05..R-10", "Tanpa rekening, per unit, bunga, instruksi, kartu, per produk", "Couchbase", "GET /laporan/R-xx (N1QL)"],
        ["W-01..W-04, 06, 08, 09", "Master & data operasional", "Couchbase", "N1QL write (reuse Part-3)"],
        ["W-05, W-10", "Blokir / tutup rekening", "Couchbase + ledger", "POST /rekening/{no}/blokir|tutup"],
        ["W-07", "Setoran / penarikan / transfer", "Couchbase + Cassandra", "POST /transaksi/* (outbox)"]]
table(s, 0.5, 1.3, 12.3, rows, [2.2, 4.9, 2.2, 3.0], size=13, row_h=0.5)
text(s, 0.5, 6.0, 12.3, 1.2, "Tidak diterjemahkan langsung: JOIN & NOT EXISTS atas transaksi (R-01, R-03, R-04) → denormalisasi nama kanal ke event, atribut turunan last_transaction_at, dan agregasi di aplikasi. FK/CHECK → validasi di service layer.", 14, False, GREY)
notes(s, "Prinsipnya: data terkini dan operasional ke Couchbase, histori ke Cassandra. Query yang tidak bisa diterjemahkan 1:1 dijelaskan alasannya: Cassandra tidak punya JOIN, jadi nama kanal disimpan di event.")

# ============ 5b. Alasan Couchbase (main DB)
s = prs.slides.add_slide(BLANK); header(s, "Mengapa Couchbase dipilih sebagai main database", "Data operasional dan saldo berada di sini")
bullets(s, 0.6, 1.4, 12.1, 5.6, [
    "Model dokumen cocok dengan data bank||: rekening menyimpan pemegang_rekening, nasabah menyimpan rekening_refs; satu baca = satu entitas lengkap, tanpa JOIN.",
    "Transaksi ACID multi-dokumen||: saldo + dokumen outbox dalam satu transaksi (SDK); W-01, W-02, W-03 menjaga dua dokumen tetap konsisten.",
    "SQL++ (N1QL)||: query Project 2 (agregasi, JOIN KEYS, UNNEST) bisa diterjemahkan langsung; 18 dari 20 query ada di sini.",
    "Key-Value + indeks GSI||: akses per kunci (rekening::<no>) sangat cepat, tulis 1 dokumen sekitar 2 ms; laporan memakai indeks sekunder.",
    "Satu sumber kebenaran saldo||: saldo (integer sen) hanya ditulis di Couchbase, sehingga tidak ada saldo ganda di dua database.",
    "Mudah dijalankan lokal||: Community Edition 7.6.1 di Docker, satu node.",
], 17, gap=10)
notes(s, "Alasan inti: data operasional bank berbentuk agregat (rekening beserta pemegangnya) dan butuh transaksi atomik. Couchbase memberi keduanya, ditambah SQL++ sehingga query Project 2 tidak perlu ditulis ulang dari nol.")

# ============ 5c. Alasan Cassandra (support DB)
s = prs.slides.add_slide(BLANK); header(s, "Mengapa Cassandra dipilih sebagai support database", "Perannya: event ledger append-only (riwayat transaksi)")
bullets(s, 0.6, 1.4, 6.0, 5.6, [
    "Tulis sangat cepat||: arsitektur LSM; cocok untuk catatan transaksi yang terus bertambah.",
    "Data deret waktu||: partition key (no_rekening, bulan) + clustering waktu; riwayat satu rekening dibaca dari satu partisi terurut.",
    "Append-only dan idempoten||: event tidak diubah; kunci event + idempotency key mencegah event ganda.",
    "Mudah diskalakan||: partisi per rekening-bulan mencegah partisi raksasa."], 16, gap=10)
bullets(s, 6.9, 1.4, 6.0, 5.6, [
    "Entitas di Cassandra||: ledger_by_rekening, ledger_event_by_id, ledger_by_kanal_bulan (R-01, R-03, W-07).",
    "Entitas di Couchbase||: nasabah, rekening, kartu, produk, unit kerja, posting bunga, instruksi, outbox (R-02, R-04..R-10, W-01..W-10).",
    "Alur||: transaksi uang ditulis di Couchbase bersama outbox; relay menerbitkan event ke Cassandra secara idempoten.",
    "Konsekuensi||: saldo konsisten; ledger eventual (jeda singkat)."], 16, gap=10)
notes(s, "Cassandra bukan pengganti Couchbase. Ia pendukung untuk riwayat yang bertambah terus dan dibaca per rekening. Tidak semua query ada di dua database; yang penting 20 query tercakup di salah satunya.")

# ============ 5d. Tantangan
s = prs.slides.add_slide(BLANK); header(s, "Potensi kesulitan dan tantangan implementasi", "Dan bagaimana kami menanganinya")
rows = [["Tantangan", "Penanganan"],
        ["Tidak ada distributed transaction Couchbase + Cassandra", "Transactional Outbox + idempotency key; ledger eventual"],
        ["Cassandra tanpa JOIN / UNIQUE", "Denormalisasi nama kanal; penjaga NIK lewat dokumen nik::<nik> di Couchbase"],
        ["Dua dokumen harus berubah bersama", "Transaksi ACID (W-01, W-02, W-03, W-05)"],
        ["Uang tipe float menimbulkan selisih", "Disimpan integer sen (saldo_efektif_sen)"],
        ["Data harus identik di kedua DBMS", "Satu dump PostgreSQL Project 2; validasi seed + rekonsiliasi"],
        ["Profil query terbatas di Community Edition", "EXPLAIN + metrik executionTime; profile timings hanya Enterprise"],
        ["Lingkungan lokal terbatas (RAM, Docker/WSL)", "Kuota Couchbase diperkecil, satu node, retry koneksi"]]
table(s, 0.5, 1.3, 12.3, rows, [5.6, 6.7], size=14, row_h=0.62)
notes(s, "Tantangan utama adalah menjaga konsistensi tanpa transaksi lintas database. Jawabannya outbox. Lalu keterbatasan model Cassandra dan keterbatasan edisi komunitas.")

# ============ 6. Model data
s = prs.slides.add_slide(BLANK); header(s, "Model data nyata di kedua database", "Dokumen operasional (Couchbase) dan event ledger (Cassandra)")
image(s, "11_dokumen_couchbase.png", 0.4, 1.2, 6.2, 5.6); image(s, "12_ledger_cqlsh.png", 6.7, 1.2, 6.3, 5.6)
text(s, 0.5, 6.85, 12.3, 0.5, "Couchbase: key rekening::<no>, saldo integer sen, pemegang di-embed.   Cassandra: partisi (no_rekening, bulan) agar tidak tumbuh tanpa batas, urut waktu menurun.", 13, False, GREY)
notes(s, "Kiri: dokumen rekening di Couchbase dengan saldo dalam sen dan array pemegang rekening di-embed. Kanan: baris ledger di Cassandra lewat cqlsh. Partisi dibatasi per rekening dan bulan.")

# ============ 7. Data seed
s = prs.slides.add_slide(BLANK); header(s, "Data seed & validasi", "Satu sumber (dump PostgreSQL Project 2) → Couchbase dan Cassandra")
image(s, "13_validasi_seed.png", 0.4, 1.2, 8.3, 5.9)
bullets(s, 8.9, 1.4, 4.1, 5.6, ["10.000 nasabah, 12.000 rekening", "8.214 kartu, 20.000 posting bunga, 1.500 instruksi", "494.347 event di Cassandra", "Jumlah dokumen = sumber (semua OK)", "Saldo total Couchbase = seed + net event ledger (rekonsiliasi)", "tx_count Couchbase = jumlah event ledger per rekening", "Bug yang ditemukan validasi: loader tidak memeriksa kegagalan parsial → diperbaiki"], 15)
notes(s, "Validasi ini penting: kami menemukan bahwa upsert batch Couchbase bisa gagal sebagian tanpa error, sehingga dokumen hilang diam-diam. Loader diperbaiki dan validasi rekonsiliasi saldo membuktikan kedua database konsisten.")

# ============ 8. Outbox
s = prs.slides.add_slide(BLANK); header(s, "Alur transaksi: Transactional Outbox", "Konsistensi tanpa distributed transaction")
image(s, "02_alur_outbox.png", 0.5, 1.2, 12.3, 5.9)
notes(s, "Langkah 1 atomik di Couchbase: ubah saldo dan tulis outbox PENDING. Langkah 2 tulis event ke Cassandra secara idempoten. Kalau gagal, relay mengulang. Trade-off: ledger bersifat eventual, saldo selalu konsisten.")

# ============ 9-11 Demo
for name, title, sub, note in [
    ("06_demo_setoran.png", "Demo 1 — Setoran", "Saldo Couchbase naik, event muncul di ledger Cassandra", "Tunjukkan saldo sebelum/sesudah, respons API, dan baris baru di ledger paling atas."),
    ("07_demo_idempotensi.png", "Demo 2 — Retry tidak menggandakan transaksi", "idempotency_key sama → duplicate: true", "Request kedua dengan kunci sama dikenali sebagai duplikat. Saldo dan tx_count tidak bertambah."),
    ("08_demo_transfer.png", "Demo 3 — Transfer atomik & penolakan", "Debit + kredit dalam satu transaksi ACID; dua event ledger", "Transfer sukses menghasilkan dua event. Transfer yang saldonya kurang ditolak dan kedua saldo tidak berubah."),
    ("09_demo_cassandra_mati.png", "Demo 4 — Cassandra mati, event tidak hilang", "Outbox menahan event sampai Cassandra pulih", "Saat Cassandra mati, saldo tetap berubah dan event PENDING di outbox. Setelah pulih, relay menerbitkan tepat satu kali."),
]:
    s = prs.slides.add_slide(BLANK); header(s, title, sub); image(s, name, 0.4, 1.15, 12.5, 6.2); notes(s, note)

# ============ 12. Read
s = prs.slides.add_slide(BLANK); header(s, "Query Read Project 2", "Cassandra untuk ledger (R-01, R-03), Couchbase untuk operasional (R-02, R-04..R-10)")
image(s, "10_laporan_read.png", 0.4, 1.15, 12.5, 6.2)
notes(s, "R-03 dihitung dari ledger Cassandra per kanal dan bulan. R-02 dan R-10 dijalankan di Couchbase dengan N1QL. Saldo agregat tidak lagi memunculkan sisa desimal karena memakai kolom integer sen.")

# ============ 13. Tes
s = prs.slides.add_slide(BLANK); header(s, "Pengujian otomatis", "15 tes lulus: unit + integrasi Couchbase ↔ Cassandra")
image(s, "14_pytest.png", 0.4, 1.2, 8.4, 5.8)
bullets(s, 9.0, 1.4, 4.0, 5.5, ["Unit: konversi sen, saldo, idempotensi key", "Setoran mengubah saldo & mencatat event", "Retry tidak ganda", "Penarikan melebihi saldo: tidak menulis apa pun", "Transfer atomik; gagal → kedua saldo utuh", "Cassandra mati → outbox → pulih (1 event)", "Histori terurut; partisi terbatas"], 15)
notes(s, "Semua skenario kegagalan diuji otomatis, termasuk simulasi Cassandra mati dan transfer yang gagal di tengah.")

# ============ 14. Stress
s = prs.slides.add_slide(BLANK); header(s, "Stress test (lokal)", "Satu laptop, satu node per DBMS: angka ini batas bawah latensi (tanpa jaringan antar node)")
rows = [["Skenario", "Req", "Avg (ms)", "P95 (ms)", "P99 (ms)", "Throughput (req/s)", "Error"]]
for r in S:
    rows.append([r["skenario"], r["request"], r["avg_ms"], r["p95_ms"], r["p99_ms"], r["throughput_rps"], f"{r['error_rate_pct']}%"])
table(s, 0.4, 1.25, 12.5, rows, [5.4, 0.8, 1.2, 1.2, 1.2, 1.6, 1.1], size=12.5, row_h=0.5)
hot = [r for r in S if "konsistensi" in r][0]["konsistensi"]
card = s.shapes.add_shape(1, Inches(0.4), Inches(5.0), Inches(12.5), Inches(1.9)); card.fill.solid(); card.fill.fore_color.rgb = LIGHT; card.line.fill.background()
text(s, 0.6, 5.1, 12.1, 0.4, f"Konsistensi hot account: {hot['sukses']} setoran serentak ke 1 rekening → saldo naik tepat Rp{hot['selisih_sen']/100:,.0f} (harapan Rp{hot['diharapkan_sen']/100:,.0f}) — {'KONSISTEN' if hot['konsisten'] else 'TIDAK KONSISTEN'}", 15, True, GREEN if hot['konsisten'] else RED)
bullets(s, 0.6, 5.55, 12.1, 1.4, ["Baca KV Couchbase paling cepat; tulis ACID lebih mahal dari tulis ledger Cassandra.", "Integrasi (txn + outbox + Cassandra) ≈ jumlah biaya keduanya; contention pada satu rekening menaikkan P95 tetapi tidak merusak konsistensi.", "Latensi bukan perbandingan murni DBMS: client, driver, dan jaringan lokal ikut terukur."], 13)
notes(s, "Hasil stress test sungguhan di laptop kami. Poin utama: nol error dan konsisten pada 100 setoran serentak ke satu rekening. Tekankan bahwa angka latensi adalah batas bawah karena semua di satu mesin.")

# ============ 15. Deployment
s = prs.slides.add_slide(BLANK); header(s, "Deployment lokal dengan Docker Desktop", "docker compose: Couchbase CE 7.6.1 · Cassandra 5.0 · PostgreSQL 16 (sumber seed)")
image(s, "04_couchbase_ui_buckets.png", 0.3, 1.2, 4.3, 4.3); image(s, "05_couchbase_ui_query.png", 4.7, 1.2, 4.3, 4.3); image(s, "03_swagger.png", 9.1, 1.2, 4.0, 4.3)
text(s, 0.4, 5.6, 4.3, 0.5, "Couchbase Web UI: bucket bri_tabungan (52 ribu item)", 12, False, GREY)
text(s, 4.8, 5.6, 4.3, 0.5, "Query Workbench: saldo dalam sen, tx_count", 12, False, GREY)
text(s, 9.2, 5.6, 3.9, 0.5, "Swagger UI backend: /docs", 12, False, GREY)
bullets(s, 0.5, 6.1, 12.3, 1.3, ["docker compose up -d → python scripts/load_all.py → python scripts/build_indexes.py → uvicorn app.main:app", "Cloud ↔ local hanya ganti .env (contoh keduanya di .env.example)"], 14)
notes(s, "Tiga tangkapan layar asli: Web UI Couchbase, Query Workbench, dan Swagger UI backend. Seluruh lingkungan dijalankan lokal dengan Docker Desktop.")

# ============ 16. Keterbatasan
s = prs.slides.add_slide(BLANK); header(s, "Keterbatasan & usulan perbaikan", "Jujur tentang batas implementasi")
bullets(s, 0.6, 1.4, 6.0, 5.5, ["Satu node, replication factor 1||: tanpa HA; produksi: RF 3, LOCAL_QUORUM, durability MAJORITY.", "Ledger eventual||: ada jeda singkat antara saldo berubah dan event terlihat.", "Relay polling||: bisa diganti Couchbase Eventing / CDC untuk latensi lebih rendah.", "R-03 agregasi di aplikasi||: untuk analitik besar gunakan Spark/OLAP atau tabel rollup."], 16)
bullets(s, 6.9, 1.4, 6.0, 5.5, ["Lingkungan terbatas||: RAM laptop kecil; Couchbase CE dengan kuota diperkecil.", "Belum ada autentikasi API||: perlu OAuth/JWT dan rate limiting.", "Posting bunga & instruksi terjadwal||: masih lewat N1QL; bisa dijadikan job terjadwal yang juga menulis ledger.", "Cassandra READ histori||: dibaca per partisi bulanan; rentang panjang = beberapa query."], 16)
notes(s, "Sampaikan keterbatasan dengan jujur supaya penguji tahu kami paham batasnya. Ini menjawab pertanyaan 'bagaimana jika di produksi'.")

# ============ 17. Kesimpulan
s = prs.slides.add_slide(BLANK); header(s, "Kesimpulan")
bullets(s, 0.7, 1.5, 11.9, 5.5, [
    "Dua NoSQL saling terintegrasi:|| Couchbase (saldo, ACID) + Cassandra (event ledger append-only) lewat backend Python.",
    "Konsistensi tanpa distributed transaction:|| Transactional Outbox + idempotency key + penulisan idempoten.",
    "Terbukti:|| 15 tes lulus, validasi seed rekonsiliasi OK, 100 setoran serentak ke satu rekening konsisten, 0% error.",
    "Data identik:|| kedua DBMS dimuat dari satu dump Project 2; uang disimpan integer sen.",
    "Siap dipindah:|| Docker Compose lokal; cloud ↔ local cukup ganti file .env.",
], 20, gap=14)
notes(s, "Tutup dengan empat bukti: tes lulus, validasi rekonsiliasi, uji konsistensi serentak, dan data identik. Lanjut ke tanya jawab.")

out = ROOT / "docs" / "Project3_Presentasi_BRI_Tabungan_NoSQL.pptx"
prs.save(out); print("tersimpan", out, "-", len(prs.slides), "slide")

"""Buat screenshot untuk presentasi: (a) UI asli (Swagger, Couchbase Web UI) dan (b) panel hasil demo
(render HTML -> PNG) dari log demo / validasi / tes / stress."""
import html, json, pathlib, subprocess, sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"; OUT = DOCS / "screenshots"; OUT.mkdir(parents=True, exist_ok=True)
API = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8765"
CSS = """
body{margin:0;background:#0f172a;font-family:'Segoe UI',Arial,sans-serif;color:#e2e8f0}
.wrap{padding:22px 26px;width:1180px}
h1{font-size:22px;margin:0 0 4px;color:#fff} .sub{color:#94a3b8;font-size:14px;margin-bottom:14px}
.term{background:#020617;border:1px solid #1e293b;border-radius:10px;padding:14px 16px;font:13.5px/1.5 Consolas,'Courier New',monospace;white-space:pre-wrap;color:#cbd5e1}
.term .k{color:#7dd3fc}.term .s{color:#86efac}.term .n{color:#fbbf24}.term .e{color:#fca5a5}.term .c{color:#94a3b8}
.row{display:flex;gap:14px;margin-bottom:14px}.col{flex:1}
.badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:700;margin-right:6px}
.ok{background:#14532d;color:#bbf7d0}.pend{background:#78350f;color:#fde68a}.bad{background:#7f1d1d;color:#fecaca}.db{background:#1e3a8a;color:#bfdbfe}.cas{background:#4c1d95;color:#ddd6fe}
table{border-collapse:collapse;width:100%;font-size:13.5px}th{background:#1e293b;color:#e2e8f0;text-align:left;padding:7px 10px}
td{border-bottom:1px solid #1e293b;padding:6px 10px;color:#e2e8f0}tr:nth-child(even) td{background:#0b1222}
.card{background:#111c33;border:1px solid #1e293b;border-radius:10px;padding:12px 14px}
.big{font-size:28px;font-weight:700;color:#fff}.lbl{font-size:12px;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px}
.up{color:#4ade80}.down{color:#f87171}
"""

def colorize_json(obj):
    s = html.escape(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
    import re
    s = re.sub(r'&quot;([^&]+?)&quot;:', r'<span class="k">"\1"</span>:', s)
    s = re.sub(r': &quot;(.*?)&quot;', r': <span class="s">"\1"</span>', s)
    s = re.sub(r': (-?\d[\d.]*)', r': <span class="n">\1</span>', s)
    return s

def page(title, sub, body):
    return f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body><div class='wrap' id='w'><h1>{title}</h1><div class='sub'>{sub}</div>{body}</div></body></html>"

def term(text): return f"<div class='term'>{text}</div>"
def esc(t): return html.escape(t)
def money(x): return f"Rp{float(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
def rows_table(rows, cols):
    th = "".join(f"<th>{c[0]}</th>" for c in cols)
    tr = "".join("<tr>" + "".join(f"<td>{c[1](r)}</td>" for c in cols) + "</tr>" for r in rows)
    return f"<table><tr>{th}</tr>{tr}</table>"

def hist_table(rows):
    return rows_table(rows, [("Waktu event (UTC)", lambda r: r["waktu_event"][:19].replace("T", " ")),
        ("Jenis", lambda r: r["jenis_event"]), ("Arah", lambda r: r["arah"]), ("Nominal", lambda r: money(r["nominal"])),
        ("Saldo setelah", lambda r: money(r["saldo_setelah"]) if r["saldo_setelah"] else "-"),
        ("Status", lambda r: r["status_event"]), ("Event ID", lambda r: r["event_id"]), ("Sumber", lambda r: r["sumber"])])

L = json.load(open(DOCS / "demo_log.json", encoding="utf8"))
def find(prefix, nth=0):
    m = [s for s in L if s["judul"].startswith(prefix)]; return m[nth]

shots = {}   # nama -> html

# ---- 1. setoran
s0 = L[1]["response"]; setor = find("Setoran Rp500.000"); s1 = find("Saldo 002101000000001", 1)["response"]
hist = find("Histori ledger")["response"]
shots["06_demo_setoran"] = page("Demo 1 — Setoran Rp500.000", "Couchbase (saldo, transaksi ACID) → outbox → Cassandra (event ledger)", f"""
<div class='row'><div class='col card'><div class='lbl'>Saldo sebelum (Couchbase)</div><div class='big'>{money(s0['saldo_efektif'])}</div><div class='lbl'>tx_count {s0['tx_count']}</div></div>
<div class='col card'><div class='lbl'>Saldo sesudah (Couchbase)</div><div class='big up'>{money(s1['saldo_efektif'])}</div><div class='lbl'>tx_count {s1['tx_count']}</div></div>
<div class='col card'><div class='lbl'>Status ledger</div><div class='big'><span class='badge ok'>{setor['response']['ledger_status']}</span></div><div class='lbl'>{setor['ms']:.0f} ms end-to-end</div></div></div>
<div class='row'><div class='col'><div class='lbl'>POST /transaksi/setoran</div>{term(colorize_json(setor['request']))}</div>
<div class='col'><div class='lbl'>Respons</div>{term(colorize_json(setor['response']))}</div></div>
<div class='lbl'>Histori di Event Ledger Cassandra (R-01) — event baru muncul paling atas</div>{hist_table(hist)}""")

# ---- 2. idempotensi
retry = find("RETRY"); s2 = find("Saldo 002101000000001", 2)["response"]
shots["07_demo_idempotensi"] = page("Demo 2 — Retry dengan idempotency key sama", "Transaksi tidak tercatat dua kali", f"""
<div class='row'><div class='col'><div class='lbl'>Request ke-2 (kunci sama)</div>{term(colorize_json(retry['request']))}</div>
<div class='col'><div class='lbl'>Respons</div>{term(colorize_json(retry['response']))}</div></div>
<div class='row'><div class='col card'><div class='lbl'>duplicate</div><div class='big'><span class='badge ok'>{retry['response']['duplicate']}</span></div></div>
<div class='col card'><div class='lbl'>Saldo setelah retry</div><div class='big'>{money(s2['saldo_efektif'])}</div><div class='lbl'>tx_count {s2['tx_count']} (tidak bertambah)</div></div></div>""")

# ---- 3. penarikan ditolak + transfer
tolak = find("Penarikan melebihi"); tf = find("Transfer A -> B"); tfg = find("Transfer gagal")
sA = [s for s in L if s["judul"].startswith("Saldo 002101000000001")]; sB = [s for s in L if s["judul"].startswith("Saldo 002101000000004")]
shots["08_demo_transfer"] = page("Demo 3 — Transfer atomik + validasi", "Debit dan kredit dalam SATU transaksi ACID Couchbase; dua event masuk ledger", f"""
<div class='row'><div class='col'><div class='lbl'>Transfer A → B Rp250.000</div>{term(colorize_json(tf['response']))}</div>
<div class='col'><div class='lbl'>Penarikan melebihi saldo → HTTP {tolak['status']}</div>{term(colorize_json(tolak['response']))}</div></div>
<div class='lbl'>Histori ledger: rekening A (debit) dan rekening B (kredit)</div>{hist_table(find('Histori A')['response'][:3])}<br>{hist_table(find('Histori B')['response'][:2])}
<br><div class='lbl'>Transfer gagal (saldo kurang) → HTTP {tfg['status']}, kedua saldo tidak berubah</div>{term(colorize_json(tfg['response']))}""")

# ---- 4. chaos
ch_on = find("SIMULASI: Cassandra mati"); ch_trx = find("Setoran saat Cassandra mati"); ob1 = find("Outbox: event menunggu")["response"]
relay = find("Relay outbox"); h2 = find("Histori A: event muncul")["response"]; ob2 = find("Outbox setelah relay")["response"]
shots["09_demo_cassandra_mati"] = page("Demo 4 — Cassandra mati: event tidak hilang", "Transactional Outbox: saldo benar, event menunggu lalu terbit tepat satu kali", f"""
<div class='row'><div class='col card'><div class='lbl'>① Cassandra mati (simulasi)</div>
{term(colorize_json(ch_on['response']))}<br><div class='lbl'>Setoran Rp75.000 tetap sukses</div><span class='badge ok'>saldo Couchbase naik</span><span class='badge pend'>ledger: {ch_trx['response']['ledger_status']}</span></div>
<div class='col card'><div class='lbl'>② Outbox (Couchbase)</div>{term(colorize_json(ob1['ringkasan']))}<br><div class='lbl'>③ Cassandra pulih → relay</div>{term(colorize_json(relay['response']))}</div>
<div class='col card'><div class='lbl'>④ Outbox sesudah relay</div>{term(colorize_json(ob2['ringkasan']))}</div></div>
<div class='lbl'>Histori ledger sesudah relay — event setoran Rp75.000 muncul tepat satu kali</div>{hist_table(h2)}""")

# ---- 5. laporan
r3 = find("R-03")["response"]; r10 = find("R-10")["response"][:6]; r2 = find("R-02")["response"][:5]
shots["10_laporan_read"] = page("Query Read Project 2 pada Project 3", "R-03 dilayani Cassandra (ledger), R-02 dan R-10 dilayani Couchbase (N1QL)", f"""
<div class='lbl'><span class='badge cas'>CASSANDRA</span>R-03 laporan jumlah & nominal per bulan per kanal (KNL01, Jul–Okt 2026)</div>
{rows_table(r3[:8], [("Bulan", lambda r: r['bulan']), ("Jenis", lambda r: r['jenis_transaksi']), ("Jumlah", lambda r: f"{r['jumlah_transaksi']:,}"), ("Total nominal", lambda r: money(r['total_nominal'])), ("Rata-rata", lambda r: money(r['rata_rata_nominal']))])}
<br><div class='lbl'><span class='badge db'>COUCHBASE</span>R-10 distribusi rekening & saldo per produk (saldo dari kolom integer sen → tanpa sisa desimal)</div>
{rows_table(r10, [("Produk", lambda r: r['nama_produk']), ("Keluarga", lambda r: r['keluarga_produk']), ("Jumlah rekening", lambda r: f"{r['jumlah_rekening']:,}"), ("Total saldo", lambda r: money(r['total_saldo']))])}
<br><div class='lbl'><span class='badge db'>COUCHBASE</span>R-02 nasabah dengan lebih dari satu rekening aktif</div>
{rows_table(r2, [("ID", lambda r: r['id_nasabah']), ("Nama", lambda r: r['nama_lengkap']), ("Rekening aktif", lambda r: r['jumlah_rekening_aktif']), ("Total saldo", lambda r: money(r['total_saldo_efektif']))])}""")

# ---- 6. dokumen Couchbase + baris Cassandra
import httpx
doc = httpx.get(f"{API}/rekening/002101000000001", timeout=30).json()
shots["11_dokumen_couchbase"] = page("Dokumen operasional di Couchbase", "bucket bri_tabungan › scope operasional › collection rekening › key rekening::002101000000001", term(colorize_json(doc)))
cq = subprocess.run(["docker", "exec", "bri-cassandra", "cqlsh", "-e",
    "SELECT waktu_event, jenis_event, arah, nominal, saldo_setelah, status_event, event_id, sumber FROM bri_ledger.ledger_by_rekening "
    "WHERE no_rekening='002101000000001' AND bulan='202611' LIMIT 8;"], capture_output=True, text=True).stdout
shots["12_ledger_cqlsh"] = page("Event Ledger di Cassandra (cqlsh)", "keyspace bri_ledger › ledger_by_rekening — partisi (no_rekening, bulan), terbaru dulu, append-only",
    term("<span class='c'>cqlsh&gt;</span> SELECT … FROM bri_ledger.ledger_by_rekening WHERE no_rekening='002101000000001' AND bulan='202611' LIMIT 8;\n\n" + esc(cq)))

# ---- 7. validasi, tes, stress
val = (DOCS / "validate_seed.txt").read_text(encoding="utf8")
val_h = esc(val).replace("[OK  ]", "<span class='s'>[OK  ]</span>").replace("SEMUA OK", "<span class='s'>SEMUA OK</span>")
shots["13_validasi_seed"] = page("Validasi seeding", "Couchbase & Cassandra diisi dari SATU dump PostgreSQL yang sama; jumlah dan saldo direkonsiliasi", term(val_h))
pt = (DOCS / "pytest_output.txt").read_text(encoding="utf8").splitlines()
pt = [l for l in pt if "PASSED" in l or "passed" in l or "FAILED" in l]
pt_h = "\n".join(esc(l).replace("PASSED", "<span class='s'>PASSED</span>").replace("FAILED", "<span class='e'>FAILED</span>") for l in pt)
shots["14_pytest"] = page("Hasil pengujian otomatis", "Unit test + integration test (Couchbase ↔ Cassandra)", term(pt_h))
sp = DOCS / "stress_result.json"
if sp.exists():
    S = json.load(open(sp))["hasil"]
    tb = rows_table(S, [("Skenario", lambda r: r['skenario']), ("Request", lambda r: r['request']), ("Worker", lambda r: r['workers']),
        ("Avg (ms)", lambda r: r['avg_ms']), ("P95 (ms)", lambda r: r['p95_ms']), ("P99 (ms)", lambda r: r['p99_ms']),
        ("Throughput (req/s)", lambda r: r['throughput_rps']), ("Error (%)", lambda r: r['error_rate_pct'])])
    hot = [r for r in S if 'konsistensi' in r]
    kons = ""
    if hot:
        k = hot[0]['konsistensi']
        kons = f"<br><div class='card'><div class='lbl'>Uji konsistensi hot account (100 setoran serentak ke 1 rekening)</div><div class='big'><span class='badge {'ok' if k['konsisten'] else 'bad'}'>{'KONSISTEN' if k['konsisten'] else 'TIDAK KONSISTEN'}</span></div>saldo naik {k['selisih_sen']/100:,.2f} dari harapan {k['diharapkan_sen']/100:,.2f} ({k['sukses']} transaksi sukses)</div>"
    shots["15_stress_test"] = page("Stress test (lokal, 1 laptop, 1 node per DBMS)", "Latency & throughput; angka = batas bawah karena tanpa jaringan antar node", tb + kons)


# ---- diagram statis
def box(cls, title, lines): return f"<div class='card' style='min-width:250px;text-align:center'><div class='badge {cls}' style='font-size:14px'>{title}</div><div style='margin-top:8px;font-size:13px;color:#cbd5e1;line-height:1.5'>{lines}</div></div>"
arrow = "<div style='font-size:28px;color:#64748b;align-self:center'>&#10132;</div>"
shots["01_arsitektur"] = page("Arsitektur Local — Couchbase + Cassandra Event Ledger", "Backend Python (FastAPI) menghubungkan dua database; semua berjalan lokal lewat Docker Desktop", f"""
<div class='row' style='align-items:stretch;justify-content:center'>
{box('ok','Client','Swagger UI / curl<br>POST setoran, penarikan, transfer<br>GET histori, laporan')}{arrow}
{box('ok','FastAPI Backend (Python)','validasi &middot; business logic<br>idempotency key<br>transaksi ACID Couchbase<br>relay outbox &rarr; ledger')}{arrow}
<div style='display:flex;flex-direction:column;gap:14px'>
{box('db','Couchbase CE 7.6.1 &mdash; MAIN DB','nasabah, rekening (saldo integer sen), kartu,<br>produk, unit kerja, kanal, posting bunga,<br>instruksi, <b>outbox</b> &nbsp;|&nbsp; transaksi ACID multi-dokumen')}
{box('cas','Cassandra 5.0 &mdash; EVENT LEDGER','ledger_by_rekening ((no_rekening, bulan), waktu DESC)<br>ledger_event_by_id &nbsp;|&nbsp; ledger_by_kanal_bulan<br>append-only &middot; 494.347 event seed')}
</div></div>
<div class='card' style='margin-top:6px'><b>Sumber data seed:</b> satu dump PostgreSQL Project 2 (<code>tabungan_bri.dump</code>) &rarr; dimuat ke Couchbase dan Cassandra, jadi data kedua DBMS identik.</div>""")
shots["02_alur_outbox"] = page("Alur Transaksi: Transactional Outbox", "Tidak ada distributed transaction antar-database, jadi event dijaga lewat outbox + idempotensi", f"""
<div class='row' style='align-items:stretch'>
{box('db','1. Transaksi ACID Couchbase','validasi rekening &amp; saldo<br>update saldo (sen)<br>tulis outbox <b>PENDING</b><br><i>satu commit atomik</i>')}{arrow}
{box('cas','2. Publish ke Cassandra','logged batch ke 3 tabel<br>primary key deterministik<br>&rarr; retry = upsert yang sama')}{arrow}
{box('ok','3. Tandai PUBLISHED','respons ke client<br>ledger_status = PUBLISHED')}</div>
<div class='row' style='align-items:stretch'>
<div class='card col'><span class='badge pend'>Jika Cassandra gagal</span><br>saldo tetap benar &middot; event aman di outbox (PENDING) &middot; relay mengulang tiap 2 detik atau <code>POST /admin/outbox/relay</code></div>
<div class='card col'><span class='badge ok'>Jika client retry</span><br>idempotency key sama &rarr; <code>duplicate: true</code> &middot; saldo dan event tidak ganda</div>
<div class='card col'><span class='badge bad'>Trade-off</span><br>ledger bersifat eventual (beberapa ms&ndash;detik); saldo selalu konsisten. At-least-once + penulisan idempoten.</div></div>""")

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1240, "height": 800})
    for name, h in shots.items():
        pg.set_content(h); pg.wait_for_timeout(250)
        pg.locator("#w").screenshot(path=str(OUT / f"{name}.png")); print("OK", name)
    # UI asli
    pg2 = b.new_page(viewport={"width": 1366, "height": 800})
    pg2.goto(f"{API}/docs"); pg2.wait_for_timeout(2500); pg2.screenshot(path=str(OUT / "03_swagger.png")); print("OK 03_swagger")
    try:
        pg2.goto("http://localhost:8091/ui/index.html"); pg2.wait_for_timeout(2500)
        pg2.fill("input[name=username]", "Administrator"); pg2.fill("input[name=password]", "password")
        pg2.keyboard.press("Enter"); pg2.wait_for_timeout(4000)
        pg2.goto("http://localhost:8091/ui/index.html#!/buckets"); pg2.wait_for_timeout(3500)
        pg2.screenshot(path=str(OUT / "04_couchbase_ui_buckets.png")); print("OK 04_couchbase_ui_buckets")
        pg2.goto("http://localhost:8091/ui/index.html#!/query/workbench"); pg2.wait_for_timeout(3500)
        pg2.screenshot(path=str(OUT / "05_couchbase_ui_workbench.png")); print("OK 05_couchbase_ui_workbench")
    except Exception as e:
        print("Couchbase UI gagal:", e)
    b.close()

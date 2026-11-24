/* UI Query Explorer + Benchmark — JavaScript biasa, tanpa library eksternal. Semua panggilan lewat /api/* */
const $ = (s, r = document) => r.querySelector(s);
const el = (t, a = {}, ...k) => { const e = document.createElement(t); for (const [x, y] of Object.entries(a)) { if (x === 'class') e.className = y; else if (x.startsWith('on')) e.addEventListener(x.slice(2), y); else if (x === 'html') e.innerHTML = y; else if (y === false || y == null) { } else if (y === true) e.setAttribute(x, ''); else e.setAttribute(x, y); } k.flat().forEach(c => e.append(c?.nodeType ? c : document.createTextNode(c ?? ''))); return e; };
const BULAN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
const rp = v => 'Rp' + Number(v).toLocaleString('id-ID', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const ms = v => (v == null ? '-' : Number(v).toLocaleString('id-ID', { minimumFractionDigits: 3, maximumFractionDigits: 3 }) + ' ms');
function tgl(s) { const d = new Date(s); if (isNaN(d)) return s; const p = n => String(n).padStart(2, '0'); return `${p(d.getDate())} ${BULAN[d.getMonth()]} ${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`; }
function fmt(k, v) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'object') return JSON.stringify(v);
  if (/(saldo|nominal|bunga|total_nominal|rata_rata|total_saldo)/i.test(k) && !/sen$|periode|tarif|hari/i.test(k) && v !== '' && !isNaN(v)) return rp(v);
  if (/(waktu|_at$|tanggal_posting)/i.test(k) && /^\d{4}-\d\d-\d\dT/.test(v)) return tgl(v);
  if (/^tanggal/i.test(k) && /^\d{4}-\d\d-\d\d$/.test(v)) return tgl(v + 'T00:00:00').slice(0, 11);
  return String(v);
}
async function api(path, opt) { const r = await fetch(path, opt); let j = null; try { j = await r.json(); } catch { } if (!r.ok) { const e = j?.error || j?.detail || { message: 'HTTP ' + r.status }; throw Object.assign(new Error(e.message || JSON.stringify(e)), { code: e.code }); } return j; }
const post = (p, b) => api(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });

// ---------- tabs
document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#tabs button,.tab').forEach(x => x.classList.remove('active')); b.classList.add('active'); $('#tab-' + b.dataset.tab).classList.add('active');
  if (b.dataset.tab === 'status') loadStatus(); if (b.dataset.tab === 'benchmark') loadHistory(); });

// ---------- tabel + ekspor
function csvOf(rows) { if (!rows.length) return ''; const ks = Object.keys(rows[0]); const q = v => '"' + String(v ?? '').replace(/"/g, '""') + '"'; return [ks.map(q).join(','), ...rows.map(r => ks.map(k => q(typeof r[k] === 'object' ? JSON.stringify(r[k]) : r[k])).join(','))].join('\n'); }
function table(rows, name) {
  if (!rows.length) return el('div', { class: 'mut' }, 'Tidak ada baris.');
  let data = rows.slice(), dir = 1, key = null;
  const ks = Object.keys(rows[0]); const wrap = el('div');
  const tb = el('table');
  const render = () => {
    tb.innerHTML = '';
    const head = el('tr', {}, ks.map(k => el('th', { onclick: () => { dir = key === k ? -dir : 1; key = k; data.sort((a, b) => (a[k] > b[k] ? 1 : a[k] < b[k] ? -1 : 0) * dir); render(); } }, k + (key === k ? (dir > 0 ? ' ▲' : ' ▼') : ''))));
    tb.append(head);
    data.forEach(r => tb.append(el('tr', {}, ks.map(k => el('td', { title: String(typeof r[k] === 'object' ? JSON.stringify(r[k]) : (r[k] ?? '')) }, fmt(k, r[k]))))));
  };
  render();
  const dl = el('button', { class: 'sec', onclick: () => { const a = el('a', { href: URL.createObjectURL(new Blob([csvOf(rows)], { type: 'text/csv' })), download: (name || 'hasil') + '.csv' }); a.click(); } }, 'Ekspor CSV (yang ditampilkan)');
  wrap.append(dl, el('div', { class: 'tbl' }, tb)); return wrap;
}
function timingPanel(tm, avg) {
  const items = [['Total', tm.total_ms], ['Couchbase', tm.couchbase_ms], ['Cassandra', tm.cassandra_ms], ['Aplikasi', tm.app_ms]];
  if (tm.server_exec_ms != null) items.push(['Server exec (CB)', tm.server_exec_ms]);
  if (tm.ledger_visible_lag_ms != null) items.push(['Lag ledger', tm.ledger_visible_lag_ms]);
  const box = el('div', { class: 'tm' }, items.map(([l, v]) => el('div', {}, el('b', {}, ms(v)), el('span', {}, l))), el('div', {}, el('b', {}, (tm.rows_returned ?? 0).toLocaleString('id-ID')), el('span', {}, 'Baris')));
  if (avg != null) box.append(el('div', {}, el('b', {}, ms(avg)), el('span', {}, 'Rata-rata benchmark terakhir')));
  return box;
}
function errBox(e) { return el('div', { class: 'err' }, el('b', {}, 'Gagal: '), e.message, e.code ? el('div', { class: 'mut' }, 'kode: ' + e.code) : ''); }

// ---------- Status
async function loadStatus() {
  const box = $('#tab-status'); box.innerHTML = 'Memuat…';
  try {
    const s = await api('/api/status?refresh=true'); box.innerHTML = '';
    const db = (n, d, cls) => el('div', { class: 'card' }, el('h3', {}, n, ' ', el('span', { class: d.ok ? 'ok' : 'bad' }, d.ok ? '● terhubung' : '● gagal')), el('div', { class: 'mut' }, `versi ${d.versi ?? '-'} · ping ${d.ping_ms ?? '-'} ms`), d.error ? el('div', { class: 'bad' }, d.error) : '');
    const j = s.jumlah || {}; const n = x => (x ?? 0).toLocaleString('id-ID');
    box.append(el('div', { class: 'grid' }, db('Couchbase (main)', s.couchbase), db('Cassandra (event ledger)', s.cassandra),
      el('div', { class: 'card' }, el('h3', {}, 'Data seed (Couchbase)'), el('div', {}, `Nasabah: ${n(j.nasabah?.seed)}`), el('div', {}, `Rekening: ${n(j.rekening?.seed)}`), el('div', {}, `Kartu debit: ${n(j.kartu_debit?.seed)}`), el('div', { class: 'mut' }, `Data uji: ${n(j.rekening?.uji)} rekening, ${n(j.nasabah?.uji)} nasabah, ${n(j.kartu_debit?.uji)} kartu`)),
      el('div', { class: 'card' }, el('h3', {}, 'Event ledger (Cassandra)'), el('div', {}, `Total event: ${n(j.ledger_events)}`), el('div', { class: 'mut' }, `Dibuat via API: ${n(j.ledger_api)} · Python ${s.python}`)),
      el('div', { class: 'card' }, el('h3', {}, 'Outbox (sinkron ledger)'), el('div', {}, Object.entries(j.outbox || {}).map(([k, v]) => `${k}: ${n(v)}`).join(' · ') || 'kosong'), el('div', { class: s.simulasi_cassandra_mati ? 'bad' : 'ok' }, s.simulasi_cassandra_mati ? 'Simulasi Cassandra MATI aktif' : 'Relay normal'))));
    box.append(el('p', {}, el('button', { class: 'sec', onclick: async () => { if (confirm('Kembalikan data uji ke baseline? (menghapus data uji + event ledger-nya)')) { await post('/api/test-data/reset', {}); alert('Data uji dipulihkan.'); loadStatus(); } } }, 'Reset data uji'), ' ', el('span', { class: 'mut' }, 'Data uji: rekening 002999…, nasabah NSB99…, kartu 52299…')));
  } catch (e) { box.innerHTML = ''; box.append(errBox(e)); }
}

// ---------- Query Explorer
let QUERIES = [], BENCH_AVG = {};
async function loadBenchAvg() { try { const h = await api('/api/benchmark/results'); if (h.length) { const d = await api('/api/benchmark/results/' + h[0].file); BENCH_AVG = Object.fromEntries(d.hasil.map(r => [r.id, r.avg])); } } catch { } }
function card(q) {
  const inputs = {}; const form = el('div', { class: 'row' });
  q.params.forEach(p => { const i = p.type === 'select' ? el('select', {}, p.options.map(o => el('option', { value: o, selected: String(o) === String(p.default) }, o))) : el('input', { type: p.type === 'number' ? 'number' : p.type === 'date' ? 'date' : 'text', value: p.default, step: 'any', title: p.hint || '' }); inputs[p.name] = i; form.append(el('label', {}, p.label, i)); });
  const out = el('div'); const btn = el('button', { class: 'act' + (q.kind === 'W' ? ' w' : '') }, 'Jalankan');
  const params = () => Object.fromEntries(Object.entries(inputs).map(([k, i]) => [k, i.value]));
  btn.onclick = async () => {
    if (q.kind === 'W' && !confirm(`${q.id} MENGUBAH data (saran: data uji). Lanjutkan?\n\nSaya paham ini mengubah data uji.`)) return;
    btn.disabled = true; out.innerHTML = 'Menjalankan…';
    try {
      const r = await post(`/api/queries/${q.id}/run`, { params: params(), confirm: q.kind === 'W' }); const d = r.data; out.innerHTML = '';
      out.append(timingPanel(r.meta.timing, BENCH_AVG[q.id]));
      if (d.hasil?.message) out.append(el('div', { class: 'ok' }, '✔ ' + d.hasil.message));
      if (d.hasil?.saldo_sebelum) out.append(el('div', {}, 'Saldo sebelum → sesudah: ', Object.keys(d.hasil.saldo_sebelum).map(k => el('div', {}, `${k}: ${rp(d.hasil.saldo_sebelum[k])} → ${rp(d.hasil.saldo_sesudah[k])}`))));
      out.append(el('div', { class: 'mut' }, `Menampilkan ${d.baris.length} dari ${d.total_baris.toLocaleString('id-ID')} baris${d.dipotong ? ' (dipotong 100)' : ''}`), table(d.baris, q.id));
      if (q.kind === 'R' && d.total_baris === 0) out.append(el('div', { class: 'warn' }, 'Hasil kosong — periksa parameter atau data seed.'));
    } catch (e) { out.innerHTML = ''; out.append(errBox(e)); } btn.disabled = false;
  };
  const cp = el('button', { class: 'sec', onclick: () => navigator.clipboard.writeText(q.statement) }, 'Salin');
  return el('div', { class: 'card', id: 'q-' + q.id }, el('div', {}, el('span', { class: 'badge b-' + q.kind }, q.kind === 'R' ? 'READ' : 'WRITE'), el('span', { class: 'badge b-' + q.db }, q.db)), el('h3', {}, `${q.id} · ${q.title}`), el('div', { class: 'mut' }, q.desc), q.note ? el('div', { class: 'warn mut' }, 'Catatan: ' + q.note) : '', form, el('div', { class: 'row' }, btn, cp), el('details', {}, el('summary', {}, 'Statement (SQL++ / CQL)'), el('pre', {}, q.statement)), out);
}
async function initExplorer() { QUERIES = await api('/api/queries'); await loadBenchAvg(); const box = $('#tab-explorer'); box.append(el('p', { class: 'mut' }, 'Query READ aman dijalankan. Query WRITE hanya menyentuh data uji (rekening 002999…, NSB99…) dan meminta konfirmasi.'), el('h2', {}, 'Query Read (R-01 … R-10)'), el('div', { class: 'grid' }, QUERIES.filter(q => q.kind === 'R').map(card)), el('h2', {}, 'Query Write (W-01 … W-10)'), el('div', { class: 'grid' }, QUERIES.filter(q => q.kind === 'W').map(card))); }

// ---------- Benchmark
function chart(rows) {
  const mx = Math.max(...rows.map(r => r.avg || 0), 1); const col = { Couchbase: '#2563eb', Cassandra: '#7c3aed', Keduanya: '#0d9488' };
  const c = el('div', { class: 'chart' }); rows.forEach(r => { c.append(el('div', {}, r.id), el('div', {}, el('div', { class: 'bar', style: `width:${Math.max(1, 100 * (r.avg || 0) / mx)}%;background:${col[r.db]}` })), el('div', {}, ms(r.avg))); }); return c;
}
function benchTable(d) {
  const rows = d.hasil; const t = el('table'); t.append(el('tr', {}, ['ID', 'Deskripsi', 'DB', 'Runs (ms)', 'Min', 'Avg', 'Median', 'P95', 'Max', 'Rows', 'Pulih'].map(h => el('th', {}, h))));
  rows.forEach(r => t.append(el('tr', {}, el('td', {}, r.id), el('td', {}, r.title), el('td', {}, r.db), el('td', {}, (r.runs_ms || []).map(x => x.toFixed(2)).join(' · ')), ...['min', 'avg', 'median', 'p95', 'max'].map(k => el('td', {}, r[k] != null ? r[k].toFixed(3) : '-')), el('td', {}, r.rows ?? '-'), el('td', {}, r.pemulihan_baseline == null ? '' : el('span', { class: 'pill ' + (r.pemulihan_baseline ? 'p-ok' : 'p-bad') }, r.pemulihan_baseline ? 'ya' : 'GAGAL')))));
  const err = rows.filter(r => r.errors?.length); return el('div', {}, el('div', { class: 'tbl' }, t), err.length ? el('div', { class: 'err' }, err.map(r => el('div', {}, `${r.id}: ${r.errors[0]}`))) : '', el('h3', {}, 'Perbandingan rata-rata (ms) per query'), chart(rows));
}
async function loadHistory() { const box = $('#bench-history'); if (!box) return; try { const h = await api('/api/benchmark/results'); box.innerHTML = ''; if (!h.length) box.append(el('div', { class: 'mut' }, 'Belum ada riwayat.')); h.forEach(x => box.append(el('div', { class: 'row' }, el('span', {}, `${tgl(x.waktu)} · ${x.jumlah_query} query · ${x.runs} run`), el('button', { class: 'sec', onclick: async () => showResult(x.file) }, 'Lihat'), ...['csv', 'json', 'md'].map(f => el('a', { href: `/api/benchmark/results/${x.file}?format=${f}`, target: '_blank', class: 'sec', style: 'color:#93c5fd;text-decoration:none;padding:6px 8px' }, f.toUpperCase()))))); } catch { } }
async function showResult(file) { const d = await api('/api/benchmark/results/' + file); const o = $('#bench-out'); o.innerHTML = ''; o.append(el('div', { class: 'mut' }, `Lingkungan: ${tgl(d.lingkungan.waktu)} · Python ${d.lingkungan.python} · Couchbase ${d.lingkungan.couchbase_version ?? '-'} · Cassandra ${d.lingkungan.cassandra_version ?? '-'} · commit ${d.lingkungan.commit ?? '-'}`), benchTable(d), el('h3', {}, 'Tabel Markdown (siap tempel ke laporan)'), el('pre', {}, await (await fetch(`/api/benchmark/results/${file}?format=md`)).text())); }
function initBenchmark() {
  const box = $('#tab-benchmark'); const sel = {}; const checks = el('div', { class: 'row' });
  ['R-01', 'R-02', 'R-03', 'R-04', 'R-05', 'R-06', 'R-07', 'R-08', 'R-09', 'R-10', 'W-01', 'W-02', 'W-03', 'W-04', 'W-05', 'W-06', 'W-07', 'W-08', 'W-09', 'W-10'].forEach(id => { const c = el('input', { type: 'checkbox', style: 'min-width:0' }); c.checked = true; sel[id] = c; checks.append(el('label', { style: 'flex-direction:row;align-items:center;gap:4px' }, c, id)); });
  const set = f => Object.entries(sel).forEach(([id, c]) => c.checked = f(id));
  const runs = el('input', { type: 'number', value: 5, min: 1, max: 50 }), warm = el('input', { type: 'number', value: 1, min: 0, max: 5 }), conf = el('input', { type: 'checkbox', style: 'min-width:0' });
  const prog = el('div', { class: 'progress' }, el('div')); const info = el('div', { class: 'mut' }); const out = el('div', { id: 'bench-out' }); const go = el('button', { class: 'act' }, 'Mulai benchmark');
  go.onclick = async () => {
    const ids = Object.entries(sel).filter(([, c]) => c.checked).map(([i]) => i);
    if (ids.some(i => i.startsWith('W')) && !conf.checked) { alert('Centang konfirmasi: "Saya paham ini mengubah data uji" untuk menyertakan query WRITE.'); return; }
    go.disabled = true; out.innerHTML = ''; prog.firstChild.style.width = '0'; info.textContent = 'Memulai…';
    try { const { job_id } = await post('/api/benchmark', { ids, runs: +runs.value, warmup: +warm.value, confirm_write: conf.checked });
      const t = setInterval(async () => { const j = await api('/api/benchmark/jobs/' + job_id); prog.firstChild.style.width = j.progress + '%'; info.textContent = `${j.status} · ${j.progress}% · ${j.current || ''}`;
        if (j.status !== 'berjalan') { clearInterval(t); go.disabled = false; if (j.status === 'selesai') { await showResult(j.file); loadHistory(); loadBenchAvg(); } else out.append(errBox({ message: j.error || 'gagal' })); } }, 1000);
    } catch (e) { go.disabled = false; info.textContent = ''; out.append(errBox(e)); } };
  box.append(el('div', { class: 'card' }, el('h3', {}, 'Benchmark execution time'), el('div', { class: 'mut' }, 'Setiap query dijalankan N run + warm-up (tidak dihitung). Query WRITE dipulihkan ke baseline setelah tiap run (pemulihan tidak diukur).'),
    el('div', { class: 'row' }, el('button', { class: 'sec', onclick: () => set(i => i.startsWith('R')) }, 'Semua R'), el('button', { class: 'sec', onclick: () => set(i => i.startsWith('W')) }, 'Semua W'), el('button', { class: 'sec', onclick: () => set(() => true) }, 'Semua'), el('button', { class: 'sec', onclick: () => set(() => false) }, 'Kosongkan')), checks,
    el('div', { class: 'row' }, el('label', {}, 'Runs', runs), el('label', {}, 'Warm-up', warm), el('label', { style: 'flex-direction:row;align-items:center;gap:6px;color:#fbbf24' }, conf, 'Saya paham ini mengubah data uji (WRITE)'), go), prog, info), out,
    el('h3', {}, 'Riwayat benchmark'), el('div', { id: 'bench-history' }));
}

// ---------- Transaksi
function initTransaksi() {
  const box = $('#tab-transaksi'); const f = {};
  const mk = (k, label, v, type = 'text', opts) => { f[k] = opts ? el('select', {}, opts.map(o => el('option', { value: o }, o))) : el('input', { type, value: v }); return el('label', {}, label, f[k]); };
  const out = el('div'), hist = el('div'); let lastKey = '';
  const form = el('div', { class: 'row' }, mk('jenis', 'Jenis', '', 'text', ['setoran', 'penarikan', 'transfer']), mk('no_rekening', 'Rekening', '002999000000003'), mk('no_rekening_tujuan', 'Tujuan (transfer)', '002999000000004'), mk('nominal', 'Nominal (Rp)', 100000, 'number'), mk('idempotency_key', 'Idempotency key', ''));
  async function kirim(reuse) {
    if (!reuse || !f.idempotency_key.value) f.idempotency_key.value = 'ui-' + Math.random().toString(36).slice(2, 12);
    lastKey = f.idempotency_key.value; out.innerHTML = 'Mengirim…';
    try { const p = Object.fromEntries(Object.entries(f).map(([k, i]) => [k, i.value])); const r = await post('/api/queries/W-07/run', { params: p, confirm: true }); const d = r.data; const res = d.hasil.rows?.[0] ?? d.baris[0]; out.innerHTML = '';
      out.append(timingPanel(r.meta.timing), el('div', { class: res.duplicate ? 'warn' : 'ok' }, res.duplicate ? `⚠ DUPLIKAT terdeteksi (key sama) — saldo tidak berubah. event ${res.event_id}` : `✔ ${d.hasil.message} · event ${res.event_id}`), el('div', {}, `ledger: ${res.ledger_status} · saldo setelah: ${rp(res.saldo_setelah)}`), el('div', { class: 'mut' }, `Saldo sebelum → sesudah: ` + Object.keys(d.hasil.saldo_sebelum).map(k => `${k}: ${rp(d.hasil.saldo_sebelum[k])} → ${rp(d.hasil.saldo_sesudah[k])}`).join(' | ')));
      riwayat(); } catch (e) { out.innerHTML = ''; out.append(errBox(e)); } }
  async function riwayat() { try { const r = await post('/api/queries/R-01/run', { params: { no_rekening: f.no_rekening.value, tanggal_awal: '2025-11-01', tanggal_akhir: '2026-12-31' }, confirm: false }); hist.innerHTML = ''; hist.append(el('h3', {}, 'Riwayat rekening (R-01, Cassandra)'), timingPanel(r.meta.timing), table(r.data.baris.slice(0, 30).map(({ no_rekening, bulan, ...x }) => x), 'riwayat')); } catch (e) { hist.innerHTML = ''; hist.append(errBox(e)); } }
  box.append(el('div', { class: 'card' }, el('h3', {}, 'Setoran / Penarikan / Transfer (W-07)'), el('div', { class: 'mut' }, 'Memakai rekening uji. Kosongkan key untuk transaksi baru; "Kirim ulang" memakai key yang sama untuk mendemokan idempotensi.'), form,
    el('div', { class: 'row' }, el('button', { class: 'act w', onclick: () => kirim(false) }, 'Kirim'), el('button', { class: 'sec', onclick: () => { if (!lastKey) { alert('Kirim transaksi dulu.'); return; } f.idempotency_key.value = lastKey; kirim(true); } }, 'Kirim ulang dengan key yang sama'), el('button', { class: 'sec', onclick: riwayat }, 'Muat riwayat')), out), hist);
}

initExplorer().catch(e => $('#tab-explorer').append(errBox(e))); initBenchmark(); initTransaksi(); loadStatus();

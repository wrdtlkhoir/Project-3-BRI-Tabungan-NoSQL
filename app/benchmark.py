"""Benchmark: jalankan tiap query `runs` kali (+ warmup), hitung min/avg/median/p95/max, simpan JSON/CSV/Markdown.
Query tulis: tiap run -> jalankan -> pulihkan baseline (undo, TIDAK diukur) sehingga data uji tidak bergeser."""
import csv
import io
import json
import pathlib
import platform
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone

from app import query_catalog as qc
from app import timing

RESULT_DIR = pathlib.Path(__file__).resolve().parents[1] / "benchmark_results"
RESULT_DIR.mkdir(exist_ok=True)
JOBS: dict[str, dict] = {}


def _env_meta(svc) -> dict:
    meta = {"waktu": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(), "os": platform.platform()}
    try:
        meta["commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=RESULT_DIR.parent, timeout=5).stdout.strip() or None
    except Exception:
        meta["commit"] = None
    try:
        meta["cassandra_version"] = svc.ledger.s.execute("SELECT release_version FROM system.local").one()[0]
    except Exception:
        pass
    try:
        meta["couchbase_version"] = svc.cb.cluster.query("SELECT version() AS v").rows().__next__()["v"]
    except Exception:
        pass
    return meta


def _one(qid, params):
    """Satu eksekusi terukur; untuk W selalu undo setelah pengukuran."""
    q = qc.CAT[qid]
    try:
        r = qc.run_query(qid, params, confirm=True, undo=(q.kind == "W"))
        return {"ok": True, "timing": r["timing"], "restored": r["restored"]}
    except qc.BusinessError as e:
        return {"ok": False, "error": f"{e.code}: {e.message}"}
    except Exception as e:                       # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def run_job(job_id: str, ids: list[str], runs: int, warmup: int, params_by_id: dict, svc):
    job = JOBS[job_id]
    total_steps = len(ids) * (runs + warmup); done = 0
    results = []
    qc.ensure_test_data()
    for qid in ids:
        q = qc.CAT[qid]
        prm = (params_by_id or {}).get(qid, {})
        for _ in range(warmup):
            _one(qid, prm); done += 1; job["progress"] = round(100 * done / total_steps)
        runs_list, errors, restored_all = [], [], True
        for i in range(runs):
            r = _one(qid, prm); done += 1; job["progress"] = round(100 * done / total_steps)
            job["current"] = f"{qid} run {i + 1}/{runs}"
            if r["ok"]:
                runs_list.append(r["timing"]); restored_all &= bool(r["restored"] is not False)
            else:
                errors.append(r["error"])
        tot = [x["total_ms"] for x in runs_list]
        row = {"id": qid, "title": q.title, "kind": q.kind, "db": q.db, "runs_ms": tot, "runs_detail": runs_list, "errors": errors,
               "rows": runs_list[-1]["rows_returned"] if runs_list else None,
               "cold_ms": tot[0] if tot else None, "pemulihan_baseline": (restored_all if q.kind == "W" else None)}
        row.update(timing.stats(tot))
        if len(tot) > 1:
            row["avg_tanpa_cold"] = round(sum(tot[1:]) / (len(tot) - 1), 3)
        for k in ("couchbase_ms", "cassandra_ms", "app_ms", "server_exec_ms"):
            vals = [x[k] for x in runs_list if k in x]
            row[f"avg_{k}"] = round(sum(vals) / len(vals), 3) if vals else None
        results.append(row)
        job["partial"] = results
    out = {"id": job_id, "runs": runs, "warmup": warmup, "lingkungan": _env_meta(svc), "hasil": results}
    fn = RESULT_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{job_id[:6]}.json"
    json.dump(out, open(fn, "w", encoding="utf8"), indent=1, ensure_ascii=False, default=str)
    job.update({"status": "selesai", "progress": 100, "file": fn.name, "hasil": results})


def start(ids, runs, warmup, params_by_id, svc) -> str:
    jid = uuid.uuid4().hex
    JOBS[jid] = {"status": "berjalan", "progress": 0, "current": "", "ids": ids, "mulai": time.time()}

    def target():
        try:
            run_job(jid, ids, runs, warmup, params_by_id, svc)
        except Exception as e:                     # noqa: BLE001
            JOBS[jid].update({"status": "gagal", "error": f"{type(e).__name__}: {e}"})
    threading.Thread(target=target, daemon=True).start()
    return jid


def list_results() -> list[dict]:
    out = []
    for f in sorted(RESULT_DIR.glob("*.json"), reverse=True):
        try:
            d = json.load(open(f, encoding="utf8"))
            out.append({"file": f.name, "waktu": d["lingkungan"].get("waktu"), "runs": d["runs"], "jumlah_query": len(d["hasil"])})
        except Exception:
            pass
    return out


def load(file: str) -> dict:
    f = RESULT_DIR / pathlib.Path(file).name
    return json.load(open(f, encoding="utf8"))


COLS = ["id", "title", "db", "runs_ms", "min", "avg", "median", "p95", "max", "rows"]


def to_csv(d: dict) -> str:
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["ID", "Deskripsi", "Database", "Runs (ms)", "Min", "Avg", "Median", "P95", "Max", "Rows"])
    for r in d["hasil"]:
        w.writerow([r["id"], r["title"], r["db"], " | ".join(f"{x:.3f}" for x in r["runs_ms"]), r.get("min"), r.get("avg"), r.get("median"), r.get("p95"), r.get("max"), r.get("rows")])
    return buf.getvalue()


def to_md(d: dict) -> str:
    lines = ["| ID | Deskripsi | Database | Runs (ms) | Min | Avg | Median | P95 | Max | Rows |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in d["hasil"]:
        lines.append(f"| {r['id']} | {r['title']} | {r['db']} | {', '.join(f'{x:.2f}' for x in r['runs_ms'])} | {r.get('min')} | {r.get('avg')} | {r.get('median')} | {r.get('p95')} | {r.get('max')} | {r.get('rows')} |")
    env = d["lingkungan"]
    lines.append(f"\n_Lingkungan: {env.get('waktu')} · Python {env.get('python')} · Couchbase {env.get('couchbase_version')} · Cassandra {env.get('cassandra_version')} · commit {env.get('commit')} · {d['runs']} run + {d['warmup']} warmup_")
    return "\n".join(lines)

"""Muat semua data seed dari dump PostgreSQL (satu sumber) ke Couchbase + Cassandra."""
import os, pathlib, subprocess, sys
root = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault("CB_ALLOW_RELOAD", "1")
env = dict(os.environ)
env["PG_DSN"] = os.getenv("PG_DSN", "host=localhost port=5434 dbname=tabungan_bri user=postgres password=password")
env["CB_CONN_STR"] = os.getenv("COUCHBASE_CONN_STR", "couchbase://localhost")
steps = [[sys.executable, str(root / "scripts" / "init_cassandra.py")],
         [sys.executable, str(root / "infra" / "couchbase" / "load_couchbase_from_pg.py")],
         [sys.executable, str(root / "scripts" / "load_ledger.py")]]
for cmd in steps:
    print(">>", " ".join(pathlib.Path(c).name if c.endswith('.py') else c for c in cmd), flush=True)
    r = subprocess.run(cmd, env=env, cwd=root)
    if r.returncode:
        sys.exit(r.returncode)

"""BUILD INDEX Couchbase setelah data dimuat (index dibuat defer_build oleh cb_init.sh)."""
import pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.database.couchbase_db import get_cluster

cluster = get_cluster()
sql = pathlib.Path(__file__).resolve().parents[1].joinpath("infra/couchbase/build_indexes.n1ql").read_text(encoding="utf8")
for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
    stmt = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
    if stmt:
        try:
            list(cluster.query(stmt).rows())
            print("OK  ", stmt[:90])
        except Exception as e:
            print("SKIP", stmt[:70], "->", str(e)[:100])
time.sleep(5)
rows = list(cluster.query("SELECT name, state FROM system:indexes WHERE bucket_id='bri_tabungan'").rows())
for r in rows: print(r)

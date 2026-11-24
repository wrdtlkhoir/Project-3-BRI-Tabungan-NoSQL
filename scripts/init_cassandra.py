"""Buat keyspace + tabel Event Ledger (scripts/ledger.cql). Idempoten."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from cassandra.cluster import Cluster
try:
    from cassandra.io.asyncioreactor import AsyncioConnection as Conn
except Exception:
    Conn = None
from app.config import get_settings

s = get_settings()
kw = {"connection_class": Conn} if Conn else {}
cluster = Cluster([h.strip() for h in s.cassandra_hosts.split(",")], port=s.cassandra_port, **kw)
session = cluster.connect()
cql = (pathlib.Path(__file__).with_name("ledger.cql")).read_text(encoding="utf8")
for stmt in [x.strip() for x in cql.split(";") if x.strip()]:
    stmt = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
    if not stmt or stmt.upper().startswith("USE"):
        continue
    session.execute(stmt)
    if stmt.upper().startswith("CREATE KEYSPACE"):
        session.set_keyspace(s.cassandra_keyspace)
print("Event Ledger siap:", [r.table_name for r in session.execute(
    "SELECT table_name FROM system_schema.tables WHERE keyspace_name=%s", [s.cassandra_keyspace])])
cluster.shutdown()

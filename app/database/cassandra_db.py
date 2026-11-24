"""Koneksi Cassandra (Event Ledger). Session dibuat sekali dan dipakai bersama."""
from functools import lru_cache

from cassandra.cluster import Cluster
from cassandra.policies import DCAwareRoundRobinPolicy
from cassandra.query import ConsistencyLevel

# Python >= 3.12 tidak punya asyncore; pakai event loop asyncio bila tersedia.
try:  # pragma: no cover
    from cassandra.io.asyncioreactor import AsyncioConnection as _Conn
except Exception:  # pragma: no cover
    _Conn = None

from app.config import get_settings


@lru_cache
def get_cluster() -> Cluster:
    s = get_settings()
    kwargs = {"port": s.cassandra_port}
    if _Conn is not None:
        kwargs["connection_class"] = _Conn
    return Cluster([h.strip() for h in s.cassandra_hosts.split(",")], **kwargs)


@lru_cache
def get_session():
    s = get_settings()
    session = get_cluster().connect(s.cassandra_keyspace)
    session.default_timeout = 30
    session.default_consistency_level = ConsistencyLevel.ONE  # single node lokal; produksi: LOCAL_QUORUM
    return session

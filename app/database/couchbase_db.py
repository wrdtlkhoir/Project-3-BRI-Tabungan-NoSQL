"""Koneksi Couchbase (main database). Satu Cluster dipakai bersama (thread-safe)."""
from datetime import timedelta
from functools import lru_cache

from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.options import ClusterOptions, ClusterTimeoutOptions, TransactionConfig, WaitUntilReadyOptions
from couchbase.diagnostics import ServiceType
from couchbase.durability import ServerDurability, Durability

from app.config import get_settings


@lru_cache
def get_cluster() -> Cluster:
    s = get_settings()
    cfg = TransactionConfig(
        # single-node (replica 0): durability level 'none' cukup; di cluster produksi gunakan MAJORITY
        durability=ServerDurability(Durability.NONE),
        timeout=timedelta(seconds=15),
    )
    last = None
    for attempt in range(1, 6):                    # relay port Docker/WSL kadang lambat -> retry koneksi
        try:
            cluster = Cluster(
                s.couchbase_conn_str,
                ClusterOptions(PasswordAuthenticator(s.couchbase_username, s.couchbase_password),
                               transaction_config=cfg,
                               timeout_options=ClusterTimeoutOptions(connect_timeout=timedelta(seconds=20),
                                                                     kv_timeout=timedelta(seconds=10),
                                                                     query_timeout=timedelta(seconds=60))),
            )
            cluster.wait_until_ready(timedelta(seconds=30), WaitUntilReadyOptions(
                service_types=[ServiceType.KeyValue, ServiceType.Query]))
            return cluster
        except Exception as e:                      # noqa: BLE001
            last = e
    raise last


def get_scope():
    s = get_settings()
    return get_cluster().bucket(s.couchbase_bucket).scope(s.couchbase_scope)


def get_collection(name: str):
    return get_scope().collection(name)

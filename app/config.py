"""Konfigurasi aplikasi: semua koneksi dibaca dari environment / file .env
(tidak ada credential yang di-hardcode)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    couchbase_conn_str: str = "couchbase://localhost"
    couchbase_username: str = "Administrator"
    couchbase_password: str = "password"
    couchbase_bucket: str = "bri_tabungan"
    couchbase_scope: str = "operasional"

    cassandra_hosts: str = "127.0.0.1"
    cassandra_port: int = 9042
    cassandra_keyspace: str = "bri_ledger"

    pg_dsn: str = "host=localhost port=5434 dbname=tabungan_bri user=postgres password=password"

    # relay outbox -> Cassandra berjalan di background tiap N detik
    outbox_relay_interval: float = 2.0
    outbox_max_attempts: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()

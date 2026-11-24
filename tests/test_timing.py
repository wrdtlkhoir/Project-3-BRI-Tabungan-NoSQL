"""Unit test modul timing (tanpa database)."""
import time

from app import timing


def test_stats_min_avg_median_p95():
    s = timing.stats([10, 20, 30, 40, 50])
    assert s["min"] == 10 and s["max"] == 50 and s["avg"] == 30 and s["median"] == 30 and s["p95"] == 50


def test_stats_kosong():
    assert timing.stats([]) == {}


def test_measure_non_negatif_dan_total_ge_bagian():
    with timing.measure() as t:
        with timing.timed("cb"):
            time.sleep(0.01)
        with timing.timed("cass"):
            time.sleep(0.005)
        time.sleep(0.002)
    d = t.as_dict()
    assert d["couchbase_ms"] >= 9 and d["cassandra_ms"] >= 4
    assert d["total_ms"] >= d["couchbase_ms"] + d["cassandra_ms"] - 0.5
    assert d["app_ms"] >= 0 and all(v >= 0 for v in d.values() if isinstance(v, (int, float)))


def test_timed_bersarang_tidak_dihitung_dua_kali():
    with timing.measure() as t:
        with timing.timed("cb"):
            with timing.timed("cb"):
                time.sleep(0.01)
    assert t.as_dict()["couchbase_ms"] < 18          # ±10 ms, bukan ±20 ms


def test_di_luar_measure_aman():
    with timing.timed("cb"):
        pass
    timing.set_rows(5)
    timing.set_server_exec(1.0)

#!/bin/sh
# ============================================================================
#  Pulihkan dump PostgreSQL custom-format (cassandra/tabungan_bri.dump) ke
#  container PostgreSQL. Dijalankan sebagai container one-shot
#  `postgres-restore` di docker-compose.yml.
#
#  Idempoten: --clean --if-exists membuang objek lama sebelum memuat ulang.
#  Kalau dump ternyata berisi CREATE DATABASE, restore lewat maintenance DB
#  `postgres` dengan --create (sesuai SETUP_LOKAL.md §3).
# ============================================================================
set -u

DUMP="${DUMP:-/dump/tabungan_bri.dump}"
HOST="${PGHOST:-postgres}"
USER="${PGUSER:-postgres}"
export PGPASSWORD="${PGPASSWORD:-password}"

echo "[pg-restore] menunggu PostgreSQL di $HOST ..."
i=0
until pg_isready -h "$HOST" -U "$USER" -d postgres >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "[pg-restore] PostgreSQL tidak siap setelah $i percobaan"
    exit 1
  fi
  sleep 2
done

# Entri DATABASE di daftar TOC pg_restore tampil sebagai " DATABASE ".
if pg_restore -l "$DUMP" 2>/dev/null | grep -q ' DATABASE '; then
  echo "[pg-restore] dump berisi CREATE DATABASE -> restore ke maintenance db 'postgres'"
  TARGET="postgres"
  EXTRA="--create"
else
  echo "[pg-restore] dump tanpa CREATE DATABASE -> restore ke 'tabungan_bri'"
  TARGET="tabungan_bri"
  EXTRA=""
fi

# shellcheck disable=SC2086
pg_restore -h "$HOST" -U "$USER" -d "$TARGET" $EXTRA \
  --no-owner --clean --if-exists "$DUMP"
rc=$?
# pg_restore: 0 sukses, 1 peringatan (umumnya tidak fatal), >= 2 gagal.
if [ "$rc" -gt 1 ]; then
  echo "[pg-restore] GAGAL (exit $rc)"
  exit "$rc"
fi

echo "[pg-restore] verifikasi jumlah baris:"
psql -h "$HOST" -U "$USER" -d tabungan_bri -Atc \
  "SELECT 'nasabah='||count(*) FROM nasabah
   UNION ALL SELECT 'rekening='||count(*) FROM rekening_tabungan
   UNION ALL SELECT 'transaksi='||count(*) FROM transaksi_tabungan;"
echo "[pg-restore] selesai"

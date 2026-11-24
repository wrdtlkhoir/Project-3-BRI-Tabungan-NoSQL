#!/bin/sh
# ============================================================================
#  Inisialisasi Couchbase sekali jalan (container one-shot `couchbase-init`
#  di docker-compose.yml).
#
#  Urutan: tunggu server -> cluster-init -> bucket -> scope -> collection -> GSI.
#
#  Kenapa collection lewat couchbase-cli, bukan N1QL?
#  Community 7.6.x menolak `CREATE COLLECTION` lewat N1QL dengan
#  "maxTTL:Supported in enterprise edition only". `collection-manage` di
#  couchbase-cli tetap jalan di CE.
#
#  Semua langkah idempoten + menunggu kesiapan, supaya `docker compose up`
#  boleh diulang dan tidak balapan dengan node yang baru menyala.
# ============================================================================
set -u

HOST="${CB_HOST:-couchbase:8091}"          # host:port untuk couchbase-cli
HOST_ONLY="${HOST%%:*}"                    # host saja untuk connection string cbq
USER="${CB_USER:-Administrator}"
PASS="${CB_PASS:-password}"
BUCKET="${CB_BUCKET:-bri_tabungan}"
SCOPE="operasional"
CLI="couchbase-cli"
CBQ="cbq -u $USER -p $PASS -e http://$HOST_ONLY:8093"

wait_http() {
  echo "[cb-init] menunggu Couchbase di $HOST ..."
  i=0
  until wget -q -O /dev/null "http://$HOST/ui/index.html" 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -ge 60 ]; then
      echo "[cb-init] Couchbase tidak siap setelah $i percobaan"
      exit 1
    fi
    sleep 5
  done
}

ensure_cluster() {
  if $CLI server-list -c "$HOST" -u "$USER" -p "$PASS" >/dev/null 2>&1; then
    echo "[cb-init] cluster sudah diinisialisasi"
    return 0
  fi
  echo "[cb-init] cluster-init"
  i=0
  until $CLI cluster-init -c "$HOST" -u "$USER" -p "$PASS" \
        --cluster-username "$USER" --cluster-password "$PASS" \
        --services data,index,query \
        --cluster-ramsize 1536 --cluster-index-ramsize 512 >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 24 ]; then
      echo "[cb-init] gagal cluster-init setelah $i percobaan"
      return 1
    fi
    echo "[cb-init]   ... menunggu node siap"
    sleep 5
  done
}

ensure_bucket() {
  echo "[cb-init] bucket $BUCKET"
  i=0
  while :; do
    if $CLI bucket-list -c "$HOST" -u "$USER" -p "$PASS" 2>/dev/null | grep -q "$BUCKET"; then
      echo "[cb-init] bucket sudah ada"
      return 0
    fi
    # --bucket-replica 0 WAJIB pada single-node kalau mau transaksi ACID.
    if $CLI bucket-create -c "$HOST" -u "$USER" -p "$PASS" \
         --bucket "$BUCKET" --bucket-type couchbase --bucket-ramsize 768 \
         --bucket-replica 0 --wait >/dev/null 2>&1; then
      echo "[cb-init] bucket dibuat"
      return 0
    fi
    i=$((i + 1))
    if [ "$i" -ge 12 ]; then
      echo "[cb-init] gagal membuat bucket setelah $i percobaan"
      return 1
    fi
    sleep 5
  done
}

ensure_scope() {
  echo "[cb-init] scope $SCOPE"
  i=0
  until $CBQ -s="CREATE SCOPE \`$BUCKET\`.\`$SCOPE\` IF NOT EXISTS;" >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 12 ]; then
      echo "[cb-init] gagal membuat scope setelah $i percobaan"
      return 1
    fi
    echo "[cb-init]   ... menunggu Query Service"
    sleep 5
  done
}

ensure_collections() {
  echo "[cb-init] collections"
  for c in produk unit_kerja kanal nasabah rekening kartu_debit posting_bunga instruksi_terjadwal outbox; do
    $CLI collection-manage -c "$HOST" -u "$USER" -p "$PASS" \
      --bucket "$BUCKET" --create-collection "$SCOPE.$c" >/dev/null 2>&1 \
      || echo "[cb-init] collection $c sudah ada (dilewati)"
  done
}

wait_http
ensure_cluster || exit 1
ensure_bucket  || exit 1
ensure_scope   || exit 1
ensure_collections

echo "[cb-init] membuat GSI (defer_build, di-BUILD setelah data dimuat)"
$CBQ -f /cb/couchbase_indexes.n1ql

echo "[cb-init] selesai"

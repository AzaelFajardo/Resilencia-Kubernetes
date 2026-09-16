#!/usr/bin/env bash
# Show replication health: recovery state + data parity for primary and replica.
# Usage: scripts/postgres_replication_status.sh
set -euo pipefail

PGDATA=/var/lib/postgresql/data/pgdata
COUNT_SQL='SELECT count(*) FROM orders'

echo "== postgres (primary label) =="
kubectl exec deploy/postgres -- sh -c "export PGPASSWORD=resilencia_secret; psql -U resilencia -d resilencia_db -h localhost -c 'SELECT pg_is_in_recovery() AS in_recovery;' && echo -n 'orders on primary: ' && psql -U resilencia -d resilencia_db -h localhost -Atc '$COUNT_SQL'"

echo "== postgres-replica =="
kubectl exec deploy/postgres-replica -- sh -c "export PGPASSWORD=resilencia_secret; psql -U resilencia -d resilencia_db -h localhost -c 'SELECT pg_is_in_recovery() AS in_recovery;' && echo -n 'orders on replica: ' && psql -U resilencia -d resilencia_db -h localhost -Atc '$COUNT_SQL'"

echo "== wal senders on primary =="
kubectl exec deploy/postgres -- sh -c "export PGPASSWORD=resilencia_secret; psql -U resilencia -d resilencia_db -h localhost -Atc \"SELECT application_name, state, sync_state FROM pg_stat_replication;\""
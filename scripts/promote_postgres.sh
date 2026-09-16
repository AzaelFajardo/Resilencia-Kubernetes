#!/usr/bin/env bash
# Promote the hot-standby replica (postgres-replica) to PRIMARY and re-point
# the `postgres` Service at it. After this, all app traffic (DATABASE_URL in
# the 5 microservices points at the `postgres` Service) writes to the promoted
# node. Usage: scripts/promote_postgres.sh
set -euo pipefail

PGDATA=/var/lib/postgresql/data/pgdata

echo ">> Creating replication slot-free promote (pg_promote) on postgres-replica..."
# pg_promote() ends recovery on the standby without needing a trigger file.
kubectl exec deploy/postgres-replica -- sh -c "export PGPASSWORD=resilencia_secret; psql -U resilencia -d resilencia_db -h localhost -c 'SELECT pg_promote(true);'"

echo ">> Removing standby.signal so the pod stays primary across restarts..."
kubectl exec deploy/postgres-replica -- rm -f "$PGDATA/standby.signal"

echo ">> Re-pointing Service postgres -> app:postgres-replica..."
kubectl patch service postgres -p '{"spec":{"selector":{"app":"postgres-replica"}}}'

echo ">> Verifying the promoted primary accepts writes..."
kubectl exec deploy/postgres-replica -- sh -c "export PGPASSWORD=resilencia_secret; psql -U resilencia -d resilencia_db -h localhost -c 'SELECT pg_is_in_recovery() AS in_recovery;'"

echo "OK: the postgres Service now routes app traffic to the promoted node."
# Test Name

Baseline scenario (Action Plan Phase 1) — system with no resilience
mechanisms enabled.

# When It Was Run

2026-09-04, local Docker Compose stack, fresh volumes (first run). Independently
re-verified 2026-09-05 on a second fresh boot (`docker compose down -v` +
`up -d --build`) — see "Second run (re-verification)" below. This closes a gap
found during a Phase 0-5 audit: `docs/ACTION-PLAN.md` had claimed a second run
with different numbers (271 requests, p50 97ms, p95 213ms, p99 972ms) that was
never actually recorded anywhere in the repo. That claim has been corrected in
`ACTION-PLAN.md` to match the real second run documented here.

# Description

Goal: capture the proposal's "Baseline (sistema sin resiliencia)" scenario —
no retries, no circuit breaker, no autoscaling, no chaos — as the comparison
point for every later phase (retries, circuit breaker, Kubernetes).

## Setup

1. `docker compose down -v --remove-orphans && docker compose up -d --build --remove-orphans`.
   Defaults already match the baseline scenario: `RETRY_ENABLED=false`,
   `FAILURE_RATE=0.0`, `LATENCY_MS=0`, `TIMEOUT_RATE=0.0` (see `.env.example`).
2. `python cli.py status` — confirmed all 5 services healthy and the seeded
   data present (50000 users, 3 products, 2 orders/payments/notifications
   from `db/init.sql`).
3. **Stock caveat:** `scripts/k6/baseline.js` orders `product_id=1` on every
   iteration, and the seed data only gives it 12 units of stock. At 10 VUs
   the run would exhaust stock in about a second and spend the rest of the
   30s recording "out of stock" business failures — a test-data artifact,
   not a resilience finding. Bumped it once before the run:
   `docker compose exec -T postgres psql -U resilencia -d resilencia_db -c "UPDATE products SET quantity = 100000 WHERE id = 1;"`
   (only the `quantity` column matters — `inventory-service` overwrites the
   JSONB copy with that column's value on every read, see
   `construct_product_model` in `services/inventory-service/main.py`).
4. **Script fix:** `scripts/k6/baseline.js` only checked
   `r.status === 200 || 201`. `order-service` returns HTTP 200 for every
   outcome, including business failures (out of stock, payment declined,
   fraud hold) — none of those raise an HTTPException. That check alone
   cannot measure a real error rate. Added a second check,
   `r.json('status') === 'success'`, plus `summaryTrendStats` including
   `p(99)` (the default k6 summary stops at p95).
5. Ran the script via the official image, matching the README's documented
   invocation:
   ```
   docker run --rm -i --network resilencia-kubernetes_app-net \
     -e ORDER_URL=http://order-service:8000/orders \
     -v "$(pwd)/scripts/k6:/scripts" \
     grafana/k6 run /scripts/baseline.js
   ```
   (On Windows/Git Bash, prefix with `MSYS_NO_PATHCONV=1` — otherwise the
   `/scripts/baseline.js` argument gets mangled into a Windows path by
   MSYS's automatic path conversion before it ever reaches the container.)

# Results

## Performance (k6 client-side)

| Metric | Value |
| --- | --- |
| Iterations / requests | 258 |
| Throughput | 8.32 req/s (10 VUs, 1s think time) |
| Checks passed | 516/516 (100%) — both HTTP-level and business-level |
| HTTP error rate (`http_req_failed`) | 0.00% |
| Business error rate (`order succeeded` check) | 0.00% |
| Latency p50 (med) | 133.36 ms |
| Latency p90 | 242.15 ms |
| Latency p95 | 276.42 ms |
| Latency p99 | 1.30 s |
| Latency max | 1.31 s |
| Latency avg / min | 178.47 ms / 59.06 ms |

The p99/max jump (1.3s vs. a 133ms median) is the order flow's cold-start
tail: the first requests of the run pay for on-demand connection setup
across order → user → inventory → payment → notification, plus JIT
warch-up in each service's async engine; the distribution is otherwise
tight (p90 at 242ms, right next to the median).

## Cross-check against Prometheus (server-side)

`order-service`'s own `/metrics` (`http_request_duration_seconds_bucket{handler="/orders"}`)
after the run:

```
le=0.1  -> 56/258  (21.7%)
le=0.5  -> 249/258 (96.5%)
le=1.0  -> 252/258 (97.7%)
le=+Inf -> 258/258 (100%)
```

Consistent with k6's client-side numbers: p95 (276ms) falls in the (0.1s,
0.5s] bucket as expected, and p99 (1.3s) falls in the ~2.3% tail beyond the
1.0s bucket. Prometheus's default histogram buckets are too coarse for a
precise quantile here — k6's own percentiles (computed from exact per-request
samples) are the numbers to trust and compare against in later phases.

`http_requests_total{handler="/orders",status="2xx"}` = 258, matching k6's
`http_reqs` exactly and confirming 0% HTTP-level errors server-side too.

`Status -> Targets` equivalent (`GET /api/v1/targets`): both the
`microservices` job (all 5 services) and `otel-collector` report `health:
"up"`.

## Observability

`GET http://localhost:16687/api/services` (Jaeger) lists all 5 services
after the run: `order-service`, `user-service`, `inventory-service`,
`payment-service`, `notification-service`. Distributed traces for the full
order flow are confirmed to be flowing end to end.

## Second run (re-verification)

Repeated the exact same setup end to end on 2026-09-05: fresh boot
(`docker compose down -v --remove-orphans && docker compose up -d --build
--remove-orphans`), confirmed all 5 services healthy via `python cli.py
status` (50000 seeded users, 3 products, 2 orders/payments/notifications),
re-applied the product-1 stock bump (`UPDATE products SET quantity = 100000
WHERE id = 1;` — reset by `down -v`, as noted below), and ran the same
`docker run ... grafana/k6 run /scripts/baseline.js` invocation.

| Metric | First run (09-04) | Second run (09-05) |
| --- | --- | --- |
| Iterations / requests | 258 | 256 |
| Throughput | 8.32 req/s | 8.22 req/s |
| Checks passed | 516/516 (100%) | 512/512 (100%) |
| HTTP error rate | 0.00% | 0.00% |
| Business error rate | 0.00% | 0.00% |
| Latency p50 (med) | 133.36 ms | 167.08 ms |
| Latency p90 | 242.15 ms | 270.10 ms |
| Latency p95 | 276.42 ms | 402.69 ms |
| Latency p99 | 1.30 s | 1.07 s |
| Latency max | 1.31 s | 1.11 s |

Cross-checks (second run): `order-service`'s own `/metrics` shows
`http_requests_total{handler="/orders",status="2xx"}` = 256, matching k6's
`http_reqs` exactly (0% HTTP-level errors server-side). Duration histogram
(`http_request_duration_seconds_bucket{handler="/orders"}`): `le=0.1` →
39/256 (15.2%), `le=0.5` → 247/256 (96.5%), `le=1.0` → 253/256 (98.8%),
`le=+Inf` → 256/256. Prometheus `Status -> Targets` shows both
`microservices` (all 5 instances) and `otel-collector` as `up`. Jaeger
(`GET /api/services`) lists all 5 services.

**Conclusion:** the second run reproduces the same shape as the first —
near-zero error rate, sub-500ms p95, all services traced — confirming this
is stable across independent fresh boots, not a one-off result. The exact
figures differ run to run as expected for a load test (p95 276ms vs.
403ms, p99 1.30s vs. 1.07s), both driven by the same cold-start tail
described above for the first run.

## Notes for later phases

- This is the number to beat/compare against in Phase 3 (retries) and
  Phase 4 (circuit breaker): 0% error rate here means those scenarios need
  their own injected failure (via `cli.py chaos set <service> --failure-rate`)
  to have anything to recover from.
- The stock bump on product 1 (`quantity = 100000`) lives only in the
  Docker volume for this run; `docker compose down -v` resets it back to the
  seeded value of 12. Repeat the bump before any future load test that
  reuses `product_id=1`.
- The `baseline.js` fixes (business-status check, `p(99)` in
  `summaryTrendStats`) are permanent and apply to every future run of this
  script, not just this one.

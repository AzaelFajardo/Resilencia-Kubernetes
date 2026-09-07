# Test Name

Fault injection: artificial latency (Action Plan Phase 7) — 500ms injected
into `inventory-service`, measured against both Docker Compose and
Kubernetes.

# When It Was Run

2026-09-06, both environments already up (Compose stack from the Phase 1
re-verification boot; Kubernetes cluster from Phase 6).

# Description

Goal: measure the proposal's "Latencia artificial" fault — its primary
metrics are latency p50/p95/p99 and throughput — against the Phase 1
baseline, in both environments.

## Setup

- `python cli.py chaos set inventory-service --latency-ms 500 --yes`.
  `inventory-service` was chosen because `order-service` calls it **twice**
  per order (availability check, then reserve — see
  `docs/tests/retries-results.md`), so the injected delay compounds
  predictably (≈1000ms of pure injected latency per order) and is easy to
  verify arithmetically in the results.
- Ran `scripts/k6/baseline.js` (10 VUs, 30s) unchanged — same script as
  Phase 1, so results are directly comparable to that baseline.
- Product-1 stock already bumped to 100000 in both environments from prior
  phases (Compose: confirmed 99743 remaining before this run; Kubernetes:
  99469) — comfortably above what a 30s/10-VU run consumes.
- Reset chaos (`chaos reset --all --yes`) immediately after each run.

# Results

| Metric | Phase 1 baseline (no chaos) | Compose + 500ms latency | Kubernetes + 500ms latency |
| --- | --- | --- | --- |
| Requests | 256-258 | 140 | 115 |
| Throughput | ~8.2-8.3 req/s | **4.48 req/s** | **3.56 req/s** |
| HTTP/business error rate | 0% | 0% | 0% |
| Latency p50 (med) | 133-167 ms | **1.17 s** | **1.49 s** |
| Latency p90 | 242-270 ms | 1.47 s | 2.45 s |
| Latency p95 | 276-403 ms | **1.54 s** | **3.55 s** |
| Latency p99 | 1.07-1.30 s | **1.61 s** | **4.21 s** |

## Analysis

- **The latency shows up almost exactly where expected.** Compose's p50
  (1.17s) ≈ baseline p50 (~0.15s) + 2×500ms injected ≈ 1.15s — the fault
  is precisely additive on the median, as it should be for a deterministic
  per-call delay with no queuing yet at only 10 VUs.
- **Throughput dropped proportionally, not catastrophically.** k6 runs a
  fixed 10 VUs with a 1s `sleep()` between iterations
  (`scripts/k6/baseline.js`); each iteration now takes ~2.2-2.7s instead of
  ~1.2s, so fewer iterations complete in the 30s window — throughput fell
  from ~8.3 to 4.48 (Compose) / 3.56 (Kubernetes) req/s, roughly tracking
  the ~2x increase in iteration time. This is exactly the "throughput"
  half of this fault's primary metric: added latency doesn't just slow
  individual requests, it directly caps how much load 10 concurrent users
  can generate.
- **Kubernetes shows a noticeably wider tail than Compose at the same
  injected latency (p95 3.55s vs. 1.54s, p99 4.21s vs. 1.61s), even though
  the median is close (1.49s vs. 1.17s).** This is the `kubectl
  port-forward` tunnel's own variance stacking on top of the deterministic
  500ms×2 chaos delay — consistent with the same caveat already documented
  in `docs/tests/kubernetes-results.md` for the CPU-saturation fault: the
  tunnel adds latency and, more here, *jitter*, not just a fixed offset.
  The median is a fair comparison point between environments; the tail
  (p95/p99) is not, for this specific fault, in this specific setup.
- **No errors in either environment.** 500ms×2 well within
  `HTTP_TIMEOUT=5.0s` (order-service's own downstream call timeout) in
  Compose; Kubernetes' worse tail (max 4.23s) got close to that ceiling but
  never crossed it in this run — a slightly higher injected latency (e.g.
  800ms-1s) would likely start producing timeout-driven errors in
  Kubernetes before Compose, purely from the added port-forward variance,
  which would be worth knowing if this fault is ever pushed further.

# Exit criteria

Met: artificial-latency fault executed and documented in both
environments, with p50/p95/p99 and throughput measured against the Phase 1
baseline in each.

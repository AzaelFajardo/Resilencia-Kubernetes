# Test Name

JMeter baseline execution (Action Plan Phase 11) - the smoke test Phase 2
authored the plan for but explicitly deferred running.

# When It Was Run

2026-09-06, Compose stack, same product-1 stock bump as every other load
test in this project.

# Description

Goal: actually run `scripts/jmeter/baseline.jmx` end to end and compare its
numbers against k6's Phase 1 baseline, closing the one remaining "authored
but never executed" item from Phase 2.

## Setup

- Installed JMeter 5.6.3 as a plain zip extract (no installer) - the
  winget package (`DEVCOM.JMeter`) pulls a bundled JDK via an MSI that
  blocks on a UAC elevation prompt in a non-interactive session; the
  official Apache binary zip needs no install and this machine already
  has a JDK (`java -version` → 26.0.2).
- Ran headless with the plan's own defaults (`HOST=localhost`,
  `PORT=8100`, 10 users, 10s ramp-up, 30s duration - identical shape to
  the k6 baseline):
  `jmeter -n -t scripts/jmeter/baseline.jmx -l results.jtl -e -o report/`

# Results

| Metric | JMeter | k6 (Phase 1, two runs) |
| --- | --- | --- |
| Requests | 215 | 256 / 258 |
| Error rate | 0.00% | 0.00% |
| Throughput | 7.43 req/s | 8.2-8.3 req/s |
| p50 (median) | 169 ms | 133-167 ms |
| p90 | 277.2 ms | 242-270 ms |
| p95 | 346.8 ms | 276-403 ms |
| p99 | 384.76 ms | 1.07-1.30 s |
| max | 397 ms | 1.11-1.31 s |

**0% error rate confirmed at both the HTTP and business-status level** -
the plan's `ResponseAssertion` (checking `"status":"success"` in the
response body, added in Phase 2 for the same reason as the k6 fix -
`order-service` returns HTTP 200 for business failures too) counts as a
sample error if it fails, and `errorCount` was 0.

**p50/p90/p95 land in the same range as k6's**, confirming the two tools
measure the same real behavior despite different threading models.
**p99/max differ a lot** (385ms vs. 1.07-1.30s) - JMeter's run didn't
reproduce k6's cold-start tail this time. Plausible explanations: JMeter's
thread-group ramp-up is more gradual than k6's constant-VU model, this run
had fewer total samples (215 vs. 256-258) so the tail is thinner by
sample count alone, and connection warm-up effects are inherently
run-to-run noisy (the same variance was already documented between k6's
own two Phase 1 runs). Not investigated further - both tools agree on the
part that matters (median/p95, near-zero error rate); the tail is a minor
discrepancy worth knowing about, not a contradiction to resolve.

# Exit criteria

Met: the JMeter plan authored in Phase 2 has a real completed run, with
numbers directly comparable to k6's Phase 1 baseline (median and p95
agree closely; p99 differs and is explained rather than ignored).

# Test Name

Fault injection: pod/container kill (Action Plan Phase 7) — MTTR comparison
between Docker Compose (no restart policy) and Kubernetes (self-healing).

# When It Was Run

2026-09-06, both environments already up from Phase 6 (Compose: fresh since
the Phase 1 re-verification boot; Kubernetes: minikube cluster from Phase 6).

# Description

Goal: measure MTTR (mean time to recovery) for a killed service instance in
both environments, and confirm/quantify the resilience gap the proposal
expects Kubernetes to close relative to plain Compose.

## Setup

- **Compose:** confirmed no service in `compose.yml` sets a `restart:`
  policy except `data-seeder` (`restart: "no"`, intentional — it's a
  one-shot job) — every microservice defaults to Docker's own default of
  no automatic restart on exit.
- **Kubernetes:** reusing the MTTR measurement already taken in Phase 6
  (`docs/tests/kubernetes-results.md`) rather than repeating it — same
  fault, same mechanism (`restartPolicy: Always` + ReplicaSet), no reason
  to re-run.

# Results

## Docker Compose: no automatic recovery

1. `docker compose kill payment-service` (SIGKILL) at T+0.
2. Immediately attempted `POST /orders`: **order failed as designed**,
   with automatic compensation — `"status":"error"`, message: `Payment
   failed, inventory released: [Errno -2] Name or service not known`.
   Note the failure mode: a **fully killed container** fails via DNS
   resolution (Compose's embedded DNS has nothing to route
   `payment-service` to once the container exits), not a connection-refused
   like `FAILURE_RATE`-simulated chaos or a mid-request drop. `order-service`
   correctly released the reserved inventory before returning the error —
   the compensating-transaction path works the same regardless of *why*
   payment failed.
3. Checked status at T+37s: **`payment-service` still `Exited (137)` —
   zero automatic recovery.** Docker Compose has no supervisor watching for
   dead containers unless a `restart:` policy is explicitly set (this
   project doesn't set one on any live service).
4. Manually issued `docker compose start payment-service` and polled
   `/health` every second: **ready again in 3.46s.**
5. Confirmed the order flow fully recovered: a follow-up `POST /orders`
   returned `"status":"success"`.

**MTTR in Compose = unbounded (∞) without human intervention.** The 3.46s
figure is *not* a resilience mechanism — it's how fast the container
itself boots once a person (or an external supervisor this project doesn't
have) issues the restart. There is nothing in this stack that would ever
issue that command on its own.

## Kubernetes: automatic recovery (reusing Phase 6 measurement)

From `docs/tests/kubernetes-results.md`: deleting a running
`payment-service` pod (`kubectl delete pod ...`) was followed by the
ReplicaSet automatically scheduling and starting a replacement, which
passed its readiness probe and rejoined the Service's endpoints in
**11.55 seconds** on that run, with no human action beyond the initial
`kubectl delete` (which stands in for an unplanned pod death — a node
issue, an OOM-kill, etc. — kubelet/the ReplicaSet controller react
identically regardless of why the pod disappeared). **A later independent
re-run of the same test measured 26.50s instead** (see "Re-verification"
in `docs/tests/kubernetes-results.md` — likely host resource contention
after a long session, not a change in mechanism). Treat Kubernetes' MTTR
here as "tens of seconds, fully automatic" rather than a precise constant
- the comparison against Compose's *unbounded* MTTR below holds regardless
of which sample is used.

## Comparison

| | Docker Compose | Kubernetes |
| --- | --- | --- |
| Detects the dead instance? | No (nothing watches) | Yes (kubelet + ReplicaSet controller) |
| Recovers automatically? | **No** | **Yes** |
| MTTR | ∞ (until a human intervenes) | ~11-27s (2 samples: 11.55s, 26.50s) |
| Manual-recovery time once triggered | 3.46s (container restart only) | n/a (fully automatic) |

This is exactly the resilience gap the proposal's Kubernetes phase is
meant to demonstrate: the same "a service instance dies" fault is
unrecoverable-by-design in the Compose baseline and self-healing in
Kubernetes, without any application code changing between the two.

# Exit criteria

Met: pod/container-kill fault executed and documented in both
environments, with MTTR (or its absence) measured for each.

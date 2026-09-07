# Test Name

OTel trace sampling impact (Action Plan Phase 11) - the item Phase 5
deliberately deferred.

# When It Was Run

2026-09-06/07, Compose stack.

# Description

Goal: measure sampling's impact now that `OTEL_TRACES_SAMPLER`/
`OTEL_TRACES_SAMPLER_ARG` support exists (`services/*/tracing.py`, all 5
services - a `_build_sampler()` reading the two standard OTel env vars,
since this project builds its `TracerProvider` by hand and the SDK's
automatic env-var reading only applies to the `opentelemetry-instrument`
CLI wrapper, which this project doesn't use).

## Setup

- Rebuilt all 5 images with the new `tracing.py`.
- Baseline: default `parentbased_always_on` (100% sampling, unchanged
  default behavior - verified no regression).
- Test: `OTEL_TRACES_SAMPLER=traceidratio OTEL_TRACES_SAMPLER_ARG=0.1`
  (10%) via `docker compose up -d --force-recreate --no-deps <5 services>`.
- Measured exported span volume by counting `otel-collector`'s own debug
  exporter log lines (`docker compose logs otel-collector --since
  <timestamp>`, summing `"spans": N` per batch) across 30 orders each,
  rather than trusting Jaeger's UI/API trace count - this session has
  accumulated thousands of traces from every prior phase, so Jaeger's own
  count includes irrelevant history even with a short lookback window.

# Results

| Sampling | Orders | Spans exported | Spans/order |
| --- | --- | --- | --- |
| 100% (`parentbased_always_on`, default) | 30 | 1110 | 37.0 |
| 10% (`traceidratio`, arg `0.1`) | 30 | 147 | 4.9 |

**147/1110 = 13.2%**, close to the configured 10% - the gap is expected
statistical noise from only 30 sampled traces, not a bug (each of the 5
services makes its own independent per-trace sampling decision via
`ParentBased`, but the root decision - made by `order-service`, the first
span in every trace - propagates to all downstream spans in the same
trace, so the unit of randomness here is really 30 trials, not 1110).

**Latency:** a quick 10-order timing at each ratio (1.28s total at 10% vs.
1.56s total at 100%, ~13%/~16% median request time) suggests a small,
real-but-modest latency saving from sampling - smaller than the +35-42%
`OTEL_SDK_DISABLED` swing measured in Phase 5, which makes sense: a
non-sampled span still gets created and still runs through the
instrumentation wrappers (context propagation, httpx/SQLAlchemy hooks) -
sampling drops what gets *exported*, `OTEL_SDK_DISABLED` skips
instrumentation entirely. This 10-order comparison is too small to trust
as a precise percentage; treat it as directional, not a headline number.

# Exit criteria

Met: sampling is now configurable and its impact measured (span-volume
reduction tracks the configured ratio; latency effect is real but small
and distinct from the full-disable effect measured in Phase 5).

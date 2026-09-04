# JMeter test plan usage

`scripts/jmeter/baseline.jmx` is the concurrent-user counterpart to
`scripts/k6/baseline.js` (Action Plan Phase 2): same request
(`POST /orders`, `{"user_id":1,"product_id":1,"quantity":1}`), same 1s think
time between iterations, same idea of "no resilience mechanisms enabled".
k6 stays the primary tool for the automated comparisons in later phases
(retries, circuit breaker); this plan exists so the team also has a
concurrent-user-style test available, as the proposal asks for both tools.

**This plan has been authored but not executed.** Per the project's rules,
JMeter itself is not installed as part of this phase — installing it and
running the full experiment suite belongs to whoever executes Phase 3
onward. Before trusting it for real numbers, open it once in the JMeter GUI
(or run a short headless smoke test) to confirm it behaves as described
here.

## Parameters

All of these are JMeter "User Defined Variables" backed by `__P(name,default)`,
so they can be overridden from the command line with `-J<name>=<value>`
without editing the file:

| Variable | Default | Meaning |
| --- | --- | --- |
| `HOST` | `localhost` | Host to send requests to |
| `PORT` | `8100` | order-service port (matches `ORDER_SERVICE_PORT` in `.env.example`) |
| `USER_ID` | `1` | `user_id` in the order payload |
| `PRODUCT_ID` | `1` | `product_id` in the order payload |
| `QUANTITY` | `1` | `quantity` in the order payload |
| `USERS` | `10` | concurrent threads (matches k6's `vus: 10`) |
| `RAMP_UP` | `10` | seconds to reach `USERS` threads |
| `DURATION` | `30` | seconds the test runs once ramped up (matches k6's `duration: '30s'`) |

Defaults target `localhost:8100` — the host-exposed `order-service` port from
a normal `docker compose up` — so the plan runs against the stack the same
way the README's `curl`/`Invoke-RestMethod` examples do, no Docker network
wiring required.

## Stock caveat (same as the k6 baseline)

`PRODUCT_ID=1` only has 12 units of seeded stock (see
`docs/tests/baseline-results.md`). Bump it before a real run so the test
measures service performance instead of running dry on stock:

```powershell
docker compose exec -T postgres psql -U resilencia -d resilencia_db -c "UPDATE products SET quantity = 100000 WHERE id = 1;"
```

## Running headless

```bash
jmeter -n -t scripts/jmeter/baseline.jmx -l results.jtl -e -o report/
```

- `-l results.jtl` writes raw per-request results.
- `-e -o report/` generates an HTML dashboard report (throughput, response
  time percentiles, error %) from those results.
- Override any parameter from the table above, e.g. a shorter smoke test:
  `jmeter -n -t scripts/jmeter/baseline.jmx -JUSERS=2 -JRAMP_UP=2 -JDURATION=5 -l results.jtl`

## Business-level success

Like `scripts/k6/baseline.js`, this plan does not rely on the HTTP status
code alone: `order-service` returns HTTP 200 for business failures too (out
of stock, payment declined, fraud hold - none of them raise an
HTTPException). The `Order succeeded (business status)` response assertion
checks the response body for `"status":"success"` so the JMeter report's
error % reflects real order outcomes, not just "the request was served".

import http from 'k6/http';
import { check, sleep } from 'k6';

const ORDER_URL = __ENV.ORDER_URL || 'http://order-service:8000/orders';
const CHAOS_URL = __ENV.CHAOS_URL || 'http://payment-service:8000/chaos/config';

export const options = {
  vus: 10,
  duration: '30s',
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export function setup() {
  const payload = JSON.stringify({ FAILURE_RATE: 0.3 });
  const params = { headers: { 'Content-Type': 'application/json' } };
  http.post(CHAOS_URL, payload, params);
}

export function teardown() {
  const payload = JSON.stringify({ FAILURE_RATE: 0.0 });
  const params = { headers: { 'Content-Type': 'application/json' } };
  http.post(CHAOS_URL, payload, params);
}

export default function () {
  const payload = JSON.stringify({
    user_id: 1,
    product_id: 1,
    quantity: 1,
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
    },
  };

  const res = http.post(ORDER_URL, payload, params);
  check(res, {
    'status is 200 or 201': (r) => r.status === 200 || r.status === 201,
    // order-service returns HTTP 200 even when the payment call failed
    // (see scripts/k6/baseline.js) - this check is what actually shows the
    // retries-vs-no-retries difference in error rate.
    'order succeeded': (r) => r.json('status') === 'success',
  });
  sleep(1);
}

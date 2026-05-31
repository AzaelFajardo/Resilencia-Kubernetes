import http from 'k6/http';
import { check, sleep } from 'k6';

const ORDER_URL = __ENV.ORDER_URL || 'http://localhost:8000/orders';
const CHAOS_URL = __ENV.CHAOS_URL || 'http://localhost:8003/chaos/config';

export const options = {
  vus: 10,
  duration: '30s',
};

export function setup() {
  const payload = JSON.stringify({ failure_rate: 0.8 });
  const params = { headers: { 'Content-Type': 'application/json' } };
  http.post(CHAOS_URL, payload, params);
}

export function teardown() {
  const payload = JSON.stringify({ failure_rate: 0.0 });
  const params = { headers: { 'Content-Type': 'application/json' } };
  http.post(CHAOS_URL, payload, params);
}

export default function () {
  const payload = JSON.stringify({
    user_id: "1",
    product_id: "1",
    quantity: 1,
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
    },
  };

  const res = http.post(ORDER_URL, payload, params);
  check(res, {
    'status is 200/201 or 503': (r) => r.status === 200 || r.status === 201 || r.status === 503 || r.status === 500,
  });
  sleep(1);
}

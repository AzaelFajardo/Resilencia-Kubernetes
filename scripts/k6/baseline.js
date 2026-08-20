import http from 'k6/http';
import { check, sleep } from 'k6';

const ORDER_URL = __ENV.ORDER_URL || 'http://order-service:8000/orders';

export const options = {
  vus: 10,
  duration: '30s',
};

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
  });
  sleep(1);
}

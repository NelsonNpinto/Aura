// Load profile for AURA (Phase 5.6).
//
// Runs against a PREVIEW deploy with PROVIDER_MODE=fake, so it measures AURA's own overhead —
// routing, RLS transactions, the gateway, SSE — without spending provider quota or claiming
// model latency it did not measure.
//
//   k6 run -e BASE_URL=https://aura-preview.vercel.app -e API_KEY=... infra/k6/load.js
//
// Thresholds are deliberately generous: Neon scales to zero after 5 minutes, so the first
// request in a run pays a cold start (~1 s) by design (§B4).

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const BASE = __ENV.BASE_URL || 'http://localhost:8010';
const API_KEY = __ENV.API_KEY || '';

const healthLatency = new Trend('aura_health_ms');
const readLatency = new Trend('aura_read_ms');
const errorRate = new Rate('aura_errors');

export const options = {
  scenarios: {
    // Public pages: what an anonymous visitor hits.
    browse: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: '30s', target: 5 },
        { duration: '1m', target: 10 },
        { duration: '30s', target: 0 },
      ],
      exec: 'browse',
    },
    // Authenticated reads: the inbox and the eval report.
    read: {
      executor: 'constant-vus',
      vus: 3,
      duration: '2m',
      exec: 'read',
      startTime: '30s',
    },
  },
  thresholds: {
    'http_req_failed': ['rate<0.02'],
    'aura_health_ms': ['p(95)<1500'],
    'aura_read_ms': ['p(95)<3000'],
    'aura_errors': ['rate<0.02'],
  },
};

function headers() {
  return API_KEY ? { 'x-api-key': API_KEY } : {};
}

export function browse() {
  const health = http.get(`${BASE}/api/v1/health`);
  healthLatency.add(health.timings.duration);
  errorRate.add(health.status !== 200);
  check(health, { 'health 200': (r) => r.status === 200 });

  const report = http.get(`${BASE}/api/v1/eval-report`);
  // 404 is a legitimate answer when nothing has been published yet.
  check(report, { 'eval report answered': (r) => r.status === 200 || r.status === 404 });

  const categories = http.get(`${BASE}/api/v1/challenge/categories`);
  check(categories, { 'challenge categories': (r) => r.status === 200 });
  sleep(1);
}

export function read() {
  if (!API_KEY) {
    sleep(1);
    return;
  }
  const invoices = http.get(`${BASE}/api/v1/runs?limit=20`, { headers: headers() });
  readLatency.add(invoices.timings.duration);
  errorRate.add(invoices.status >= 400);
  check(invoices, { 'runs listed': (r) => r.status === 200 });

  const usage = http.get(`${BASE}/api/v1/usage`, { headers: headers() });
  check(usage, { 'usage 200': (r) => r.status === 200 });
  sleep(2);
}

export function handleSummary(data) {
  return {
    'stdout': JSON.stringify(
      {
        checks: data.metrics.checks && data.metrics.checks.values,
        http_req_failed: data.metrics.http_req_failed && data.metrics.http_req_failed.values,
        health_p95: data.metrics.aura_health_ms && data.metrics.aura_health_ms.values['p(95)'],
        read_p95: data.metrics.aura_read_ms && data.metrics.aura_read_ms.values['p(95)'],
        note: 'PROVIDER_MODE=fake: model latency is not included in these figures.',
      },
      null,
      2,
    ),
    'load-report.json': JSON.stringify(data, null, 2),
  };
}

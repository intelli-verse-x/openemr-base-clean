# Baseline Performance Metrics

Captured on the local dev stack (Apple Silicon, colima 4 CPU / 8 GB; OpenEMR flex +
MariaDB in Docker; agent in a Python 3.11 venv; **mock LLM** to isolate the
service/DB path from external-provider variance). Raw CSVs in `loadtest/`.

## Load test — `/chat` (and health/ready mix)

| Scenario | Requests | Failures | Throughput | p50 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| **10 concurrent** (`baseline_10`) | 215 | 0 (0.00%) | 7.96 req/s | 12 ms | 27 ms | 41 ms | 99 ms |
| **50 concurrent** (`baseline_50`) | 1,098 | 0 (0.00%) | 37.7 req/s | 6 ms | 20 ms | 72 ms | 130 ms |

`/chat` alone at 50 users: p50 8 ms, p95 21 ms, p99 75 ms, max 130 ms — all far under
the 15 s brief budget. Zero errors at both levels. (With a real LLM, add provider
latency; the fast model typically adds ~0.5–2 s, synthesis ~2–5 s — still within budget.)

## Infrastructure baseline (idle-to-light load)

| Container | CPU | Memory |
|---|---:|---:|
| openemr (flex) | 0.2% | ~609 MiB |
| mariadb | ~0.01% | ~214 MiB |
| phpmyadmin | ~0.01% | ~45 MiB |
| agent service (python) | <5% single core under 50-user load | ~90–120 MiB RSS |

## Deployed baseline (EKS, live)

Confirmed on the public deployment (`clinical-copilot.intelli-verse-x.ai`, 2 replicas,
arm64 nodes) via `kubectl top`. Idle-to-light load:

| Pod | CPU (cores) | Memory |
|---|---:|---:|
| clinical-copilot (replica 1) | 2m | 40 Mi |
| clinical-copilot (replica 2) | 1m | 40 Mi |
| copilot-mariadb | 3m | 204 Mi |

A live 50-concurrent burst against the public URL returned **50/50 HTTP 200**, wall-clock
p95 ~0.98 s (dominated by client→us-east-1 RTT; server-side latency stays 1–7 ms per the
structured logs). Requests: `kubectl -n clinical-copilot top pods`.

## How to reproduce

```bash
# 1) OpenEMR up (repo root)
cd docker/development-easy-light && HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose up -d

# 2) Agent up (mock LLM)
cd clinical-copilot
COPILOT_DB_PORT=8320 COPILOT_LLM_PROVIDER=mock .venv/bin/uvicorn app.main:app --port 8500

# 3) Load tests
.venv/bin/locust -f loadtest/locustfile.py --headless -u 10 -r 5 -t 60s --host http://127.0.0.1:8500 --csv loadtest/baseline_10
.venv/bin/locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 60s --host http://127.0.0.1:8500 --csv loadtest/baseline_50
```

## Interpretation

The service/DB path is not the bottleneck; **LLM latency dominates real-world response
time**. This validates the ARCHITECTURE.md decision to use bounded SQL reads (not UI
replay or FHIR round-trips) and to keep verification/observability off the hot path.
Future performance regressions should be measured against these numbers.

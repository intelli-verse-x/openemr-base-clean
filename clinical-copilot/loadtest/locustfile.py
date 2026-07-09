"""Load/stress test for the Clinical Co-Pilot.

Run 10 then 50 concurrent users (engineering requirement):
  .venv/bin/locust -f loadtest/locustfile.py --headless -u 10 -r 5 -t 60s \
      --host http://127.0.0.1:8500 --csv loadtest/baseline_10
  .venv/bin/locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 60s \
      --host http://127.0.0.1:8500 --csv loadtest/baseline_50

Records p50/p95/p99 latency + error rate in the CSV. Use with the mock LLM to
measure the service/DB path without external-provider variance.
"""
import random

from locust import HttpUser, between, task

_QUESTIONS = [
    "give me the pre-visit summary",
    "what medications is the patient on?",
    "any drug interactions or allergy conflicts?",
    "show recent lab results",
    "what changed since the last visit?",
    "list active problems",
]


class Clinician(HttpUser):
    wait_time = between(0.5, 2.0)

    @task(4)
    def chat(self):
        self.client.post("/chat", json={
            "patient_id": random.randint(1, 12),
            "message": random.choice(_QUESTIONS),
            "user_id": "admin",
            "role": "physician",
        }, name="/chat")

    @task(1)
    def ready(self):
        self.client.get("/ready", name="/ready")

    @task(1)
    def health(self):
        self.client.get("/health", name="/health")

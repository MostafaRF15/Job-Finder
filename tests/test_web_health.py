"""Unit test for the /health endpoint (liveness check)."""

from __future__ import annotations

import unittest

from job_agent.web import app


class HealthEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = app.test_client()

    def test_health_returns_ok(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data, {"ok": True, "status": "healthy"})


if __name__ == "__main__":
    unittest.main()

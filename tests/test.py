"""Tests for the GitHub webhook triage server (solution.py)."""

import json
import unittest
from unittest.mock import patch

from solution import app, classify_severity


# Sample GitHub webhook payload used across tests
SAMPLE_WEBHOOK_PAYLOAD = {
    "action": "labeled",
    "issue": {
        "number": 42,
        "title": "500 Internal Server Error on /api/users endpoint",
        "body": (
            "When hitting the /api/users endpoint with a POST request "
            "containing a valid payload, the server returns a 500 error.\n\n"
            "Traceback:\n```\nTraceback (most recent call last):\n"
            '  File "app/routes/users.py", line 23, in create_user\n'
            "    user = User(**data)\n"
            "TypeError: __init__() got an unexpected keyword argument "
            "'email_address'\n```\n\n"
            "Expected: 201 Created with user object.\n"
            "Actual: 500 Internal Server Error."
        ),
        "labels": [
            {"id": 1, "name": "bug"},
            {"id": 2, "name": "devin-triage"},
        ],
        "state": "open",
        "user": {"login": "tkirby926"},
        "html_url": "https://github.com/tkirby926/Devin-Solution/issues/42",
    },
    "repository": {
        "full_name": "tkirby926/Devin-Solution",
        "clone_url": "https://github.com/tkirby926/Devin-Solution.git",
        "html_url": "https://github.com/tkirby926/Devin-Solution",
    },
    "sender": {"login": "tkirby926"},
}


class TestClassifySeverity(unittest.TestCase):
    """Tests for the classify_severity helper."""

    def test_small_severity_for_500_error(self):
        severity = classify_severity(
            "500 Internal Server Error on /api/users endpoint",
            "server returns a 500 error",
        )
        self.assertEqual(severity, "small")

    def test_small_severity_for_validation_error(self):
        severity = classify_severity("Validation fails", "validation error on input")
        self.assertEqual(severity, "small")

    def test_medium_severity_for_refactor(self):
        severity = classify_severity("Refactor auth module", "needs a refactor")
        self.assertEqual(severity, "medium")

    def test_large_severity_for_race_condition(self):
        severity = classify_severity("Race condition in worker", "concurrency issue")
        self.assertEqual(severity, "large")

    def test_default_medium_severity(self):
        severity = classify_severity("Update README", "typo fix")
        self.assertEqual(severity, "medium")


class TestWebhook(unittest.TestCase):
    """Tests for the /webhook/github endpoint."""

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_ignores_payload_without_issue(self):
        response = self.client.post(
            "/webhook/github",
            data=json.dumps({"action": "opened"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ignored")

    def test_ignores_issue_without_triage_label(self):
        payload = {
            "action": "labeled",
            "issue": {
                "number": 1,
                "title": "Some issue",
                "body": "",
                "labels": [{"id": 1, "name": "bug"}],
            },
            "repository": {
                "full_name": "owner/repo",
                "clone_url": "https://github.com/owner/repo.git",
            },
        }
        response = self.client.post(
            "/webhook/github",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("ignored", response.get_json()["status"])

    @patch("solution.create_devin_session", return_value="mock-session-id")
    @patch("solution.monitor_session")
    def test_creates_session_for_triaged_issue(self, mock_monitor, mock_create):
        response = self.client.post(
            "/webhook/github",
            data=json.dumps(SAMPLE_WEBHOOK_PAYLOAD),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "devin-session-created")
        self.assertEqual(data["session_id"], "mock-session-id")
        self.assertEqual(data["severity"], "small")
        mock_create.assert_called_once()


if __name__ == "__main__":
    unittest.main()

from flask import Flask, request, jsonify
import threading
import time

from devin_client import create_devin_session, check_session_status
from github_commenter import post_issue_comment

app = Flask(__name__)

# In-memory tracking (replace with DB in production)
TASKS = {}

def classify_severity(title: str, body: str) -> str:
    text = (title + " " + body).lower()

    if "race condition" in text or "concurrency" in text:
        return "large"

    if "refactor" in text:
        return "medium"

    if "500" in text or "validation" in text or "error" in text:
        return "small"

    return "medium"


@app.route("/webhook/github", methods=["POST"])
def github_webhook():
    data = request.json

    if "issue" not in data:
        return jsonify({"status": "ignored"})

    issue = data["issue"]
    repo = data["repository"]["full_name"]
    repo_url = data["repository"]["clone_url"]

    labels = [label["name"] for label in issue.get("labels", [])]

    if "devin-triage" not in labels:
        return jsonify({"status": "ignored - no triage label"})

    issue_number = issue["number"]
    title = issue["title"]
    body = issue.get("body", "")

    severity = classify_severity(title, body)

    session_id = create_devin_session(
        repo_url,
        issue_number,
        title,
        body,
        severity,
    )

    TASKS[session_id] = {
        "repo": repo,
        "issue_number": issue_number,
        "status": "in_progress",
    }

    threading.Thread(target=monitor_session, args=(session_id,)).start()

    return jsonify({
        "status": "devin-session-created",
        "session_id": session_id,
        "severity": severity,
    })


def monitor_session(session_id):
    """Poll a Devin session until it reaches a terminal status.

    Terminal statuses (per Devin API docs):
      - exit      — completed successfully
      - error     — encountered an error
      - suspended — paused / needs attention
    """
    while True:
        result = check_session_status(session_id)
        status = result["status"]

        if status in ("exit", "error", "suspended"):
            TASKS[session_id]["status"] = status

            repo = TASKS[session_id]["repo"]
            issue_number = TASKS[session_id]["issue_number"]
            session_url = result.get("url", "(no URL available)")

            status_label = {
                "exit": "Completed",
                "error": "Failed",
                "suspended": "Suspended",
            }.get(status, status)

            message = (
                f"**Devin Session Update**\n\n"
                f"- **Status:** {status_label}\n"
                f"- **Session:** {session_url}\n\n"
                f"Review the session for full details."
            )

            post_issue_comment(repo, issue_number, message)
            break

        time.sleep(20)


if __name__ == "__main__":
    app.run(port=5000)

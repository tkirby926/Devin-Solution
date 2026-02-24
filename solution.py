from flask import Flask, request, jsonify
import threading
import time

from devin_client import create_devin_task, check_task_status
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

    task_id = create_devin_task(
        repo_url,
        issue_number,
        title,
        body,
        severity
    )

    TASKS[task_id] = {
        "repo": repo,
        "issue_number": issue_number,
        "status": "in_progress"
    }

    threading.Thread(target=monitor_task, args=(task_id,)).start()

    return jsonify({
        "status": "devin-task-created",
        "task_id": task_id,
        "severity": severity
    })


def monitor_task(task_id):
    while True:
        result = check_task_status(task_id)

        if result["status"] in ["completed", "failed"]:
            TASKS[task_id]["status"] = result["status"]

            repo = TASKS[task_id]["repo"]
            issue_number = TASKS[task_id]["issue_number"]

            message = f"""
            Devin Task Completed
            Status: {result['status']}
            Output:
            {result.get('summary', 'See task logs.')}
            """

            post_issue_comment(repo, issue_number, message)
            break

        time.sleep(20)


if __name__ == "__main__":
    app.run(port=5000)
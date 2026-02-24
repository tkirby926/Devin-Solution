import os
import requests

DEVIN_API_KEY = os.getenv("DEVIN_API_KEY")
DEVIN_API_BASE = os.getenv("DEVIN_API_BASE")


def create_devin_task(repo_url, issue_number, title, body, severity):
    if severity == "small":
        instructions = f"""
        Resolve GitHub Issue #{issue_number}.
        - Create branch devin/issue-{issue_number}
        - Implement fix
        - Run tests
        - Open PR referencing issue
        """
    elif severity == "medium":
        instructions = f"""
        Analyze GitHub Issue #{issue_number}.
        Provide detailed remediation plan.
        Do NOT implement.
        """
    else:
        instructions = f"""
        Analyze GitHub Issue #{issue_number}.
        Explain why this requires senior engineer review.
        Do NOT implement.
        """

    payload = {
        "repo_url": repo_url,
        "task": f"""
        Issue Title: {title}
        Issue Body:
        {body}

        {instructions}
        """,
        "metadata": {
            "issue_number": issue_number,
            "severity": severity
        }
    }

    headers = {
        "Authorization": f"Bearer {DEVIN_API_KEY}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        f"{DEVIN_API_BASE}/tasks",
        json=payload,
        headers=headers
    )

    response.raise_for_status()
    return response.json()["id"]


def check_task_status(task_id):
    headers = {
        "Authorization": f"Bearer {DEVIN_API_KEY}"
    }

    response = requests.get(
        f"{DEVIN_API_BASE}/tasks/{task_id}",
        headers=headers
    )

    response.raise_for_status()
    return response.json()
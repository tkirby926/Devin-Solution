import os

import requests

# ---------------------------------------------------------------------------
# GitHub API configuration
# Set GITHUB_TOKEN via environment variable.
# The token needs `repo` scope to post comments on issues.
# ---------------------------------------------------------------------------


GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


def post_issue_comment(repo_full_name, issue_number, message):
    url = f"https://api.github.com/repos/{repo_full_name}/issues/{issue_number}/comments"

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    payload = {
        "body": message
    }

    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()

import requests

# ---------------------------------------------------------------------------
# GitHub API configuration
# Replace the placeholder below with your actual GitHub personal access token.
# The token needs `repo` scope to post comments on issues.
# ---------------------------------------------------------------------------
GITHUB_TOKEN = "YOUR_GITHUB_TOKEN"  # TODO: replace with actual token


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

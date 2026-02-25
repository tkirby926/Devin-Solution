import os
from env import DEVIN_API_KEY
import requests

# ---------------------------------------------------------------------------
# Devin API configuration
# Set via environment variables.  The base URL defaults to the Devin v1 API.
# Base URL options:
#   https://api.devin.ai/v1                (legacy, default)
#   https://api.devin.ai/v3/organizations  (current, recommended)
# ---------------------------------------------------------------------------
 # Set via environment variable
DEVIN_API_BASE = os.getenv("DEVIN_API_BASE", "https://api.devin.ai/v1")  # Devin v1 API base URL


def create_devin_session(repo_url, issue_number, title, body, severity):
    """Create a Devin session to handle a GitHub issue.

    The Devin API uses *sessions* (not tasks).  The main field in the
    request body is ``prompt`` — a free-text string that tells Devin
    what to do.  The response includes ``session_id`` which is used to
    poll for status later.

    Docs: https://docs.devin.ai/api-reference/v1/overview
    """
    if severity == "small":
        instructions = (
            f"Resolve GitHub Issue #{issue_number} in the repo {repo_url}.\n"
            f"- Create branch devin/issue-{issue_number}\n"
            f"- Implement the fix\n"
            f"- Run tests\n"
            f"- Open a PR referencing the issue\n"
        )
    elif severity == "medium":
        instructions = (
            f"Analyze GitHub Issue #{issue_number} in the repo {repo_url}.\n"
            f"Provide a detailed remediation plan.\n"
            f"Do NOT implement the fix — only plan it.\n"
        )
    else:  # large
        instructions = (
            f"Analyze GitHub Issue #{issue_number} in the repo {repo_url}.\n"
            f"Explain why this requires senior engineer review.\n"
            f"Do NOT implement any changes.\n"
        )

    prompt = (
        f"Issue Title: {title}\n"
        f"Issue Body:\n{body}\n\n"
        f"{instructions}"
    )

    payload = {"prompt": prompt}

    headers = {
        "Authorization": f"Bearer {DEVIN_API_KEY}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        f"{DEVIN_API_BASE}/sessions",
        json=payload,
        headers=headers,
    )

    response.raise_for_status()
    return response.json()["session_id"]


def check_session_status(session_id):
    """Poll the status of a Devin session.

    Terminal statuses returned by the Devin API:
      - ``exit``      — session completed successfully
      - ``error``     — session encountered an error
      - ``suspended`` — session was suspended

    The response also includes ``url`` which links to the Devin session.
    """
    headers = {
        "Authorization": f"Bearer {DEVIN_API_KEY}",
    }

    response = requests.get(
        f"{DEVIN_API_BASE}/sessions/{session_id}",
        headers=headers,
    )

    response.raise_for_status()
    return response.json()

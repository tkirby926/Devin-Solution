"""
GitHub Error Webhook Automation & AI Agent
===========================================
Reads GitHub error messages via webhook events, then uses an AI agent
to analyze the error and respond with a suggested fix.

Supported webhook events:
  - check_run (CI check failures)
  - workflow_run (GitHub Actions workflow failures)
  - issue_comment (error messages in issue/PR comments)

Environment variables:
  GITHUB_WEBHOOK_SECRET  - Secret for verifying webhook signatures
  GITHUB_TOKEN           - Personal access token for GitHub API calls
  OPENAI_API_KEY         - API key for OpenAI (used by the error-fixing agent)
  OPENAI_MODEL           - Model to use (default: gpt-4)
  FLASK_PORT             - Port to run the webhook server on (default: 5000)
"""

import hashlib
import hmac
import logging
import os
import re
from typing import Optional

import requests
from flask import Flask, abort, jsonify, request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITHUB_WEBHOOK_SECRET: str = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
GITHUB_TOKEN: str = os.environ.get("GITHUB_TOKEN", "")
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "gpt-4")
FLASK_PORT: int = int(os.environ.get("FLASK_PORT", "5000"))

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("webhook-agent")

# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------


def verify_signature(payload_body: bytes, signature_header: str) -> bool:
    """Verify the GitHub webhook HMAC-SHA256 signature."""
    if not GITHUB_WEBHOOK_SECRET:
        logger.warning("GITHUB_WEBHOOK_SECRET not set — skipping verification")
        return True

    if not signature_header:
        return False

    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)


# ---------------------------------------------------------------------------
# Error extraction helpers (one per supported event type)
# ---------------------------------------------------------------------------


def extract_error_from_check_run(payload: dict) -> Optional[dict]:
    """Extract error info from a ``check_run`` event whose conclusion is *failure*."""
    check_run = payload.get("check_run", {})
    if check_run.get("conclusion") != "failure":
        return None

    output = check_run.get("output", {})
    return {
        "source": "check_run",
        "name": check_run.get("name", "Unknown Check"),
        "error_message": output.get("summary", "No summary available"),
        "details": output.get("text", ""),
        "repo": payload.get("repository", {}).get("full_name", ""),
        "head_sha": check_run.get("head_sha", ""),
        "url": check_run.get("html_url", ""),
    }


def extract_error_from_workflow_run(payload: dict) -> Optional[dict]:
    """Extract error info from a ``workflow_run`` event whose conclusion is *failure*."""
    workflow_run = payload.get("workflow_run", {})
    if workflow_run.get("conclusion") != "failure":
        return None

    run_id = workflow_run.get("id")
    repo = payload.get("repository", {}).get("full_name", "")

    # Try to fetch detailed failure logs from the Actions API
    detailed_logs = fetch_workflow_failure_details(repo, run_id) if run_id else ""

    return {
        "source": "workflow_run",
        "name": workflow_run.get("name", "Unknown Workflow"),
        "error_message": f"Workflow '{workflow_run.get('name')}' failed",
        "details": detailed_logs,
        "repo": repo,
        "head_sha": workflow_run.get("head_sha", ""),
        "url": workflow_run.get("html_url", ""),
        "run_id": run_id,
    }


def extract_error_from_issue_comment(payload: dict) -> Optional[dict]:
    """Extract error info from an ``issue_comment`` event when the body contains error patterns."""
    comment = payload.get("comment", {})
    body: str = comment.get("body", "")

    error_patterns = [
        r"(?i)error[:\s](.+)",
        r"(?i)exception[:\s](.+)",
        r"(?i)traceback[\s\S]+",
        r"(?i)failed[:\s](.+)",
        r"(?i)panic[:\s](.+)",
        r"(?i)segfault",
        r"(?i)stack\s*trace",
    ]

    if not any(re.search(p, body) for p in error_patterns):
        return None

    issue = payload.get("issue", {})
    return {
        "source": "issue_comment",
        "name": f"Issue #{issue.get('number', '?')}",
        "error_message": body,
        "details": "",
        "repo": payload.get("repository", {}).get("full_name", ""),
        "head_sha": "",
        "url": comment.get("html_url", ""),
        "issue_number": issue.get("number"),
    }


# Mapping of GitHub event names to extractor functions
EVENT_EXTRACTORS: dict = {
    "check_run": extract_error_from_check_run,
    "workflow_run": extract_error_from_workflow_run,
    "issue_comment": extract_error_from_issue_comment,
}

# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

_GITHUB_API = "https://api.github.com"


def _github_headers() -> dict:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def fetch_workflow_failure_details(repo: str, run_id: int) -> str:
    """Fetch failed-job / failed-step details from the Actions API."""
    if not GITHUB_TOKEN:
        return "(GitHub token not configured — cannot fetch logs)"

    url = f"{_GITHUB_API}/repos/{repo}/actions/runs/{run_id}/jobs"
    try:
        resp = requests.get(url, headers=_github_headers(), timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return f"(Failed to fetch workflow jobs: {exc})"

    lines: list[str] = []
    for job in resp.json().get("jobs", []):
        if job.get("conclusion") == "failure":
            lines.append(f"Job: {job['name']}")
            for step in job.get("steps", []):
                if step.get("conclusion") == "failure":
                    lines.append(f"  Failed step: {step['name']}")

    return "\n".join(lines) if lines else "(No detailed failure info found)"


def post_github_comment(repo: str, issue_number: int, body: str) -> bool:
    """Post a comment on a GitHub issue or pull request."""
    if not GITHUB_TOKEN:
        logger.error("Cannot post comment — GITHUB_TOKEN not set")
        return False

    url = f"{_GITHUB_API}/repos/{repo}/issues/{issue_number}/comments"
    try:
        resp = requests.post(
            url,
            headers=_github_headers(),
            json={"body": body},
            timeout=30,
        )
        resp.raise_for_status()
        logger.info("Posted comment on %s#%s", repo, issue_number)
        return True
    except requests.RequestException as exc:
        logger.error("Failed to post comment: %s", exc)
        return False


def create_commit_comment(repo: str, sha: str, body: str) -> bool:
    """Post a comment on a specific commit."""
    if not GITHUB_TOKEN:
        logger.error("Cannot post commit comment — GITHUB_TOKEN not set")
        return False

    url = f"{_GITHUB_API}/repos/{repo}/commits/{sha}/comments"
    try:
        resp = requests.post(
            url,
            headers=_github_headers(),
            json={"body": body},
            timeout=30,
        )
        resp.raise_for_status()
        logger.info("Posted commit comment on %s@%s", repo, sha)
        return True
    except requests.RequestException as exc:
        logger.error("Failed to post commit comment: %s", exc)
        return False


# ---------------------------------------------------------------------------
# AI Agent — error analysis & fix suggestion
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a senior software engineer who specializes in debugging and "
    "fixing errors. When given error information you must respond with:\n"
    "1. **Root Cause** — a concise explanation of what went wrong.\n"
    "2. **Suggested Fix** — a specific, actionable fix with code snippets "
    "where applicable.\n"
    "3. **Prevention** — a brief note on how to prevent this in the future.\n\n"
    "Keep the response concise, technical, and directly useful."
)


def _build_user_prompt(error_info: dict) -> str:
    """Build the user-facing prompt sent to the LLM."""
    parts = [
        f"**Source:** {error_info['source']}",
        f"**Name:** {error_info['name']}",
        f"**Error message:**\n```\n{error_info['error_message']}\n```",
    ]
    if error_info.get("details"):
        parts.append(f"**Details:**\n```\n{error_info['details']}\n```")
    if error_info.get("repo"):
        parts.append(f"**Repository:** {error_info['repo']}")
    if error_info.get("url"):
        parts.append(f"**URL:** {error_info['url']}")
    return "\n\n".join(parts)


def agent_analyze_error(error_info: dict) -> str:
    """
    Send the extracted error to the AI agent and return its analysis.

    Falls back to a simple rule-based analysis when OPENAI_API_KEY is not set.
    """
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set — using fallback analysis")
        return _fallback_analysis(error_info)

    user_prompt = _build_user_prompt(error_info)

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 1500,
    }

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except requests.RequestException as exc:
        logger.error("OpenAI API request failed: %s", exc)
        return _fallback_analysis(error_info)
    except (KeyError, IndexError) as exc:
        logger.error("Unexpected OpenAI response structure: %s", exc)
        return _fallback_analysis(error_info)


def _fallback_analysis(error_info: dict) -> str:
    """Provide a basic rule-based analysis when the LLM is unavailable."""
    msg = error_info.get("error_message", "")
    details = error_info.get("details", "")
    combined = f"{msg}\n{details}"
    suggestions: list[str] = []

    rules: list[tuple[str, str]] = [
        (
            r"(?i)modulenotfounderror|import\s+error",
            "A Python import failed. Ensure the dependency is listed in "
            "requirements.txt / pyproject.toml and installed.",
        ),
        (
            r"(?i)syntaxerror",
            "There is a syntax error in the code. Check the indicated file "
            "and line number for typos or missing punctuation.",
        ),
        (
            r"(?i)typeerror",
            "A TypeError occurred. Verify that function arguments and "
            "variable types match their expected signatures.",
        ),
        (
            r"(?i)connection\s*(refused|timeout|reset)",
            "A network connection issue occurred. Verify that the target "
            "service is running and reachable.",
        ),
        (
            r"(?i)permission\s*denied",
            "A permission error occurred. Check file/directory permissions "
            "and credentials.",
        ),
        (
            r"(?i)out\s*of\s*memory|oom",
            "The process ran out of memory. Consider optimising memory usage "
            "or increasing resource limits.",
        ),
        (
            r"(?i)timeout",
            "An operation timed out. Check for slow queries, network issues, "
            "or increase the timeout threshold.",
        ),
    ]

    for pattern, suggestion in rules:
        if re.search(pattern, combined):
            suggestions.append(suggestion)

    if not suggestions:
        suggestions.append(
            "Unable to determine an automatic fix. "
            "Please review the error details manually."
        )

    header = (
        f"**Automated Error Analysis** "
        f"(source: `{error_info['source']}`, name: `{error_info['name']}`)\n\n"
    )
    body = "\n".join(f"- {s}" for s in suggestions)
    truncated_msg = msg[:300] + ("..." if len(msg) > 300 else "")
    footer = f"\n\n> Error: `{truncated_msg}`"
    return header + body + footer


# ---------------------------------------------------------------------------
# Respond — post the agent's analysis back to GitHub
# ---------------------------------------------------------------------------


def respond_to_error(error_info: dict, analysis: str) -> bool:
    """
    Post the agent's analysis back to the appropriate place on GitHub.

    - For issue_comment errors -> reply on the same issue.
    - For check_run / workflow_run errors -> comment on the commit.
    """
    repo = error_info.get("repo", "")
    if not repo:
        logger.warning("No repo in error_info — cannot respond")
        return False

    comment_body = (
        "## Automated Error Analysis\n\n"
        f"{analysis}\n\n"
        "---\n"
        f"*Generated by [webhook-agent]({error_info.get('url', '')})*"
    )

    if error_info.get("issue_number"):
        return post_github_comment(
            repo, error_info["issue_number"], comment_body
        )

    if error_info.get("head_sha"):
        return create_commit_comment(
            repo, error_info["head_sha"], comment_body
        )

    logger.warning(
        "No issue_number or head_sha — nowhere to post the response"
    )
    return False


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------


@app.route("/webhook", methods=["POST"])
def handle_webhook():
    """
    Main webhook endpoint.

    1. Verify the signature.
    2. Determine the event type.
    3. Extract any error information.
    4. Run the AI agent to analyse the error.
    5. Post the analysis back to GitHub.
    """
    # --- Signature verification ---
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(request.get_data(), signature):
        logger.warning("Invalid webhook signature")
        abort(401, description="Invalid signature")

    # --- Parse event ---
    event_type = request.headers.get("X-GitHub-Event", "")
    payload: dict = request.get_json(silent=True) or {}

    logger.info(
        "Received event: %s (action=%s)", event_type, payload.get("action")
    )

    extractor = EVENT_EXTRACTORS.get(event_type)
    if extractor is None:
        return (
            jsonify({
                "status": "ignored",
                "reason": f"Unsupported event: {event_type}",
            }),
            200,
        )

    error_info = extractor(payload)
    if error_info is None:
        return (
            jsonify({
                "status": "ignored",
                "reason": "No actionable error found",
            }),
            200,
        )

    logger.info(
        "Error detected — source=%s name=%s",
        error_info["source"],
        error_info["name"],
    )

    # --- Agent analysis ---
    analysis = agent_analyze_error(error_info)
    logger.info("Agent analysis complete (%d chars)", len(analysis))

    # --- Respond on GitHub ---
    posted = respond_to_error(error_info, analysis)

    return (
        jsonify({
            "status": "processed",
            "error_source": error_info["source"],
            "error_name": error_info["name"],
            "analysis_length": len(analysis),
            "posted_to_github": posted,
            "analysis_preview": analysis[:500],
        }),
        200,
    )


@app.route("/health", methods=["GET"])
def health():
    """Simple health-check endpoint."""
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting webhook server on port %s", FLASK_PORT)
    app.run(host="0.0.0.0", port=FLASK_PORT)

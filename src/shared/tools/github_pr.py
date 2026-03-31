"""
tools/github_pr.py
GitHub PR tools using direct API calls with GITHUB_TOKEN from environment.
No gh CLI dependency — works in any environment with requests.
"""

import json
import os
import logging
import requests
from crewai.tools import tool

log = logging.getLogger(__name__)

ORG = "carespace-ai"


def _gh_api(endpoint: str, method: str = "GET", payload: dict = None) -> dict | list:
    """GitHub API v3 call using GITHUB_TOKEN from environment."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set in environment")

    url = f"https://api.github.com/{endpoint}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }

    if method == "GET":
        resp = requests.get(url, headers=headers, timeout=30)
    elif method == "POST":
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
    elif method == "PATCH":
        resp = requests.patch(url, headers=headers, json=payload, timeout=30)
    else:
        raise ValueError(f"Unsupported method: {method}")

    if resp.status_code >= 400:
        raise RuntimeError(f"GitHub API {resp.status_code}: {resp.text[:200]}")

    if resp.status_code == 204:
        return {}
    return resp.json()


def _gh_raw(endpoint: str) -> str:
    """GitHub API call that returns raw text (for diffs)."""
    token = os.environ.get("GITHUB_TOKEN", "")
    url = f"https://api.github.com/{endpoint}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3.diff",
    }
    resp = requests.get(url, headers=headers, timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"GitHub API {resp.status_code}: {resp.text[:200]}")
    return resp.text


@tool("list_open_prs")
def list_open_prs(repo: str = "") -> str:
    """
    Lists open PRs across carespace-ai repos. Returns JSON array with
    number, title, author, repo, url, additions, deletions, head branch.

    repo: specific repo name (e.g. 'carespace-ui'). Empty = all repos.
    """
    prs = []

    if repo:
        repos = [repo]
    else:
        try:
            result = _gh_api(f"orgs/{ORG}/repos?per_page=100&sort=pushed&type=all")
            repos = [r["name"] for r in result if not r.get("archived")]
        except Exception as e:
            return json.dumps({"error": f"Failed to list repos: {e}"})

    for rname in repos:
        try:
            result = _gh_api(f"repos/{ORG}/{rname}/pulls?state=open&per_page=20")
            for pr in result:
                prs.append({
                    "repo": rname,
                    "full_repo": f"{ORG}/{rname}",
                    "number": pr["number"],
                    "title": pr["title"],
                    "author": pr.get("user", {}).get("login", "unknown"),
                    "url": pr["html_url"],
                    "headRefName": pr["head"]["ref"],
                    "additions": pr.get("additions", 0),
                    "deletions": pr.get("deletions", 0),
                    "createdAt": pr.get("created_at", ""),
                })
        except Exception:
            continue

    return json.dumps(prs, indent=2)


@tool("get_pr_diff")
def get_pr_diff(repo: str, pr_number: int) -> str:
    """
    Gets the diff of a PR. Tries the full diff first; if too large (>20K lines),
    falls back to file-by-file patches via the files API.

    repo: repo name (e.g. 'carespace-ui')
    pr_number: PR number
    """
    # Try full diff first
    try:
        diff = _gh_raw(f"repos/{ORG}/{repo}/pulls/{pr_number}")
        if len(diff) > 50000:
            diff = diff[:50000] + "\n\n... (diff truncated — too large)"
        return diff
    except Exception as e:
        if "406" not in str(e) and "too_large" not in str(e):
            return json.dumps({"error": str(e)})

    # Fallback: fetch file-by-file patches (no size limit)
    log.info("get_pr_diff: full diff too large for %s#%d — using file-by-file", repo, pr_number)
    try:
        page = 1
        all_files = []
        while True:
            result = _gh_api(f"repos/{ORG}/{repo}/pulls/{pr_number}/files?per_page=100&page={page}")
            if not result:
                break
            all_files.extend(result)
            if len(result) < 100:
                break
            page += 1

        # Sort by change size, largest first
        all_files.sort(key=lambda f: f.get("changes", 0), reverse=True)

        total_add = sum(f.get("additions", 0) for f in all_files)
        total_del = sum(f.get("deletions", 0) for f in all_files)
        header = f"# PR #{pr_number} in {repo} — {len(all_files)} files (+{total_add} -{total_del})\n\n"

        chunks = [header]
        total_len = len(header)
        MAX_TOTAL = 80000  # keep total under 80K chars for LLM context
        MAX_PER_FILE = 3000  # max patch chars per file

        for f in all_files:
            fname = f["filename"]
            status = f["status"]
            adds = f.get("additions", 0)
            dels = f.get("deletions", 0)
            patch = f.get("patch", "") or ""

            if len(patch) > MAX_PER_FILE:
                patch = patch[:MAX_PER_FILE] + f"\n... (patch truncated, {len(patch)} total chars)"

            file_block = f"## {fname} ({status}, +{adds} -{dels})\n```diff\n{patch}\n```\n\n"

            if total_len + len(file_block) > MAX_TOTAL:
                remaining = len(all_files) - len(chunks) + 1
                chunks.append(f"\n... ({remaining} more files omitted — diff too large)\n")
                break

            chunks.append(file_block)
            total_len += len(file_block)

        return "".join(chunks)
    except Exception as e2:
        return json.dumps({"error": f"File-by-file fallback also failed: {e2}"})


@tool("get_pr_files")
def get_pr_files(repo: str, pr_number: int) -> str:
    """
    Lists files changed in a PR with additions/deletions count.

    repo: repo name (e.g. 'carespace-ui')
    pr_number: PR number
    """
    try:
        result = _gh_api(f"repos/{ORG}/{repo}/pulls/{pr_number}/files?per_page=100")
        files = [
            {
                "filename": f["filename"],
                "status": f["status"],
                "additions": f["additions"],
                "deletions": f["deletions"],
                "patch": f.get("patch", "")[:5000],
            }
            for f in result
        ]
        return json.dumps(files, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool("post_pr_review_comment")
def post_pr_review_comment(repo: str, pr_number: int, body: str) -> str:
    """
    Posts a review comment on a PR. Use this to report security findings.

    repo: repo name (e.g. 'carespace-ui')
    pr_number: PR number
    body: markdown comment body with findings
    """
    try:
        result = _gh_api(
            f"repos/{ORG}/{repo}/issues/{pr_number}/comments",
            method="POST",
            payload={"body": body},
        )
        return json.dumps({
            "ok": True,
            "repo": repo,
            "pr": pr_number,
            "comment_url": result.get("html_url", ""),
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

"""
tools/github_pr.py
GitHub PR tools using gh CLI for fetching diffs and posting review comments.
"""

import json
import subprocess
import logging
from crewai.tools import tool

log = logging.getLogger(__name__)

ORG = "carespace-ai"


def _gh(args: list[str], timeout: int = 30) -> str:
    """Run gh CLI command and return output."""
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {result.stderr[:200]}")
    return result.stdout


@tool("list_open_prs")
def list_open_prs(repo: str = "") -> str:
    """
    Lists open PRs across carespace-ai repos. Returns JSON array with
    number, title, author, repo, url, created_at, and head branch.

    repo: specific repo name (e.g. 'carespace-ui'). Empty = all repos.
    """
    prs = []

    if repo:
        repos = [repo]
    else:
        try:
            result = _gh(["repo", "list", ORG, "--json", "name", "--limit", "100"])
            repos = [r["name"] for r in json.loads(result)]
        except Exception as e:
            return json.dumps({"error": f"Failed to list repos: {e}"})

    for rname in repos:
        try:
            result = _gh([
                "pr", "list",
                "--repo", f"{ORG}/{rname}",
                "--state", "open",
                "--json", "number,title,author,url,createdAt,headRefName,additions,deletions",
                "--limit", "20",
            ])
            for pr in json.loads(result):
                pr["repo"] = rname
                pr["full_repo"] = f"{ORG}/{rname}"
                prs.append(pr)
        except Exception:
            continue  # Skip repos with no PRs or access issues

    return json.dumps(prs, indent=2)


@tool("get_pr_diff")
def get_pr_diff(repo: str, pr_number: int) -> str:
    """
    Gets the full diff of a PR. Returns the raw diff text.

    repo: repo name (e.g. 'carespace-ui')
    pr_number: PR number
    """
    try:
        diff = _gh([
            "pr", "diff", str(pr_number),
            "--repo", f"{ORG}/{repo}",
        ], timeout=60)

        # Truncate if too large (LLM context limit)
        if len(diff) > 50000:
            diff = diff[:50000] + "\n\n... (diff truncated — too large)"

        return diff
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool("get_pr_files")
def get_pr_files(repo: str, pr_number: int) -> str:
    """
    Lists files changed in a PR with additions/deletions count.

    repo: repo name (e.g. 'carespace-ui')
    pr_number: PR number
    """
    try:
        result = _gh([
            "pr", "view", str(pr_number),
            "--repo", f"{ORG}/{repo}",
            "--json", "files",
        ])
        data = json.loads(result)
        return json.dumps(data.get("files", []), indent=2)
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
        _gh([
            "pr", "comment", str(pr_number),
            "--repo", f"{ORG}/{repo}",
            "--body", body,
        ])
        return json.dumps({"ok": True, "repo": repo, "pr": pr_number})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

import json
import logging

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, before_kickoff, crew, task

from shared.tools import (
    list_open_prs, get_pr_diff, get_pr_files, post_pr_review_comment,
)

log = logging.getLogger(__name__)


@CrewBase
class PRSecurityCrew:
    """Scans open PRs for security issues and posts findings as comments.

    before_kickoff: fetches PRs, creates one task per PR with the diff
    directly in the task description (not as a separate input field).
    This forces the LLM to see the actual diff.

    Input: dry_run=true → show findings in output, don't post comments.
    """

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @before_kickoff
    def inject_context(self, inputs):
        ctx = inputs or {}
        dry_run = str(ctx.get("dry_run", "false")).lower() == "true"
        repo_filter = ctx.get("repo", "")

        # ── Fetch open PRs ──
        try:
            prs_result = list_open_prs.run(repo=repo_filter)
            prs = json.loads(prs_result) if isinstance(prs_result, str) else prs_result
            if isinstance(prs, dict) and "error" in prs:
                prs = []
            log.info("pr_security: found %d open PRs (dry_run=%s)", len(prs), dry_run)
        except Exception as e:
            log.warning("pr_security: PR fetch failed: %s", e)
            prs = []

        if not prs:
            ctx["pr_summary"] = "No open PRs found."
            ctx["dry_run"] = str(dry_run)
            return ctx

        # ── Build per-PR summaries with diffs embedded ──
        pr_summaries = []
        for pr in prs[:10]:
            repo = pr.get("repo", "")
            number = pr.get("number", 0)
            title = pr.get("title", "")
            author = pr.get("author", {}).get("login", "unknown") if isinstance(pr.get("author"), dict) else str(pr.get("author", "unknown"))
            url = pr.get("url", "")

            try:
                diff = get_pr_diff.run(repo=repo, pr_number=number)
                files_result = get_pr_files.run(repo=repo, pr_number=number)
                files = json.loads(files_result) if isinstance(files_result, str) else files_result
            except Exception as e:
                log.warning("pr_security: diff fetch failed for %s#%d: %s", repo, number, e)
                diff = ""
                files = []

            # Truncate diff to fit in context
            diff_text = diff[:15000] if isinstance(diff, str) else ""
            file_list = "\n".join(
                f"  {f.get('filename', '?')} (+{f.get('additions', 0)} -{f.get('deletions', 0)})"
                for f in (files if isinstance(files, list) else [])
            )

            pr_summaries.append({
                "repo": repo,
                "number": number,
                "title": title,
                "author": author,
                "url": url,
                "file_list": file_list,
                "diff": diff_text,
            })
            log.info("pr_security: prepared %s#%d (%d chars diff)", repo, number, len(diff_text))

        # Embed PR data directly in a format the LLM can't miss
        pr_text_blocks = []
        for pr in pr_summaries:
            block = f"""
=== PR: {pr['repo']}#{pr['number']} ===
Title: {pr['title']}
Author: {pr['author']}
URL: {pr['url']}
Files changed:
{pr['file_list']}

DIFF:
{pr['diff']}
=== END PR ===
"""
            pr_text_blocks.append(block)

        ctx["pr_review_data"] = "\n".join(pr_text_blocks)
        ctx["pr_count"] = str(len(pr_summaries))
        ctx["pr_repos"] = json.dumps([{"repo": p["repo"], "number": p["number"], "title": p["title"]} for p in pr_summaries])
        ctx["dry_run"] = str(dry_run)
        return ctx

    @agent
    def security_reviewer(self) -> Agent:
        return Agent(
            config=self.agents_config["security_reviewer"],
            tools=[post_pr_review_comment],
            verbose=True,
        )

    @task
    def review_and_post(self) -> Task:
        return Task(config=self.tasks_config["review_and_post"])

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            planning=False,
            memory=False,
        )

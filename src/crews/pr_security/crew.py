import json
import logging
import os
import tempfile

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, before_kickoff, crew, task

from shared.tools import (
    list_open_prs, get_pr_diff, get_pr_files, post_pr_review_comment,
)
from shared.tools.file_reader import read_file

log = logging.getLogger(__name__)


@CrewBase
class PRSecurityCrew:
    """Scans open PRs for security issues — one subagent per PR.

    before_kickoff:
    1. Fetches all open PRs
    2. For each PR, saves the FULL diff to a temp file (no truncation)
    3. Creates a task per PR with the file path

    Each task gets the full diff via file reading — no context limit issues.
    The LLM reads the file, analyzes thoroughly, and posts findings.
    """

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    _pr_tasks: list = []

    @before_kickoff
    def inject_context(self, inputs):
        ctx = inputs or {}
        dry_run = str(ctx.get("dry_run", "true")).lower() == "true"
        repo_filter = ctx.get("repo", "")

        # ── 1. Fetch open PRs ──
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
            ctx["no_prs"] = "true"
            ctx["dry_run"] = str(dry_run)
            return ctx

        # ── 2. For each PR, save full diff to temp file ──
        pr_entries = []
        for pr in prs[:15]:  # Process up to 15 PRs per run
            repo = pr.get("repo", "")
            number = pr.get("number", 0)
            title = pr.get("title", "")
            author = pr.get("author", {}).get("login", "unknown") if isinstance(pr.get("author"), dict) else str(pr.get("author", "unknown"))
            url = pr.get("url", "")

            # Get full diff — NO truncation
            try:
                diff = get_pr_diff.run(repo=repo, pr_number=number)
            except Exception as e:
                log.warning("pr_security: diff failed for %s#%d: %s", repo, number, e)
                diff = f"Error fetching diff: {e}"

            # Get changed files
            try:
                files_result = get_pr_files.run(repo=repo, pr_number=number)
                files = json.loads(files_result) if isinstance(files_result, str) else files_result
            except Exception:
                files = []

            # Save full diff to temp file
            diff_path = os.path.join(tempfile.gettempdir(), f"pr_{repo}_{number}.diff")
            with open(diff_path, "w") as f:
                f.write(diff if isinstance(diff, str) else "")

            diff_size = os.path.getsize(diff_path)
            file_count = len(files) if isinstance(files, list) else 0

            file_list = "\n".join(
                f"  {fi.get('filename', '?')} (+{fi.get('additions', 0)} -{fi.get('deletions', 0)})"
                for fi in (files if isinstance(files, list) else [])
            )

            pr_entries.append({
                "repo": repo,
                "number": number,
                "title": title,
                "author": author,
                "url": url,
                "diff_path": diff_path,
                "diff_size": diff_size,
                "file_count": file_count,
                "file_list": file_list,
            })

            log.info("pr_security: saved %s#%d diff → %s (%d bytes, %d files)",
                     repo, number, diff_path, diff_size, file_count)

        ctx["pr_entries"] = json.dumps(pr_entries)
        ctx["pr_count"] = str(len(pr_entries))
        ctx["dry_run"] = str(dry_run)
        ctx["no_prs"] = "false"

        # Build a summary for the orchestrator task
        summary_lines = []
        for p in pr_entries:
            summary_lines.append(
                f"- {p['repo']}#{p['number']}: {p['title']} "
                f"({p['file_count']} files, {p['diff_size']} bytes) "
                f"→ diff at {p['diff_path']}"
            )
        ctx["pr_summary"] = "\n".join(summary_lines)

        return ctx

    @agent
    def security_reviewer(self) -> Agent:
        return Agent(
            config=self.agents_config["security_reviewer"],
            tools=[post_pr_review_comment, read_file],
            verbose=True,
        )

    @task
    def review_all_prs(self) -> Task:
        return Task(config=self.tasks_config["review_all_prs"])

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

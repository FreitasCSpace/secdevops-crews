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
    """Hierarchical PR security review — manager delegates PRs to reviewers.

    before_kickoff: fetches PRs, saves full diffs to temp files
    Manager agent: coordinates reviews, assigns PRs to reviewer agents
    Reviewer agents: read diffs via read_file, analyze, post findings

    Skills loaded from src/shared/skills/ (OWASP + HIPAA + CareSpace)
    """

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

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
            ctx["pr_count"] = "0"
            ctx["pr_entries"] = "[]"
            return ctx

        # ── 2. Save full diffs to temp files ──
        pr_entries = []
        for pr in prs[:15]:
            repo = pr.get("repo", "")
            number = pr.get("number", 0)
            title = pr.get("title", "")
            author = pr.get("author", {}).get("login", "unknown") if isinstance(pr.get("author"), dict) else str(pr.get("author", "unknown"))
            url = pr.get("url", "")

            try:
                diff = get_pr_diff.run(repo=repo, pr_number=number)
            except Exception as e:
                log.warning("pr_security: diff failed for %s#%d: %s", repo, number, e)
                diff = f"Error fetching diff: {e}"

            try:
                files_result = get_pr_files.run(repo=repo, pr_number=number)
                files = json.loads(files_result) if isinstance(files_result, str) else files_result
            except Exception:
                files = []

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
            log.info("pr_security: saved %s#%d → %s (%d bytes, %d files)",
                     repo, number, diff_path, diff_size, file_count)

        ctx["pr_entries"] = json.dumps(pr_entries)
        ctx["pr_count"] = str(len(pr_entries))
        ctx["dry_run"] = str(dry_run)
        ctx["no_prs"] = "false"
        return ctx

    # ── Manager agent: coordinates and delegates ──

    @agent
    def review_manager(self) -> Agent:
        return Agent(
            config=self.agents_config["review_manager"],
            tools=[],
            verbose=True,
            allow_delegation=True,
        )

    # ── Reviewer agent: reads diffs, analyzes, posts findings ──

    @agent
    def security_reviewer(self) -> Agent:
        return Agent(
            config=self.agents_config["security_reviewer"],
            tools=[post_pr_review_comment, read_file],
            verbose=True,
            allow_delegation=False,
        )

    @task
    def review_all_prs(self) -> Task:
        return Task(config=self.tasks_config["review_all_prs"])

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.hierarchical,
            manager_agent=self.review_manager(),
            verbose=True,
            planning=False,
            memory=False,
            skills=["src/shared/skills"],
        )

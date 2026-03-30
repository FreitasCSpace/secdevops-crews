from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, before_kickoff, crew, task

from shared.tools import (
    list_open_prs, get_pr_diff, get_pr_files, post_pr_review_comment,
)


@CrewBase
class PRSecurityCrew:
    """Scans open PRs for security issues and posts findings as comments.

    before_kickoff: fetches open PRs and their diffs (Python)
    LLM: analyzes diffs for security vulnerabilities + code quality (real LLM value)
    LLM: posts findings as PR comments via gh CLI
    """

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @before_kickoff
    def inject_context(self, inputs):
        import json, logging
        log = logging.getLogger(__name__)

        ctx = inputs or {}

        # ── Fetch open PRs ──
        try:
            prs_result = list_open_prs.run(repo=ctx.get("repo", ""))
            prs = json.loads(prs_result) if isinstance(prs_result, str) else prs_result
            if isinstance(prs, dict) and "error" in prs:
                prs = []
            log.info("pr_security: found %d open PRs", len(prs))
        except Exception as e:
            log.warning("pr_security: PR fetch failed: %s", e)
            prs = []

        if not prs:
            ctx["pr_data"] = json.dumps({"prs": [], "message": "No open PRs found."})
            return ctx

        # ── Fetch diff for each PR ──
        pr_data = []
        for pr in prs[:10]:  # Limit to 10 PRs per run
            repo = pr.get("repo", "")
            number = pr.get("number", 0)
            try:
                diff = get_pr_diff.run(repo=repo, pr_number=number)
                files_result = get_pr_files.run(repo=repo, pr_number=number)
                files = json.loads(files_result) if isinstance(files_result, str) else files_result
            except Exception as e:
                log.warning("pr_security: diff fetch failed for %s#%d: %s", repo, number, e)
                diff = ""
                files = []

            pr_data.append({
                "repo": repo,
                "number": number,
                "title": pr.get("title", ""),
                "author": pr.get("author", {}).get("login", "unknown"),
                "url": pr.get("url", ""),
                "additions": pr.get("additions", 0),
                "deletions": pr.get("deletions", 0),
                "files": files if isinstance(files, list) else [],
                "diff": diff[:30000] if isinstance(diff, str) else "",  # Cap diff size
            })
            log.info("pr_security: fetched diff for %s#%d (%d chars)",
                     repo, number, len(pr_data[-1]["diff"]))

        ctx["pr_data"] = json.dumps({"prs": pr_data}, indent=2)
        return ctx

    @agent
    def security_reviewer(self) -> Agent:
        return Agent(
            config=self.agents_config["security_reviewer"],
            tools=[post_pr_review_comment],
            verbose=True,
        )

    @task
    def review_prs(self) -> Task:
        return Task(config=self.tasks_config["review_prs"])

    @task
    def post_findings(self) -> Task:
        return Task(config=self.tasks_config["post_findings"])

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

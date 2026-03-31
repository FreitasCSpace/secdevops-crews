"""SecDevOps Crews Flow — CrewHub entry point.

CrewHub detects this as a Flow (via [tool.crewai] type = "flow" in pyproject.toml)
and calls kickoff(). Inputs arrive via CREWHUB_INPUT_KWARGS env var.

Usage from CrewHub:
    crew_name: "pr_security"    (required)
    repo: "carespace-ui"        (optional — empty = scan all repos)

Architecture:
    @start  → load_inputs (parse CrewHub env, validate crew_name)
    @listen → run_crew    (execute the requested crew)
    @listen → build_output (compile summary + ensure artifacts)
"""

import importlib
import json
import logging
import os
from typing import Optional

from crewai.flow.flow import Flow, start, listen
from crewai.flow.persistence import persist
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


class SecDevOpsState(BaseModel):
    crew_name: str = Field(default="pr_security", description="Crew to run")
    repo: str = Field(default="", description="Specific repo to scan (empty = all)")
    dry_run: str = Field(default="true", description="true = show findings only, false = post PR comments")
    crew_inputs: dict = {}
    crew_raw_output: str = ""
    crew_success: bool = False
    crew_error: Optional[str] = None


CREW_REGISTRY = {
    "pr_security": ("crews.pr_security.crew", "PRSecurityCrew"),
}


@persist()
class SecDevOpsFlow(Flow[SecDevOpsState]):
    """Orchestrates SecDevOps crews with typed state and persistence.

    CrewHub Input: {crew_name, repo?}

    Steps:
        1. load_inputs   — parse CrewHub env, validate crew_name
        2. run_crew      — execute the requested crew
        3. build_output  — compile summary for CrewHub output display
    """

    @start()
    def load_inputs(self):
        """Parse CrewHub env var and validate crew_name."""
        raw = os.environ.get("CREWHUB_INPUT_KWARGS", "{}")
        inputs = json.loads(raw) if raw else {}

        self.state.crew_name = inputs.pop("crew_name", self.state.crew_name or "pr_security")
        self.state.repo = inputs.pop("repo", self.state.repo or "")
        self.state.dry_run = inputs.pop("dry_run", self.state.dry_run or "true")
        self.state.crew_inputs = {
            "repo": self.state.repo,
            "dry_run": self.state.dry_run,
            **inputs,
        }

        if self.state.crew_name not in CREW_REGISTRY:
            available = ", ".join(sorted(CREW_REGISTRY.keys()))
            raise ValueError(f"Unknown crew '{self.state.crew_name}'. Available: {available}")

        log.info("[%s] Inputs loaded", self.state.crew_name)

    @listen(load_inputs)
    def run_crew(self):
        """Execute the requested crew with inputs."""
        module_path, cls_name = CREW_REGISTRY[self.state.crew_name]
        module = importlib.import_module(module_path)
        crew_cls = getattr(module, cls_name)

        try:
            result = crew_cls().crew().kickoff(inputs=self.state.crew_inputs)
            self._crew_result = result
            self.state.crew_raw_output = result.raw if hasattr(result, "raw") else str(result)
            self.state.crew_success = True
            log.info("[%s] Crew completed successfully", self.state.crew_name)
        except Exception as e:
            self._crew_result = None
            self.state.crew_error = str(e)
            self.state.crew_success = False
            log.error("[%s] Failed: %s", self.state.crew_name, e)
            raise

    @listen(run_crew)
    def build_output(self):
        """Compile summary for CrewHub output display and ensure artifacts exist."""
        # Search for output files in multiple possible locations
        cwd = os.getcwd()
        possible_dirs = [
            os.path.join(cwd, "output"),
            "/app/output",
            os.path.join(cwd, "src", "output"),
            "output",
        ]
        output_dir = None
        output_files = []
        for d in possible_dirs:
            if os.path.isdir(d):
                files = [f for f in os.listdir(d) if f.endswith(".md")]
                if files:
                    output_dir = d
                    output_files = files
                    break

        log.info("[%s] cwd=%s output_dir=%s files=%s", self.state.crew_name, cwd, output_dir, output_files)

        # Build CrewHub output message
        pr_count = self.state.crew_inputs.get("pr_count", "?")
        dry_run = self.state.dry_run

        lines = [
            f"## SecDevOps — PR Security Review",
            f"",
            f"**Mode:** {'Dry Run (no comments posted)' if dry_run == 'true' else 'Live (comments posted to PRs)'}",
            f"**Repo filter:** {self.state.repo or 'all repos'}",
            f"",
        ]

        # Try to extract PR info from crew inputs
        try:
            pr_entries = json.loads(self.state.crew_inputs.get("pr_entries", "[]"))
            if pr_entries:
                lines.append(f"**PRs reviewed:** {len(pr_entries)}")
                lines.append("")
                for pr in pr_entries:
                    repo = pr.get("repo", "?")
                    number = pr.get("number", "?")
                    title = pr.get("title", "?")
                    files = pr.get("file_count", "?")
                    lines.append(f"- **{repo}#{number}** — {title} ({files} files)")
                lines.append("")
        except Exception:
            pass

        if output_files:
            lines.append(f"**Review files:** {len(output_files)}")
            for f in sorted(output_files):
                lines.append(f"- `{f}`")
            lines.append("")

        # Append crew raw output (the LLM's final summary)
        if self.state.crew_raw_output:
            lines.append("---")
            lines.append("")
            lines.append(self.state.crew_raw_output)

        summary = "\n".join(lines)
        print(f"[{self.state.crew_name}] Complete.", flush=True)
        return summary


def main():
    flow = SecDevOpsFlow()
    flow.kickoff()


if __name__ == "__main__":
    main()

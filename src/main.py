"""SecDevOps Crews Flow — CrewHub entry point.

CrewHub detects this as a Flow (via [tool.crewai] type = "flow" in pyproject.toml)
and calls kickoff(). Inputs arrive via CREWHUB_INPUT_KWARGS env var.

Usage from CrewHub:
    crew_name: "pr_security"    (required)
    repo: "carespace-ui"        (optional — empty = scan all repos)

Architecture:
    @start  → load_inputs  (parse CrewHub env, validate crew_name)
    @listen → run_crew     (execute the requested crew)
    @listen → build_output (write per-PR .md files + compile summary)
"""

import importlib
import json
import logging
import os
import re
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

    @start()
    def load_inputs(self):
        """Parse CrewHub env var and validate crew_name."""
        raw = os.environ.get("CREWHUB_INPUT_KWARGS", "{}")
        inputs = json.loads(raw) if raw else {}

        self.state.crew_name = inputs.get("crew_name", self.state.crew_name or "pr_security")
        self.state.repo = inputs.get("repo", "")
        self.state.dry_run = inputs.get("dry_run", "true")
        self.state.crew_inputs = {
            "repo": self.state.repo,
            "dry_run": self.state.dry_run,
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
        """Write per-PR review .md files and compile CrewHub output summary.

        The LLM produces the security reviews but can't be trusted to call
        write_review_file. So we parse its output here and write files from Python.
        """
        output_dir = os.path.join(os.getcwd(), "output")
        os.makedirs(output_dir, exist_ok=True)

        raw = self.state.crew_raw_output or ""
        written_files = []

        # ── 1. Extract all task outputs (not just final) ──
        full_text = raw
        result_obj = getattr(self, "_crew_result", None)
        if result_obj and hasattr(result_obj, "tasks_output") and result_obj.tasks_output:
            sections = []
            for task_out in result_obj.tasks_output:
                task_raw = ""
                if hasattr(task_out, "raw"):
                    task_raw = str(task_out.raw or "")
                elif hasattr(task_out, "output"):
                    task_raw = str(task_out.output or "")
                if task_raw.strip():
                    sections.append(task_raw)
            if sections:
                full_text = "\n\n---\n\n".join(sections)

        # ── 2. Write full review output as one file ──
        if full_text.strip() and len(full_text.strip()) > 50:
            full_path = os.path.join(output_dir, "full_review.md")
            with open(full_path, "w") as fh:
                fh.write(full_text)
            written_files.append("full_review.md")
            log.info("[%s] wrote output/full_review.md (%d chars)", self.state.crew_name, len(full_text))

        # ── 3. Try to split by PR sections and write individual files ──
        # Look for patterns like "## 🔒 Security Review" or "## PR #123" or "repo#number"
        pr_sections = re.split(r'(?=^## .*(?:Security Review|PR\s*[#\d]|🔒))', full_text, flags=re.MULTILINE)
        pr_sections = [s.strip() for s in pr_sections if s.strip() and len(s.strip()) > 100]

        if len(pr_sections) > 1:
            for section in pr_sections:
                # Try to extract repo#number from section
                match = re.search(r'(\w[\w.-]+)#(\d+)', section)
                if match:
                    pr_repo = match.group(1)
                    pr_num = match.group(2)
                    fname = f"{pr_repo}_{pr_num}.md"
                else:
                    # Fallback: use index
                    idx = pr_sections.index(section)
                    fname = f"review_{idx + 1}.md"

                pr_path = os.path.join(output_dir, fname)
                with open(pr_path, "w") as fh:
                    fh.write(section)
                written_files.append(fname)
                log.info("[%s] wrote output/%s", self.state.crew_name, fname)

        # ── 4. Also check if LLM wrote files via write_review_file tool ──
        for existing in os.listdir(output_dir):
            if existing.endswith(".md") and existing not in written_files:
                written_files.append(existing)

        # ── 5. Write summary.md ──
        pr_entries = []
        try:
            pr_entries = json.loads(self.state.crew_inputs.get("pr_entries", "[]"))
        except Exception:
            pass

        summary_lines = [
            "# SecDevOps — PR Security Review Summary",
            "",
            f"**Mode:** {'Dry Run' if self.state.dry_run == 'true' else 'Live'}",
            f"**Repo filter:** {self.state.repo or 'all repos'}",
            f"**PRs analyzed:** {len(pr_entries) if pr_entries else '?'}",
            f"**Review files:** {len(written_files)}",
            "",
        ]

        if pr_entries:
            summary_lines.append("## PRs Reviewed")
            summary_lines.append("")
            for entry in pr_entries:
                summary_lines.append(
                    f"- **{entry.get('repo', '?')}#{entry.get('number', '?')}** "
                    f"— {entry.get('title', '?')} ({entry.get('file_count', '?')} files)"
                )
            summary_lines.append("")

        if written_files:
            summary_lines.append("## Output Files")
            summary_lines.append("")
            for fname in sorted(written_files):
                summary_lines.append(f"- `output/{fname}`")
            summary_lines.append("")

        summary_md = "\n".join(summary_lines)
        summary_path = os.path.join(output_dir, "summary.md")
        with open(summary_path, "w") as fh:
            fh.write(summary_md)
        log.info("[%s] wrote output/summary.md", self.state.crew_name)

        # ── 6. Return summary as CrewHub output message ──
        output_lines = summary_lines.copy()
        if raw and len(raw.strip()) > 50:
            output_lines.append("---")
            output_lines.append("")
            # Truncate for display if very long
            display_raw = raw if len(raw) < 5000 else raw[:5000] + "\n\n... (truncated)"
            output_lines.append(display_raw)

        print(f"[{self.state.crew_name}] Complete. {len(written_files)} files written to output/", flush=True)
        return "\n".join(output_lines)


def main():
    flow = SecDevOpsFlow()
    flow.kickoff()


if __name__ == "__main__":
    main()

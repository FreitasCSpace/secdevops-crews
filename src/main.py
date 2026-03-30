"""SecDevOps Crews Flow — CrewHub entry point.

CrewHub detects this as a Flow (via [tool.crewai] type = "flow" in pyproject.toml)
and calls kickoff(). Inputs arrive via CREWHUB_INPUT_KWARGS env var.

Usage from CrewHub:
    crew_name: "pr_security"    (required)
    repo: "carespace-ui"        (optional — empty = scan all repos)

Architecture:
    @start  → load_inputs (parse CrewHub env, validate crew_name)
    @listen → run_crew    (execute the requested crew)
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
    crew_name: str = ""
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
        1. load_inputs  — parse CrewHub env, validate crew_name
        2. run_crew     — execute the requested crew
    """

    @start()
    def load_inputs(self):
        """Parse CrewHub env var and validate crew_name."""
        raw = os.environ.get("CREWHUB_INPUT_KWARGS", "{}")
        inputs = json.loads(raw) if raw else {}

        self.state.crew_name = inputs.pop("crew_name", "pr_security")
        self.state.crew_inputs = inputs

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
            log.info("[%s] Complete", self.state.crew_name)
        except Exception as e:
            self._crew_result = None
            self.state.crew_error = str(e)
            self.state.crew_success = False
            log.error("[%s] Failed: %s", self.state.crew_name, e)
            raise


def main():
    flow = SecDevOpsFlow()
    flow.kickoff()


if __name__ == "__main__":
    main()

"""
SecDevOps Crews — PR Security Scanner

Single Flow that dispatches to security crews.
Currently: pr_security crew scans open PRs and posts findings as comments.
"""

import os
import json
import logging
import importlib
from crewai.flow.flow import Flow, listen, start
from crewai.flow.persistence import persist
from pydantic import BaseModel

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


class SecDevOpsState(BaseModel):
    crew_name: str = ""
    crew_inputs: dict = {}
    crew_result: str = ""
    crew_success: bool = False


CREW_REGISTRY = {
    "pr_security": ("crews.pr_security.crew", "PRSecurityCrew"),
}


@persist()
class SecDevOpsFlow(Flow[SecDevOpsState]):
    """Dispatches to SecDevOps crews."""

    @start()
    def load_inputs(self):
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
        module_path, cls_name = CREW_REGISTRY[self.state.crew_name]
        module = importlib.import_module(module_path)
        crew_cls = getattr(module, cls_name)

        try:
            result = crew_cls().crew().kickoff(inputs=self.state.crew_inputs)
            self.state.crew_result = result.raw if hasattr(result, "raw") else str(result)
            self.state.crew_success = True
            log.info("[%s] Complete", self.state.crew_name)
        except Exception as e:
            self.state.crew_result = str(e)
            self.state.crew_success = False
            log.error("[%s] Failed: %s", self.state.crew_name, e)
            raise


def main():
    flow = SecDevOpsFlow()
    flow.kickoff()


if __name__ == "__main__":
    main()

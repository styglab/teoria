"""Harness2 adapter: source-only Codex proposals and probes on development documents.

The upstream framework owns Propose–Probe–Compose and its experience library.
Codex is used through a text-only proposer so neither holdout labels nor the
repository filesystem is exposed to an improver session.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .codex_runner import CodexRunner
from .search_evaluation import EXTRACTION_INSTRUCTION, save_json
from .search_experiment import load, verify_corpus


def adapt(root: Path, *, model: str | None, tasks: int = 2) -> dict:
    from harness2.core import tree
    from harness2.core.proposer import Proposer, Reply
    from harness2.core.schedule import run_domain
    from harness2.core.spec import BenchPrompts, BenchSpec, ChannelSpec
    from harness2.substrate.codex import CodexSubstrate

    verify_corpus(root)
    if tasks < 1:
        raise ValueError("positive task count required")
    work = root / "harness2"

    class Adapter:
        substrate = CodexSubstrate()

        def __init__(self):
            channel = ChannelSpec("opencode", model or "configured_codex")
            self.spec = BenchSpec(
                name="teoria_specifications", runs_root=work / "runs", install_mode="codex_root",
                prompts=BenchPrompts(work="extract evidence-grounded equipment requirements from procurement specifications"),
                channels={"proposer": channel, "selector": channel},
                leak_globs=("*labels*", "*expected*", "*validation*", "*reports*"),
            )
            tree.write_tree(self.substrate.surface(), {"AGENTS.md": EXTRACTION_INSTRUCTION}, self.base_harness(), stubs=False)
            self.identities = sorted(p.stem for p in (root / "sources/development").glob("*.json"))

        def tasks(self, split="all"):
            if split not in {"all", "development"}:
                raise ValueError("adapter only exposes development")
            return self.identities[:tasks]

        def domain_of(self, task_id):
            return "specifications"

        def task_prompt(self, task_id):
            return "Extract numerical equipment requirements from source.json as facts, preserving source evidence and scope."

        def task_files(self, task_id):
            if task_id not in self.identities:
                raise ValueError("unknown development task")
            directory = work / "source" / task_id
            directory.mkdir(parents=True, exist_ok=True)
            save_json(directory / "source.json", load(root / "sources/development" / f"{task_id}.json"))
            return directory

        def base_harness(self):
            return work / "base"

        def validate_tree(self, harness):
            if set(harness) != {"AGENTS.md"} or not harness["AGENTS.md"].strip():
                raise ValueError("this experiment permits AGENTS.md prompt edits only")

        def execute(self, task_id, harness_dir, run_id, *, timeout=None):
            self.task_files(task_id)
            directory = work / "executions" / run_id
            instruction = ((harness_dir or self.base_harness()) / "AGENTS.md").read_text()
            source = load(root / "sources/development" / f"{task_id}.json")
            result = asyncio.run(CodexRunner(model=model).generate(instruction, {"source": source}, directory / "facts.json"))
            save_json(directory / "trajectory.json", {"action": "Codex source-only extraction", "result": result})
            return directory

        def delivered(self, directory):
            return (directory / "facts.json").exists()

        def trajectory(self, directory, *, obs_trunc):
            return (directory / "trajectory.json").read_text()

        def deliverable_text(self, directory):
            return (directory / "facts.json").read_text()

        def deliverable_files(self, directory):
            return {"facts.json": self.deliverable_text(directory)}

    class CodexProposer(Proposer):
        def call(self, mission, context_dir, label, **kwargs):
            directory = Path(context_dir)
            # Only the framework-created source/evidence tree is serialized. No tools
            # are given to Codex and no original absolute paths are passed as instructions.
            files = {str(p.relative_to(directory)): p.read_text() for p in sorted(directory.rglob("*"))
                     if p.is_file() and p.suffix in {".md", ".json", ".txt", ".py"}}
            instruction = (
                "You are the Codex proposer in Harness2. Follow the mission using only provided files. "
                "Return JSON {files:[{path,content}],reply:string}. Only AGENTS.md may be edited. "
                "Keep the exact fact field contract and JSON output shape. Do not add tools or scripts. "
                "Return the complete AGENTS.md content for proposal/composition, with <notes> in reply. "
                "For selection return files:[] and the requested <why> and ```choice``` reply. "
                "For experience return files:[] and <edits>/<experience> (or NO_ENTRY). "
                "Use observed source fidelity, never a hidden answer or a grade."
            )
            cache = work / "proposer" / f"{len(self._calls):04}_{label.replace('/', '_')}.json"
            result = asyncio.run(CodexRunner(model=model).generate(instruction, {"mission": mission, "files": files}, cache))
            workspace = directory / "harness" if kwargs.get("harvest") else None
            for edit in result.get("files", []):
                if edit["path"] != "AGENTS.md" or workspace is None:
                    raise ValueError("proposer tried to edit outside the prompt surface")
                (workspace / "AGENTS.md").write_text(edit["content"])
            reply = Reply(label=label, text=result["reply"], ok=True, attempts=1, workspace=workspace, channel="codex_exec")
            self._calls.append(reply)
            print(f"Harness2 Codex {label}", flush=True)
            return reply

    adapter = Adapter()
    proposer = CodexProposer(spec=adapter.spec.channels["proposer"])
    result = run_domain("specifications", adapter.tasks(), 1, adapter=adapter, prop=proposer,
                        runs_root=adapter.spec.runs_root, library_root=work / "library", modes=("seq",))
    save_json(work / "result.json", result)
    # Export every surviving composed prompt; an external development-only comparison
    # chooses one before the held-out questions are opened by the final grader.
    candidates = sorted((work / "runs").glob("*/**/harnesses/c1/AGENTS.md"))
    for index, path in enumerate(candidates):
        target = work / "candidates" / f"candidate_{index:02}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(path.read_text())
    if result["failed"] or not candidates:
        raise RuntimeError(f"Harness2 adaptation incomplete: {result}")
    return result

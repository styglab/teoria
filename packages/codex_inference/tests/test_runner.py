import asyncio
import json
from pathlib import Path

import pytest

from teoria_codex_inference import CodexRunner


class Process:
    returncode = 0
    pid = 12345

    def __init__(self, answer, events):
        self.answer, self.events = answer, events

    async def communicate(self, prompt):
        self.answer.write_text('{"ready":true}')
        return b"\n".join(json.dumps(e).encode() for e in self.events), b""

    async def wait(self):
        return 0


async def test_text_inference_cache_and_changed_prompt_rejection(monkeypatch, tmp_path):
    calls = []

    async def spawn(*argv, **kwargs):
        calls.append((argv, kwargs))
        return Process(Path(argv[argv.index("-o") + 1]), [{"type": "turn.completed"}])

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    runner = CodexRunner()
    output = tmp_path / "answer.json"
    assert await runner.generate("instruction", {}, output) == {"ready": True}
    assert await runner.generate("instruction", {}, output) == {"ready": True}
    assert len(calls) == 1
    assert calls[0][1]["start_new_session"] is True
    assert "read-only" in calls[0][0]
    with pytest.raises(ValueError, match="stale"):
        await runner.generate("changed instruction", {}, output)


async def test_inference_rejects_tool_use_without_caching(monkeypatch, tmp_path):
    async def spawn(*argv, **kwargs):
        return Process(Path(argv[argv.index("-o") + 1]), [{"type": "item.completed", "item": {"type": "command_execution"}}])

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    output = tmp_path / "answer.json"
    with pytest.raises(RuntimeError, match="used a tool"):
        await CodexRunner().generate("instruction", {}, output)
    assert not output.exists()


async def test_cancellation_kills_process_group(monkeypatch, tmp_path):
    started = asyncio.Event()
    killed = []

    class WaitingProcess(Process):
        async def communicate(self, prompt=None):
            if started.is_set():
                return b"", b""
            started.set()
            await asyncio.Event().wait()

    async def spawn(*argv, **kwargs):
        return WaitingProcess(Path(argv[argv.index("-o") + 1]), [])

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr("os.killpg", lambda pid, sig: killed.append(pid))
    task = asyncio.create_task(CodexRunner().generate("instruction", {}, tmp_path / "answer.json"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert killed == [12345]


def test_provider_schema_requires_all_fields_and_preserves_local_validation_contract():
    from teoria_codex_inference import strict_output_schema
    original={'type':'object','properties':{'value':{'type':'string','default':'1','pattern':r'^(?!x)\d+$'}},'required':[]}
    result=strict_output_schema(original)
    assert result['required']==['value'] and result['additionalProperties'] is False
    assert 'pattern' not in result['properties']['value']
    assert 'default' not in result['properties']['value']
    assert original['properties']['value']['pattern']==r'^(?!x)\d+$'


async def test_authoring_control_credentials_are_not_inherited_by_inference(monkeypatch,tmp_path):
    monkeypatch.setenv('TEORIA_SPECIFICATION_AUTHORING_API_TOKEN','test-authoring-token')
    monkeypatch.setenv('TEORIA_ADMIN_API_TOKEN','test-admin-token')
    async def spawn(*argv,**kwargs):
        assert kwargs['env'].get('TEORIA_SPECIFICATION_AUTHORING_API_TOKEN') is None
        assert kwargs['env'].get('TEORIA_ADMIN_API_TOKEN') is None
        return Process(Path(argv[argv.index('-o')+1]),[])
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
    assert await CodexRunner().generate('instruction',{},tmp_path/'answer.json')=={'ready':True}

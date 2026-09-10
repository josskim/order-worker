import asyncio
from types import SimpleNamespace
from order_worker import local_dispatcher as dispatcher


def test_cancel_kills_only_spawned_job_tree(monkeypatch):
    calls = []
    class Process:
        pid = 123456
        returncode = None
        async def wait(self):
            self.returncode = 0
            return 0
    process = Process()
    async def spawn(*args, **kwargs):
        calls.append(('spawn', args))
        return process
    monkeypatch.setattr(dispatcher.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(dispatcher.database_transport, 'is_job_cancelled', lambda *_: True)
    monkeypatch.setattr(dispatcher.subprocess, 'run', lambda args, **kw: calls.append(('kill', args)))
    assert asyncio.run(dispatcher.isolated_job('test-job', 'product-status')) == 0
    assert calls[1] == ('kill', ['taskkill', '/PID', '123456', '/T', '/F'])


def test_successful_child_does_not_get_killed(monkeypatch):
    async def spawn(*args, **kwargs):
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(dispatcher.asyncio, 'create_subprocess_exec', spawn)
    assert asyncio.run(dispatcher.isolated_job('test-job', 'product-status')) == 0

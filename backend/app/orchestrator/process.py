"""Launch, health-check and tear down a single OS process.

Windows has no SIGTERM, so "graceful" stop means sending CTRL_BREAK_EVENT to
the process group (requires the child to have been started with
CREATE_NEW_PROCESS_GROUP) and waiting; if it doesn't exit in time we fall
back to `taskkill /T /F`, which also reaps children `uv run` / `cmd` spawn
that CTRL_BREAK alone would miss.
"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from typing import Optional

import httpx

from ..config import LOG_DIR, LOG_TAIL_LINES, ProcessSpec

IS_WINDOWS = sys.platform == "win32"


class StartCancelled(Exception):
    """A model start was abandoned because Stop or shutdown was requested."""


def _build_env(spec: ProcessSpec) -> dict[str, str]:
    env = os.environ.copy()
    env.update(spec.env)
    if spec.extra_path_dirs:
        prefix = os.pathsep.join(str(p) for p in spec.extra_path_dirs)
        env["PATH"] = f"{prefix}{os.pathsep}{env.get('PATH', '')}"
    return env


def tail_log(name: str, lines: int = LOG_TAIL_LINES) -> str:
    path = LOG_DIR / f"{name}.log"
    if not path.exists():
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(content.splitlines()[-lines:])


class ManagedProcess:
    def __init__(self, spec: ProcessSpec):
        self.spec = spec
        self._proc: Optional[subprocess.Popen] = None
        self._log_file = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def exit_summary(self) -> str:
        code = self._proc.returncode if self._proc else None
        return f"process '{self.spec.name}' exited (code {code}).\n{tail_log(self.spec.name)}"

    def start(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"{self.spec.name}.log"
        self._log_file = open(log_path, "w", encoding="utf-8", errors="replace")
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
        self._proc = subprocess.Popen(
            self.spec.cmd,
            cwd=str(self.spec.cwd),
            env=_build_env(self.spec),
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )

    async def wait_healthy(self, cancel: Optional[asyncio.Event] = None) -> None:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.spec.startup_timeout
        async with httpx.AsyncClient(timeout=3.0) as client:
            while True:
                if cancel is not None and cancel.is_set():
                    raise StartCancelled(f"start of '{self.spec.name}' was cancelled")
                if not self.is_running:
                    code = self._proc.returncode if self._proc else None
                    raise RuntimeError(
                        f"process '{self.spec.name}' exited during startup (code {code}).\n"
                        f"{tail_log(self.spec.name)}"
                    )
                if self.spec.health_url:
                    try:
                        resp = await client.get(self.spec.health_url)
                        if resp.status_code < 500:
                            return
                    except httpx.HTTPError:
                        pass
                else:
                    return
                if loop.time() > deadline:
                    raise TimeoutError(
                        f"process '{self.spec.name}' did not become healthy within "
                        f"{self.spec.startup_timeout:.0f}s.\n{tail_log(self.spec.name)}"
                    )
                if cancel is None:
                    await asyncio.sleep(1.0)
                else:
                    try:
                        await asyncio.wait_for(cancel.wait(), 1.0)
                    except asyncio.TimeoutError:
                        pass

    async def wait_stopped(self, timeout: float) -> bool:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while self.is_running:
            if loop.time() > deadline:
                return False
            await asyncio.sleep(0.5)
        return True

    async def stop(self) -> None:
        if not self.is_running:
            self._close_log()
            return
        pid = self._proc.pid
        if IS_WINDOWS:
            try:
                self._proc.send_signal(signal.CTRL_BREAK_EVENT)
            except (OSError, ValueError):
                pass
        else:
            self._proc.terminate()
        stopped = await self.wait_stopped(self.spec.shutdown_timeout)
        if not stopped:
            await self._force_kill(pid)
            if not await self.wait_stopped(10.0):
                raise RuntimeError(f"process '{self.spec.name}' did not stop; refusing to start another copy")
        self._close_log()

    async def _force_kill(self, pid: int) -> None:
        if IS_WINDOWS:
            proc = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        else:
            try:
                self._proc.kill()
            except OSError:
                pass

    def _close_log(self) -> None:
        if self._log_file:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None

import asyncio
import unittest
from unittest.mock import AsyncMock

from app.orchestrator.manager import OrchestratorManager
from app.orchestrator.process import StartCancelled
from app.orchestrator.state import ModelStatus


class ResetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = OrchestratorManager()
        self.manager.state.active_model = "yue2"
        self.manager.state.models["yue2"].status = ModelStatus.RUNNING

    async def test_restart_waits_for_old_process_to_exit(self):
        entered = asyncio.Event()
        exited = asyncio.Event()

        async def stop(_model):
            entered.set()
            await exited.wait()

        self.manager._stop_processes = stop
        self.manager._start_model = AsyncMock()
        restart = asyncio.create_task(self.manager.restart_model("yue2"))
        await entered.wait()
        self.manager._start_model.assert_not_awaited()
        self.assertEqual(self.manager.state.models["yue2"].status, ModelStatus.STOPPING)
        exited.set()
        await restart
        self.manager._start_model.assert_awaited_once_with("yue2")

    async def test_failed_stop_never_starts_another_copy(self):
        self.manager._stop_processes = AsyncMock(side_effect=RuntimeError("still running"))
        self.manager._start_model = AsyncMock()
        with self.assertRaisesRegex(RuntimeError, "still running"):
            await self.manager.restart_model("yue2")
        self.manager._start_model.assert_not_awaited()
        self.assertEqual(self.manager.state.models["yue2"].status, ModelStatus.ERROR)

    async def test_reset_does_not_stop_another_active_model(self):
        self.manager.state.active_model = "ace_step"
        self.manager._stop_processes = AsyncMock()
        with self.assertRaisesRegex(ValueError, "another model"):
            await self.manager.restart_model("yue2")
        self.manager._stop_processes.assert_not_awaited()

    async def test_shutdown_during_reset_prevents_restart(self):
        async def stop(_model):
            self.manager._cancel_pending_starts()

        self.manager._stop_processes = stop
        self.manager._start_model = AsyncMock()
        with self.assertRaises(StartCancelled):
            await self.manager.restart_model("yue2")
        self.manager._start_model.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

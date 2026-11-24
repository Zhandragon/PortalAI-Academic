import asyncio
import importlib
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

package = ModuleType("handoff_fixture")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "ha/custom_components/portalai_native")]
sys.modules[package.__name__] = package
h = importlib.import_module("handoff_fixture.control_handoff")
c = importlib.import_module("handoff_fixture.commands")
w = importlib.import_module("handoff_fixture.workflows")


class Receiver:
    def __init__(self):
        self.now = 0
        self.devices = {"device": {"viewer": None, "status": {"native_chat_protocol": 1, "native_ui_protocol": 1}}}
    def connected(self, device):
        return self.devices[device]
    def lease(self, device, viewer):
        state = self.connected(device)
        old = state["viewer"]
        if old and old[0] != viewer and old[1] > self.now:
            raise PermissionError("Another viewer controls this desktop")
        state["viewer"] = (viewer, self.now + 30)
        return state


class HoldTests(unittest.TestCase):
    def setUp(self):
        self.receiver = Receiver()
        clock = patch.object(h, "monotonic", lambda: self.receiver.now)
        clock.start()
        self.addCleanup(clock.stop)
    def test_success_allows_other_controller_after_exactly_two_seconds(self):
        token = h.acquire(self.receiver, "device", "phone")
        h.release(token, True)
        self.receiver.now = 1.99
        with self.assertRaises(PermissionError):
            h.acquire(self.receiver, "device", "voice")
        self.receiver.now = 2
        h.acquire(self.receiver, "device", "voice")
    def test_active_command_rejects_other_controller_even_after_timeout(self):
        token = h.acquire(self.receiver, "device", "phone")
        self.receiver.now = 31
        with self.assertRaises(PermissionError):
            h.acquire(self.receiver, "device", "voice")
        h.release(token, True)
        self.receiver.now += 2
        h.acquire(self.receiver, "device", "voice")
    def test_out_of_order_same_viewer_completions_retain_last_active_hold(self):
        one = h.acquire(self.receiver, "device", "phone")
        two = h.acquire(self.receiver, "device", "phone")
        h.release(two, True)
        with self.assertRaises(PermissionError):
            h.acquire(self.receiver, "device", "voice")
        h.release(one, True)
        self.receiver.now += 2
        h.acquire(self.receiver, "device", "voice")
    def test_unknown_outcome_retains_existing_bounded_fallback(self):
        token = h.acquire(self.receiver, "device", "phone")
        h.release(token, False)
        with self.assertRaises(PermissionError):
            h.acquire(self.receiver, "device", "voice")
        self.receiver.now = 31
        h.acquire(self.receiver, "device", "voice")
    def test_old_completion_does_not_clear_reconnected_device(self):
        token = h.acquire(self.receiver, "device", "phone")
        self.receiver.devices["device"] = {"viewer": ("new-controller", 30)}
        h.release(token, True)
        self.assertEqual(self.receiver.devices["device"]["viewer"][0], "new-controller")
    def test_newer_legacy_desktop_reservation_is_preserved(self):
        token = h.acquire(self.receiver, "device", "phone")
        self.receiver.lease("device", "phone")
        reservation = self.receiver.devices["device"]["viewer"]
        h.release(token, True)
        self.assertIs(self.receiver.devices["device"]["viewer"], reservation)
    def test_active_legacy_desktop_is_not_stolen(self):
        self.receiver.lease("device", "desktop")
        with self.assertRaises(PermissionError):
            h.acquire(self.receiver, "device", "voice")
    def test_duplicate_release_does_not_clear_next_controller(self):
        token = h.acquire(self.receiver, "device", "phone")
        h.release(token, True)
        self.receiver.now += 2
        h.acquire(self.receiver, "device", "voice")
        h.release(token, True)
        self.assertEqual(self.receiver.devices["device"]["viewer"][0], "voice")


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.receiver = Receiver()
        clock = patch.object(h, "monotonic", lambda: self.receiver.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.state = {"view": "v", "epoch": "e", "chat": {"current": "chat", "busy": False}}
        self.hub = SimpleNamespace(read=lambda device: {"snapshot": self.state}, permitted=lambda device: True)
        self.calls = []
        async def dispatch(receiver, device, action, payload):
            self.calls.append(payload)
            return {"accepted": True, "request_id": payload["request_id"], "operation": payload["operation"]}
        self.dispatch = dispatch
        self.chat = c.ChatBridge(self.hub, self.receiver, dispatch)
        self.workflow = w.WorkflowBridge(self.hub, self.receiver, dispatch)
        self.workflow.views["device"] = {"at": time.monotonic(), "binding": {"view": "v", "epoch": "e"}, "ready": True}
    def chat_payload(self, viewer=None):
        return {"request_id": uuid.uuid4().hex, "viewer": viewer or uuid.uuid4().hex, "operation": "send", "binding": {"view": "v", "epoch": "e"}, "conversation": "chat", "text": "test"}
    def workflow_payload(self, viewer=None):
        return {"request_id": uuid.uuid4().hex, "viewer": viewer or uuid.uuid4().hex, "operation": "invoke", "binding": {"view": "v", "epoch": "e"}, "form": "form", "action": "chat_preferences", "values": {}}
    async def test_completed_workflow_then_voice_uses_two_second_cooldown(self):
        await self.workflow.execute("device", "owner", self.workflow_payload())
        with self.assertRaises(PermissionError):
            await self.chat.execute("device", "owner", self.chat_payload())
        self.receiver.now += 2
        await self.chat.execute("device", "owner", self.chat_payload())
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.receiver.devices["device"]["viewer"][1], 4)
    async def test_completed_chat_then_different_phone_uses_two_seconds(self):
        await self.chat.execute("device", "owner", self.chat_payload())
        self.receiver.now += 2
        await self.chat.execute("device", "owner", self.chat_payload())
        self.assertEqual(len(self.calls), 2)
    async def test_replay_returns_receipt_without_new_control_or_execution(self):
        payload = self.chat_payload()
        first = await self.chat.execute("device", "owner", payload)
        self.receiver.now += 2
        self.receiver.lease("device", "other-controller")
        second = await self.chat.execute("device", "owner", payload)
        self.assertEqual(first, second)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.receiver.devices["device"]["viewer"][0], "other-controller")
    async def test_waiter_cancel_does_not_release_inflight_command(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def pending(*args):
            entered.set()
            await finish.wait()
            return await self.dispatch(*args)
        self.chat.dispatch = pending
        request = asyncio.create_task(self.chat.execute("device", "owner", self.chat_payload()))
        await entered.wait()
        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        with self.assertRaises(PermissionError):
            await self.workflow.execute("device", "owner", self.workflow_payload())
        finish.set()
        await asyncio.gather(*(row["task"] for row in self.chat.receipts.values()))
        self.receiver.now += 2
        await self.workflow.execute("device", "owner", self.workflow_payload())
    async def test_chat_and_workflow_share_hold_until_both_finish(self):
        viewer = uuid.uuid4().hex
        entered, finish = asyncio.Event(), asyncio.Event()
        async def pending(*args):
            entered.set()
            await finish.wait()
            return await self.dispatch(*args)
        self.chat.dispatch = pending
        request = asyncio.create_task(self.chat.execute("device", "owner", self.chat_payload(viewer)))
        await entered.wait()
        await self.workflow.execute("device", "owner", self.workflow_payload(viewer))
        with self.assertRaises(PermissionError):
            h.acquire(self.receiver, "device", "voice")
        finish.set()
        await request
        self.receiver.now += 2
        h.acquire(self.receiver, "device", "voice")
    async def test_failed_dispatch_retains_uncertainty_guard(self):
        async def fail(*args):
            raise RuntimeError("Outcome unknown")
        self.chat.dispatch = fail
        with self.assertRaises(RuntimeError):
            await self.chat.execute("device", "owner", self.chat_payload())
        with self.assertRaises(PermissionError):
            await self.workflow.execute("device", "owner", self.workflow_payload())
    async def test_file_chunk_completion_releases_control(self):
        payload = {"request_id": uuid.uuid4().hex, "viewer": uuid.uuid4().hex, "operation": "file_chunk", "binding": {"view": "v", "epoch": "e"}, "transfer": "transfer", "offset": 0, "data": "YQ=="}
        await self.workflow.execute("device", "owner", payload)
        self.receiver.now += 2
        await self.chat.execute("device", "owner", self.chat_payload())
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()

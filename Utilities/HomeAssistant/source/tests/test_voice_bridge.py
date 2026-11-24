import asyncio
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location("voice_bridge", Path(__file__).resolve().parents[1] / "ha/custom_components/portalai_voice/bridge.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def message(identity, role, text, truncated=False):
    return {"id": identity, "role": role, "text": text, "truncated": truncated}


class ReplyTests(unittest.TestCase):
    def setUp(self):
        self.state = {"chat": {"busy": False, "messages": [
            message("old", "assistant", "Old response"),
            message("u", "user", "Turn on test light"),
            message("a", "assistant", "Done") ]}}

    def test_only_new_answer_after_matching_request(self):
        self.assertEqual(m.extract_reply(self.state, {"old"}, "Turn on test light"), "Done")
        self.assertIsNone(m.extract_reply(self.state, {"old", "u", "a"}, "Turn on test light"))

    def test_busy_never_reported_as_finished(self):
        self.state["chat"]["busy"] = True
        self.assertIsNone(m.extract_reply(self.state, {"old"}, "Turn on test light"))

    def test_other_user_message_is_not_returned_as_our_response(self):
        for row in [message("other", "user", "Other task"), message("other", "user", "Turn on test light")]:
            state = copy.deepcopy(self.state)
            state["chat"]["messages"].append(row)
            with self.assertRaises(m.VoiceUnavailable):
                m.extract_reply(state, {"old"}, "Turn on test light")

    def test_truncated_or_thinking_response_not_spoken(self):
        self.state["chat"]["messages"][-1]["truncated"] = True
        with self.assertRaises(m.VoiceUnavailable):
            m.extract_reply(self.state, {"old"}, "Turn on test light")
        self.state["chat"]["messages"][-1] = message("a", "assistant", "<think>private reasoning</think>Done")
        self.assertEqual(m.extract_reply(self.state, {"old"}, "Turn on test light"), "Done")
        self.state["chat"]["messages"][-1]["text"] = "<think>unfinished"
        self.assertIsNone(m.extract_reply(self.state, {"old"}, "Turn on test light"))

    def test_authorized_user_or_explicit_satellite_only(self):
        m.validate_origin("owner", ["voice"], "owner", None)
        m.validate_origin("owner", ["voice"], None, "voice")
        for user, device in [(None, None), (None, "other"), ("other", "voice")]:
            with self.assertRaises(m.VoiceUnavailable):
                m.validate_origin("owner", ["voice"], user, device)


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 0
        self.calls = []
        self.demands = []
        self.owner = SimpleNamespace(id="owner", is_active=True, is_admin=True)
        self.state = {"view": "v", "epoch": "e", "account": {"state": "ready"},
            "chat": {"current": "voice_chat", "busy": False, "messages": [message("old", "assistant", "Earlier")]}}
        async def get_user(identity):
            return self.owner
        async def execute(device, user, payload):
            self.calls.append(payload)
            self.state["chat"]["busy"] = True
            self.state["chat"]["messages"].append(message("u", "user", payload["text"]))
            return {"accepted": True}
        self.execute = execute
        def change(*args):
            self.demands.append(args[-1])
        self.native = {"receiver": SimpleNamespace(hub=SimpleNamespace(read=lambda d: {"snapshot": self.state})),
                       "chat": SimpleNamespace(execute=execute)}
        self.hass = SimpleNamespace(auth=SimpleNamespace(async_get_user=get_user), data={
            "portalai_native": self.native,
            "portalai_projection": {"viewer_demand": SimpleNamespace(change=change),
                                   "receiver": SimpleNamespace(lease=lambda *args: None)}})
        self.config = {"owner_id": "owner", "device_id": "device", "allowed_devices": ["voice"],
                       "conversation_id": "voice_chat", "timeout": 3}
        async def sleep(seconds):
            self.now += seconds
            if self.calls:
                self.state["chat"]["messages"].append(message("a", "assistant", "Done"))
                self.state["chat"]["busy"] = False
        self.sleep = sleep
        self.bridge = m.ProjectionVoiceBridge(self.hass, self.config, sleep=sleep, clock=lambda: self.now)

    async def test_success_uses_existing_chat_without_attachment_or_switch(self):
        self.assertEqual(await self.bridge.send("Test", user_id="owner"), "Done")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["binding"], {"view": "v", "epoch": "e"})
        self.assertNotIn("include_pending_attachments", self.calls[0])
        self.assertEqual(self.demands[-1], "release")

    async def test_busy_refuses_without_send(self):
        self.state["chat"]["busy"] = True
        with self.assertRaises(m.VoiceUnavailable):
            await self.bridge.send("Test", user_id="owner")
        self.assertFalse(self.calls)

    async def test_different_chat_refuses_without_switching(self):
        self.state["chat"]["current"] = "private_chat"
        with self.assertRaises(m.VoiceUnavailable):
            await self.bridge.send("Test", user_id="owner")
        self.assertFalse(self.calls)
        self.assertEqual(self.state["chat"]["current"], "private_chat")

    async def test_revoked_owner_refuses(self):
        self.owner.is_active = False
        with self.assertRaises(m.VoiceUnavailable):
            await self.bridge.send("Test", user_id="owner")
        self.assertFalse(self.calls)

    async def test_account_change_during_request_never_returns_private_answer(self):
        async def sleep(seconds):
            self.now += seconds
            self.state["epoch"] = "different"
        self.bridge.sleep = sleep
        with self.assertRaises(m.VoiceUnavailable):
            await self.bridge.send("Test", user_id="owner")
        self.assertEqual(len(self.calls), 1)

    async def test_timeout_does_not_resend_or_claim_success(self):
        async def sleep(seconds):
            self.now += seconds
        self.bridge.sleep = sleep
        with self.assertRaisesRegex(m.VoiceUnavailable, "may still act"):
            await self.bridge.send("Test", device_id="voice")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.demands[-1], "release")

    async def test_unknown_ack_does_not_retry(self):
        async def fail(*args):
            self.calls.append(args[-1])
            raise RuntimeError("lost acknowledgment")
        self.native["chat"].execute = fail
        with self.assertRaisesRegex(m.VoiceUnavailable, "could not confirm"):
            await self.bridge.send("Test", user_id="owner")
        self.assertEqual(len(self.calls), 1)

    async def test_snapshot_loss_after_send_reports_uncertainty_without_retry(self):
        def read(device):
            if self.calls:
                raise PermissionError("unavailable")
            return {"snapshot": self.state}
        self.native["receiver"].hub.read = read
        with self.assertRaisesRegex(m.VoiceUnavailable, "request may still act"):
            await self.bridge.send("Test", user_id="owner")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.demands[-1], "release")

    async def test_cancellation_releases_demand_and_does_not_replay(self):
        async def cancel(*args):
            self.calls.append(args[-1])
            raise asyncio.CancelledError
        self.native["chat"].execute = cancel
        with self.assertRaises(asyncio.CancelledError):
            await self.bridge.send("Test", user_id="owner")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.demands[-1], "release")

    async def test_concurrent_request_is_rejected(self):
        await self.bridge.lock.acquire()
        try:
            with self.assertRaises(m.VoiceUnavailable):
                await self.bridge.send("Test", user_id="owner")
            self.assertFalse(self.calls)
        finally:
            self.bridge.lock.release()

    async def test_other_controller_refuses_before_submission(self):
        def occupied(*args):
            raise PermissionError("Another viewer controls this desktop")
        self.hass.data["portalai_projection"]["receiver"].lease = occupied
        with self.assertRaisesRegex(m.VoiceUnavailable, "another panel"):
            await self.bridge.send("Test", user_id="owner")
        self.assertFalse(self.calls)
        self.assertEqual(self.demands[-1], "release")

    async def test_admission_wait_renews_demand_without_resending(self):
        admitted = asyncio.Event()
        async def delayed(device, user, payload):
            self.calls.append(payload)
            await admitted.wait()
            self.state["chat"]["messages"] += [message("u", "user", payload["text"]), message("a", "assistant", "Done")]
            return {"accepted": True}
        def change(*args):
            self.demands.append(args[-1])
            if self.demands.count("renew") >= 3:
                admitted.set()
        self.hass.data["portalai_projection"]["viewer_demand"].change = change
        self.native["chat"].execute = delayed
        self.bridge.renew_interval = .001
        self.assertEqual(await self.bridge.send("Test", user_id="owner"), "Done")
        self.assertEqual(len(self.calls), 1)
        self.assertGreaterEqual(self.demands.count("renew"), 3)
        self.assertEqual(self.demands[-1], "release")

    async def test_revocation_during_admission_stops_waiting_and_releases(self):
        cancelled = asyncio.Event()
        async def delayed(device, user, payload):
            self.calls.append(payload)
            self.owner.is_active = False
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        self.native["chat"].execute = delayed
        self.bridge.renew_interval = .001
        with self.assertRaisesRegex(m.VoiceUnavailable, "may still act"):
            await self.bridge.send("Test", user_id="owner")
        self.assertTrue(cancelled.is_set())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.demands[-1], "release")


if __name__ == "__main__":
    unittest.main()

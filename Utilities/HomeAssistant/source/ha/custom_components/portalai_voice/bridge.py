"""A pinned, shared PortalAI chat; never switch accounts/chats or replay sends."""
from __future__ import annotations

import asyncio
import copy
import re
import time
import uuid
from types import SimpleNamespace


class VoiceUnavailable(Exception):
    """Controlled message safe to speak aloud."""


def validate_origin(owner_id, allowed_devices, user_id, device_id):
    # Logged-in requests must come from the delegating owner. A configured
    # physical satellite may have no HA user, but must have its exact device ID.
    if user_id:
        if user_id != owner_id:
            raise VoiceUnavailable("This Home Assistant user is not authorized for PortalAI voice.")
    elif not device_id or device_id not in allowed_devices:
        raise VoiceUnavailable("This voice device is not authorized for PortalAI.")


def checked_snapshot(hub, device, conversation=None, binding=None):
    try:
        snapshot = copy.deepcopy(hub.read(device)["snapshot"])
    except (PermissionError, KeyError):
        raise VoiceUnavailable("PortalAI is offline or locked. Unlock PortalAI and start its projection.") from None
    if snapshot.get("account", {}).get("state") != "ready":
        raise VoiceUnavailable("PortalAI is locked.")
    if conversation and snapshot["chat"]["current"] != conversation:
        raise VoiceUnavailable("Select the configured voice conversation in PortalAI before speaking.")
    if binding and any(snapshot.get(k) != v for k, v in binding.items()):
        raise VoiceUnavailable("The PortalAI account changed. Check the chat before repeating the request.")
    return snapshot


def extract_reply(snapshot, previous_ids, sent_text):
    """Only a new final assistant message after our exact acknowledged user row."""
    rows = snapshot["chat"]["messages"]
    new = [row for row in rows if row["id"] not in previous_ids]
    users = [i for i, row in enumerate(new) if row["role"] == "user"]
    if not users:
        return None
    if len(users) != 1 or new[users[0]]["text"] != sent_text or new[users[0]].get("truncated"):
        raise VoiceUnavailable("The shared chat changed. Check PortalAI before repeating the request.")
    if snapshot["chat"]["busy"]:
        return None
    replies = [row for row in new[users[0]+1:] if row["role"] == "assistant" and row["text"].strip()]
    if not replies:
        return None
    row = replies[-1]
    if row.get("truncated"):
        raise VoiceUnavailable("PortalAI finished with a long response. Read the full answer in its chat.")
    # Older hosts can expose think markup in plain message content. Never speak it.
    text = re.sub(r"<think>.*?</think>", "", row["text"], flags=re.S).strip()
    if "<think>" in text or not text:
        return None
    if len(text) > 4000:
        raise VoiceUnavailable("PortalAI finished with a long response. Read the answer in its chat.")
    return text


class ProjectionVoiceBridge:
    """Adds only conversation routing; PortalAI retains all tool/Stop guards."""

    def __init__(self, hass, config, *, sleep=asyncio.sleep, clock=time.monotonic, renew_interval=4):
        self.hass = hass
        self.config = config
        self.sleep = sleep
        self.clock = clock
        self.renew_interval = renew_interval
        self.lock = asyncio.Lock()

    async def dispatch_with_demand(self, execute, renew):
        """Keep presence alive during admission; never repeat an execution."""
        task = asyncio.create_task(execute)
        try:
            while not task.done():
                done, _ = await asyncio.wait({task}, timeout=self.renew_interval)
                if not done:
                    await self.owner()
                    renew()
            return await task
        finally:
            if not task.done():
                # ChatBridge shields its effect receipt. Cancelling our waiter
                # cannot prove that an already queued action did not execute.
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def owner(self):
        user = await self.hass.auth.async_get_user(self.config["owner_id"])
        if user is None or not user.is_active or not user.is_admin:
            raise VoiceUnavailable("The Home Assistant owner approval for PortalAI is no longer active.")
        return user

    async def observe(self, conversation=None):
        owner = await self.owner()
        native = self.hass.data.get("portalai_native", {})
        projection = self.hass.data.get("portalai_projection", {})
        if "receiver" not in native or "viewer_demand" not in projection:
            raise VoiceUnavailable("The PortalAI projection integration is not ready.")
        hub = native["receiver"].hub
        book = projection["viewer_demand"]
        viewer = uuid.uuid4().hex
        connection = SimpleNamespace(user=owner)
        device = self.config["device_id"]
        try:
            book.change(device, connection, viewer, "native", "acquire")
            for _ in range(24):
                await self.owner()
                try:
                    return checked_snapshot(hub, device, conversation)
                except VoiceUnavailable:
                    await self.sleep(.25)
            return checked_snapshot(hub, device, conversation)
        finally:
            book.change(device, connection, viewer, "native", "release")

    async def send(self, text, *, user_id=None, device_id=None):
        validate_origin(self.config["owner_id"], self.config["allowed_devices"], user_id, device_id)
        if not isinstance(text, str) or not text.strip() or len(text) > 6000:
            raise VoiceUnavailable("Please use a shorter voice request.")
        if self.lock.locked():
            raise VoiceUnavailable("PortalAI is answering another voice request. Please wait.")
        async with self.lock:
            return await self._send(text)

    async def _send(self, text):
        owner = await self.owner()
        device = self.config["device_id"]
        conversation = self.config["conversation_id"]
        native = self.hass.data.get("portalai_native", {})
        projection = self.hass.data.get("portalai_projection", {})
        if "receiver" not in native or "viewer_demand" not in projection:
            raise VoiceUnavailable("The PortalAI projection integration is not ready.")
        hub = native["receiver"].hub
        book = projection["viewer_demand"]
        viewer = uuid.uuid4().hex
        connection = SimpleNamespace(user=owner)
        submitted = False
        try:
            book.change(device, connection, viewer, "native", "acquire")
            # Wake native snapshots when no browser is watching the projection.
            snapshot = None
            for _ in range(24):
                await self.owner()
                try:
                    snapshot = checked_snapshot(hub, device, conversation)
                    break
                except VoiceUnavailable:
                    await self.sleep(.25)
            if snapshot is None:
                snapshot = checked_snapshot(hub, device, conversation)
            if snapshot["chat"]["busy"]:
                raise VoiceUnavailable("PortalAI is busy. Wait for its current task or stop it in PortalAI.")
            binding = {key: snapshot[key] for key in ("view", "epoch")}
            previous_ids = {row["id"] for row in snapshot["chat"]["messages"]}
            # No attachment opt-in: unrelated unsent files must never be submitted.
            payload = {"request_id": uuid.uuid4().hex, "viewer": viewer,
                       "operation": "send", "binding": binding,
                       "conversation": conversation, "text": text}
            # Reserve the same existing controller lease ChatBridge checks.
            # A refusal here happens before anything is submitted or queued.
            # Do not steal or bypass another browser/controller's 30s lease.
            try:
                projection["receiver"].lease(device, owner.id + ":" + viewer)
            except PermissionError:
                raise VoiceUnavailable("PortalAI is being controlled in another panel. Finish that action, then try again.") from None
            renew = lambda: book.change(device, connection, viewer, "native", "renew")
            renew()
            submitted = True
            await self.dispatch_with_demand(native["chat"].execute(device, owner.id, payload), renew)
            deadline = self.clock() + self.config.get("timeout", 600)
            renewed = self.clock()
            while self.clock() < deadline:
                await self.owner()
                if self.clock() - renewed >= 4:
                    book.change(device, connection, viewer, "native", "renew")
                    renewed = self.clock()
                current = checked_snapshot(hub, device, conversation, binding)
                reply = extract_reply(current, previous_ids, text)
                if reply is not None:
                    return reply
                await self.sleep(.5)
            raise VoiceUnavailable("PortalAI has not finished. Check its chat before repeating the request; it may still act.")
        except asyncio.CancelledError:
            # Cancellation/timeout is not evidence that a tool never acted. Do not
            # resend, change chats, force-stop the host, or fabricate success.
            raise
        except VoiceUnavailable:
            if submitted:
                raise VoiceUnavailable("PortalAI could not confirm completion. The request may still act. Check its chat and device state before repeating it.") from None
            raise
        except Exception:
            if submitted:
                raise VoiceUnavailable("PortalAI could not confirm this request. Check its chat and device state before repeating it.") from None
            raise VoiceUnavailable("PortalAI voice is unavailable. Check the projection connection.") from None
        finally:
            book.change(device, connection, viewer, "native", "release")

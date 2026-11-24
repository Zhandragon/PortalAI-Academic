"""Explicit owner delegation to selected physical voice devices."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import device_registry as dr, selector
from .bridge import ProjectionVoiceBridge, VoiceUnavailable

DOMAIN = "portalai_voice"


class PortalAIVoiceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        # HA's admin-only config-flow HTTP API does not put user_id in the
        # flow context. Delegate explicitly to the single active HA owner.
        owners = [user for user in await self.hass.auth.async_get_users()
                  if user.is_owner and user.is_admin and user.is_active]
        if len(owners) != 1:
            return self.async_abort(reason="owner_required")
        owner_id = owners[0].id
        projection = self.hass.data.get("portalai_projection", {})
        receiver = projection.get("receiver")
        if receiver is None or not receiver.approved:
            return self.async_abort(reason="projection_required")
        errors = {}
        if user_input is not None:
            try:
                device = user_input["device_id"]
                if device not in receiver.approved:
                    raise VoiceUnavailable("projection_unavailable")
                allowed = user_input.get("allowed_devices", [])
                registry = dr.async_get(self.hass)
                if any(registry.async_get(device_id) is None for device_id in allowed):
                    raise VoiceUnavailable("projection_unavailable")
                config = {"owner_id": owner_id, "device_id": device,
                          "allowed_devices": allowed, "timeout": 600}
                snapshot = await ProjectionVoiceBridge(self.hass, config).observe()
                chat = snapshot["chat"]
                if not chat["current"] or chat["busy"]:
                    raise VoiceUnavailable("projection_unavailable")
                config["conversation_id"] = chat["current"]
                self._prepared = config
                self._name = user_input["name"].strip() or "PortalAI"
                self._chat_title = next((row["title"] for row in chat["conversations"]
                                         if row["id"] == chat["current"]), "Selected chat")
                self._account = snapshot["account"]["displayName"]
                await self.async_set_unique_id(device)
                self._abort_if_unique_id_configured()
                return await self.async_step_confirm()
            except (VoiceUnavailable, KeyError, PermissionError):
                errors["base"] = "projection_unavailable"
        return self.async_show_form(step_id="user", errors=errors, data_schema=vol.Schema({
            vol.Required("name", default="PortalAI"): str,
            vol.Required("device_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=list(receiver.approved), mode="dropdown")),
            vol.Optional("allowed_devices", default=[]): selector.DeviceSelector(
                selector.DeviceSelectorConfig(multiple=True)),
        }))

    async def async_step_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            if not user_input.get("approve"):
                errors["base"] = "approval_required"
            else:
                try:
                    await ProjectionVoiceBridge(self.hass, self._prepared).observe(
                        self._prepared["conversation_id"])
                    return self.async_create_entry(title=self._name, data=self._prepared)
                except VoiceUnavailable:
                    errors["base"] = "projection_unavailable"
        return self.async_show_form(step_id="confirm", errors=errors,
            description_placeholders={"chat": self._chat_title, "account": self._account},
            data_schema=vol.Schema({vol.Required("approve", default=False): bool}))

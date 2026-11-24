"""Opt-in Home Assistant conversation adapter for an existing projection."""
from homeassistant.const import Platform
from .bridge import ProjectionVoiceBridge

DOMAIN = "portalai_voice"
PLATFORMS = [Platform.CONVERSATION]


async def async_setup_entry(hass, entry):
    entry.runtime_data = ProjectionVoiceBridge(hass, dict(entry.data))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

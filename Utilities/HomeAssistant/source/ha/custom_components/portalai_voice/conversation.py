"""Voice sentences run through PortalAI's actual chat/tool harness."""
from homeassistant.components import conversation
from homeassistant.helpers import intent
from .bridge import VoiceUnavailable


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([PortalAIVoiceEntity(entry)])


class PortalAIVoiceEntity(conversation.ConversationEntity):
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL
    _attr_supports_streaming = False

    def __init__(self, entry):
        self.entry = entry
        self._attr_name = entry.title
        self._attr_unique_id = entry.entry_id

    @property
    def supported_languages(self):
        return "*"

    async def async_process(self, user_input):
        response = intent.IntentResponse(language=user_input.language)
        try:
            text = await self.entry.runtime_data.send(
                user_input.text, user_id=user_input.context.user_id,
                device_id=user_input.device_id)
            response.async_set_speech(text)
        except VoiceUnavailable as exc:
            response.async_set_error(intent.IntentResponseErrorCode.FAILED_TO_HANDLE, str(exc))
        return conversation.ConversationResult(response=response,
                                               conversation_id=user_input.conversation_id)

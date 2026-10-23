"""A busy follow-up from another sender keeps its own turn instead of joining the pending one.

With ``group_sessions_per_user: false`` everyone in a group shares one session key, and the next
turn is attributed to the pending event's sender. The busy-text debounce already keeps senders
apart (``_can_merge_text_debounce_events``); ``_hm_merge_pending_for_source`` did not, so text
sent while the agent was still being set up, and photo follow-ups on the priority path, were
appended to another person's pending message.
"""

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.platforms.event import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.session import SessionSource


class _Adapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(enabled=True, token="test", extra={"group_sessions_per_user": False}),
                         Platform.TELEGRAM)

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        return True

    async def disconnect(self) -> None:
        self._mark_disconnected()

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        return SendResult(success=True, message_id="m1")

    async def get_chat_info(self, chat_id):
        return {"id": chat_id, "type": "group"}


def _event(user_id: str, text: str, message_type=MessageType.TEXT) -> MessageEvent:
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="-100777", chat_type="group",
                           user_id=user_id, user_name=f"user{user_id}")
    event = MessageEvent(text=text, message_type=message_type, source=source, message_id=f"{user_id}-{text}")
    if message_type == MessageType.PHOTO:
        event.media_urls = [f"/tmp/{user_id}-{text}.jpg"]
        event.media_types = ["image/jpeg"]
    return event


def _runner_with_pending(first: MessageEvent):
    adapter = _Adapter()
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="t")})
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._delivery_adapter_for = lambda source: adapter
    key = adapter._event_session_key(first)
    assert key == adapter._event_session_key(_event("2", "x")), "fixture: both senders share one session"
    adapter._pending_messages[key] = first
    return runner, adapter, key


def _queued(runner, key) -> list[MessageEvent]:
    state = runner._peek_session_state(key)
    return list(state.conversation.queued_events) if state else []


def test_text_from_another_sender_during_agent_setup_gets_its_own_turn():
    runner, adapter, key = _runner_with_pending(_event("1", "owner text"))
    other = _event("2", "other text")
    runner._hm_merge_pending_for_source(other.source, key, other, merge_text=True)
    pending = adapter._pending_messages[key]
    assert (pending.source.user_id, pending.text) == ("1", "owner text")
    assert _queued(runner, key) == [other]


def test_text_from_the_same_sender_during_agent_setup_still_appends():
    runner, adapter, key = _runner_with_pending(_event("1", "first"))
    second = _event("1", "second")
    runner._hm_merge_pending_for_source(second.source, key, second, merge_text=True)
    assert adapter._pending_messages[key].text == "first\nsecond"
    assert _queued(runner, key) == []


def test_photo_from_another_sender_is_not_merged_into_the_pending_burst():
    runner, adapter, key = _runner_with_pending(_event("1", "owner photo", MessageType.PHOTO))
    other = _event("2", "other caption", MessageType.PHOTO)
    runner._hm_merge_pending_for_source(other.source, key, other)
    pending = adapter._pending_messages[key]
    assert pending.source.user_id == "1"
    assert "other caption" not in (pending.text or "")
    assert pending.media_urls == ["/tmp/1-owner photo.jpg"]
    assert _queued(runner, key) == [other]


def test_photo_burst_from_the_same_sender_still_merges():
    runner, adapter, key = _runner_with_pending(_event("1", "first", MessageType.PHOTO))
    second = _event("1", "second", MessageType.PHOTO)
    runner._hm_merge_pending_for_source(second.source, key, second)
    assert adapter._pending_messages[key].media_urls == ["/tmp/1-first.jpg", "/tmp/1-second.jpg"]
    assert _queued(runner, key) == []

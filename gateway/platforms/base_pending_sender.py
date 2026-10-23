"""Sender identity of pending events (split from :mod:`gateway.platforms.base`).

A shared group session puts several people on one session key, and the next turn is attributed to
the pending event's sender, so a busy follow-up may join a pending event only when it came from the
same sender."""
from gateway.platforms.event import MessageEvent


def _pending_sender(event: MessageEvent) -> tuple[str, ...] | None:
    """Who sent *event*: platform + user id, or the DM chat when the platform gives no user id."""
    source = getattr(event, "source", None)
    if source is None:
        return None
    platform_value = getattr(getattr(source, "platform", None), "value", getattr(source, "platform", None))
    platform = str(platform_value or "").lower()
    sender = getattr(source, "user_id_alt", None) or getattr(source, "user_id", None)
    if sender:
        return (platform, str(sender))
    if getattr(source, "chat_type", None) in {"dm", "private"} and getattr(source, "chat_id", None):
        return (platform, "dm", str(source.chat_id))
    return None


def same_pending_sender(existing: MessageEvent, event: MessageEvent) -> bool:
    """True when *event* came from the sender of *existing*, so it may join that pending turn."""
    existing_sender = _pending_sender(existing)
    return existing_sender is not None and existing_sender == _pending_sender(event)

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import re
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telethon.tl.types import InputPeerChannel, PeerChannel, PeerChat

MAX_HISTORY_MESSAGES = 1000
HISTORY_PREVIEW_LIMIT = 5


def _kyiv_timezone():
    try:
        return ZoneInfo("Europe/Kyiv")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=3), "Europe/Kyiv")


HISTORY_TIMEZONE = _kyiv_timezone()


@dataclass
class HistoryMatch:
    message_id: int
    date: datetime
    sender_name: str
    text: str
    matched_keywords: list[str]
    url: str
    saved: bool


@dataclass
class HistoryScanResult:
    scanned: int
    matched: int
    saved: int
    keywords: list[str]
    limit_reached: bool
    preview: list[HistoryMatch]
    matches: list[HistoryMatch] = field(default_factory=list)


def _default_now() -> datetime:
    return datetime.now(HISTORY_TIMEZONE)


def _with_timezone(value: datetime, reference: datetime) -> datetime:
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=reference.tzinfo)


def _parse_datetime_part(value: str, now: datetime, is_end: bool) -> datetime:
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%Y-%m-%d" and is_end:
                parsed = parsed.replace(hour=23, minute=59, second=59)
            return _with_timezone(parsed, now)
        except ValueError:
            pass
    raise ValueError("Неверный формат интервала.")


def parse_history_interval(raw: str, now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    current = now or _default_now()
    text = raw.strip().lower()
    if not text:
        raise ValueError("Введите интервал.")

    relative = re.fullmatch(r"(\d+)\s*(m|min|мин|минут|h|ч|час|часов|d|д|дн|дней)", text)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        if amount <= 0:
            raise ValueError("Интервал должен быть больше нуля.")
        if unit in {"m", "min", "мин", "минут"}:
            delta = timedelta(minutes=amount)
        elif unit in {"h", "ч", "час", "часов"}:
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(days=amount)
        return current - delta, current

    parts = re.split(r"\s+[—–-]\s+", raw.strip(), maxsplit=1)
    if len(parts) != 2:
        raise ValueError("Неверный формат интервала.")

    start = _parse_datetime_part(parts[0], current, is_end=False)
    end = _parse_datetime_part(parts[1], current, is_end=True)
    if start >= end:
        raise ValueError("Начало интервала должно быть раньше конца.")
    return start, end


def find_matches(text: str, keywords: list[str]) -> list[str]:
    lower = text.lower()
    return [keyword for keyword in keywords if keyword and keyword.lower() in lower]


def message_url(chat_tg_id: int, username: Optional[str], message_id: int) -> str:
    if username:
        return f"https://t.me/{username}/{message_id}"
    clean_id = str(chat_tg_id)
    if clean_id.startswith("-100"):
        clean_id = clean_id[4:]
    elif clean_id.startswith("-"):
        clean_id = clean_id[1:]
    return f"https://t.me/c/{clean_id}/{message_id}"


def history_entity_ref(chat: dict) -> str | InputPeerChannel | PeerChannel | PeerChat:
    username = chat.get("username")
    if username:
        return username
    tg_id = int(chat["tg_id"])
    clean_id = _clean_peer_id(tg_id)
    if chat.get("chat_type") in {"channel", "supergroup"}:
        if chat.get("access_hash"):
            return InputPeerChannel(clean_id, int(chat["access_hash"]))
        return PeerChannel(clean_id)
    if chat.get("chat_type") == "group":
        return PeerChat(clean_id)
    raise ValueError(f"Unknown chat_type {chat.get('chat_type')!r} for tg_id {tg_id}")


def _clean_peer_id(tg_id: int) -> int:
    value = str(tg_id)
    if value.startswith("-100"):
        return int(value[4:])
    if value.startswith("-"):
        return int(value[1:])
    return tg_id


async def _sender_name(message) -> str:
    try:
        sender = await message.get_sender()
    except Exception:
        sender = getattr(message, "sender", None)
    if sender is None:
        return "Unknown"
    first = getattr(sender, "first_name", "") or ""
    last = getattr(sender, "last_name", "") or ""
    username = getattr(sender, "username", None)
    if username:
        return f"@{username}"
    return f"{first} {last}".strip() or str(getattr(sender, "id", "Unknown"))


def _message_date(value: datetime, reference: datetime) -> datetime:
    return _with_timezone(value, reference)


class HistoryScanner:
    def __init__(self, client, repo):
        self.client = client
        self.repo = repo

    async def scan(
        self,
        user_tg_id: int,
        topic_id: int,
        chat: dict,
        start: datetime,
        end: datetime,
        max_messages: int = MAX_HISTORY_MESSAGES,
    ) -> HistoryScanResult:
        keywords = await self.repo.get_active_keywords_for_topic(user_tg_id, topic_id)
        scanned = 0
        matched = 0
        saved = 0
        preview: list[HistoryMatch] = []
        matches: list[HistoryMatch] = []
        if not keywords:
            return HistoryScanResult(0, 0, 0, [], False, [])

        entity_ref = history_entity_ref(chat)
        async for message in self.client.iter_messages(
            entity_ref, offset_date=end, limit=max_messages
        ):
            if not getattr(message, "date", None):
                continue
            date = _message_date(message.date, end)
            if date < start:
                break
            if date > end:
                continue
            scanned += 1
            text = message.message or ""
            if not text.strip():
                continue
            message_matches = find_matches(text, keywords)
            if not message_matches:
                continue

            matched += 1
            sender_name = await _sender_name(message)
            url = message_url(chat["tg_id"], chat.get("username"), message.id)
            was_saved = await self.repo.save_feed_item(
                user_tg_id=user_tg_id,
                chat_tg_id=chat["tg_id"],
                chat_title=chat["title"],
                message_id=message.id,
                message_text=text,
                matched_keywords=message_matches,
                sender_name=sender_name,
                message_url=url,
            )
            if was_saved:
                saved += 1
            match = HistoryMatch(
                message_id=message.id,
                date=date,
                sender_name=sender_name,
                text=text,
                matched_keywords=message_matches,
                url=url,
                saved=was_saved,
            )
            matches.append(match)
            if len(preview) < HISTORY_PREVIEW_LIMIT:
                preview.append(match)

        return HistoryScanResult(
            scanned=scanned,
            matched=matched,
            saved=saved,
            keywords=keywords,
            limit_reached=scanned >= max_messages,
            preview=preview,
            matches=matches,
        )

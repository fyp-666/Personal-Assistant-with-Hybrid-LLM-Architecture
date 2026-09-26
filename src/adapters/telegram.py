"""Receive Telegram text requests from one explicitly bound private chat."""

import json
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from adapters.gmail import GmailError
from adapters.messaging import MessageContentError
from app.assistant import ToolCheckpointError
from app.conversation import ConversationError, ConversationVersionError
from core.execution import ProviderError
from core.routing import Privacy, RequestContext, Source
from features.calendar_actions import CalendarError


class TelegramError(RuntimeError):
    """A configuration or polling failure without credential-bearing details."""


@dataclass(frozen=True)
class TelegramConfig:
    token: str = field(repr=False)
    user_id: int
    chat_id: int


def load_telegram_config(profile: Path) -> TelegramConfig:
    keys = {"TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS", "TELEGRAM_HOME_CHANNEL"}
    values = {}
    try:
        for line in (profile / ".env").read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() in keys:
                parts = shlex.split(value, comments=True)
                if len(parts) != 1:
                    raise ValueError("Expected one value")
                values[key.strip()] = parts[0]
        token = values["TELEGRAM_BOT_TOKEN"]
        user = values["TELEGRAM_ALLOWED_USERS"]
        chat = values["TELEGRAM_HOME_CHANNEL"]
        if not token or not user.isdecimal() or user != chat or int(user) <= 0:
            raise ValueError("Expected one bound private chat")
        return TelegramConfig(token, int(user), int(chat))
    except (OSError, ValueError, KeyError):
        raise TelegramError(
            "Check the Local profile Telegram configuration: a token and matching numeric user/private-chat IDs are required."
        ) from None


def _request(config: TelegramConfig, method: str, data: dict) -> object:
    request = Request(
        f"https://api.telegram.org/bot{config.token}/{method}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=35) as response:
            payload = json.load(response)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ValueError("Invalid Telegram response")
        return payload["result"]
    except (OSError, URLError, ValueError, KeyError):
        raise TelegramError(
            "Telegram request failed. Check the network, token, and other active receivers or webhooks."
        ) from None


def check_polling_available(config: TelegramConfig) -> None:
    info = _request(config, "getWebhookInfo", {})
    if not isinstance(info, dict) or info.get("url"):
        raise TelegramError(
            "A webhook is configured or the bot state is invalid. The receiver was not started; existing webhooks are not removed automatically."
        )


def get_updates(
    config: TelegramConfig, *, offset: int, timeout: int = 20
) -> list[dict]:
    updates = _request(
        config,
        "getUpdates",
        {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": ["message"],
        },
    )
    if not isinstance(updates, list) or any(
        not isinstance(update, dict) or type(update.get("update_id")) is not int
        for update in updates
    ):
        raise TelegramError("Telegram returned an invalid message list.")
    return updates


def reply_to_update(
    update: dict,
    config: TelegramConfig,
    *,
    handle: Callable[[str, RequestContext], str],
    send: Callable[[str], None],
    reset: Callable[[], None] | None = None,
) -> bool:
    """Authorize before inference; ignore other users and never append quoted text."""
    message = update.get("message")
    if not isinstance(message, dict):
        return False
    sender = message.get("from", {})
    chat = message.get("chat", {})
    if (
        sender.get("id") != config.user_id
        or sender.get("is_bot")
        or chat.get("id") != config.chat_id
        or chat.get("type") != "private"
    ):
        return False
    text = message.get("text", "").strip()
    parts = text.split(maxsplit=1)
    command = parts[0].split("@", 1)[0] if parts else ""
    rest = parts[1] if len(parts) > 1 else ""
    if any(
        key in message
        for key in ("forward_origin", "forward_from", "forward_sender_name")
    ):
        answer = "Only text requests sent directly by you are supported. Forwarded messages are not supported."
    elif not text:
        answer = "Only text requests are supported. Images, voice messages, and attachments are not supported."
    elif command == "/new" and reset is not None:
        reset()
        answer = "Started a new conversation. Recent exchanges and email/calendar snapshots were cleared, and the active model was reset to GPT. Saved preferences and calendar events are unchanged."
    elif command in {"/start", "/help"}:
        answer = (
            "You can chat, search email by date or subject (up to 10 messages), query/create/update/cancel events in the bound Google calendar, or update long-term preferences. Recent exchanges and retrieved email/calendar data provide context. Use /new to start a new conversation while keeping preferences. "
            "New conversations start with GPT. Difficult requests may be delegated to NVIDIA, which remains active for follow-ups. Provider failures switch to an available permitted fallback. Use /new to reset the active model to GPT. Use /private followed by your question for local-only processing, which remains active until /new."
        )
    elif text.startswith("/") and command != "/private":
        answer = "Unknown command. Send a text question, or use /private followed by your question."
    elif command == "/private" and not rest.strip():
        answer = "After /private, enter the question to process locally."
    else:
        private = command == "/private"
        request = rest.strip() if command == "/private" else text
        context = RequestContext(
            privacy=Privacy.SENSITIVE if private else Privacy.PUBLIC,
            source=Source.USER_INPUT,
        )
        try:
            answer = handle(request, context)
        except ToolCheckpointError as error:
            # Deliver the confirmed receipt, then preserve the storage failure so
            # the receiver stops before another request reloads stale state.
            notice = (
                "Conversation saving failed. Completed operations are not undone; do not submit them again. Privacy state may not have been saved, so the receiver will stop. "
                "Fix local storage, restart, and query again to verify. "
                "Use /private explicitly when continuing a private topic."
            )
            try:
                send(error.reply.text + "\n\n" + notice)
            except MessageContentError:
                send(
                    "Tool results were obtained, but the receipt failed the text-only delivery check. "
                    "Completed operations are not undone; do not submit them again.\n\n"
                    + notice
                )
            raise
        except ConversationVersionError:
            # Loading failed before inference or tools. Keep polling so /new can reset it.
            answer = (
                "Unsupported conversation format version. This request was not executed. "
                "Send /new to start a new conversation. Convert the archive separately first if you need to retain old context."
            )
        except ConversationError:
            # Continuing could reload an old public state after a private save failed.
            # This fixed notice has no content directives; uncertain sends propagate.
            send(
                "Conversation storage failed. Operations may have completed and preference edits may have been saved. "
                "Conversation privacy state may not have been saved, so the receiver will stop. Fix local storage before restarting; use /private explicitly for private topics."
            )
            raise
        except (ProviderError, GmailError, CalendarError):
            answer = "This request failed because the model, mailbox, or local conversation was unavailable. Try again later."
    try:
        send(answer)
    except MessageContentError:
        # The original text never reached Hermes. A fixed notice is safe to send;
        # uncertain transport failures still propagate without a retry.
        send(
            "The reply failed the text-only delivery check and was not sent. Rephrase your request; the receiver will keep running."
        )
    return True

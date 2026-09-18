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
from app.conversation import ConversationError
from core.execution import ProviderError
from core.routing import Privacy, RequestContext, Source


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
            "请检查 Local profile 的 Telegram 配置：需要 Token 和同一个数字用户/私聊 ID。"
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
            "Telegram 请求失败；请检查网络、Token，以及是否有其他接收器或 webhook 正在运行。"
        ) from None


def check_polling_available(config: TelegramConfig) -> None:
    info = _request(config, "getWebhookInfo", {})
    if not isinstance(info, dict) or info.get("url"):
        raise TelegramError(
            "机器人已配置 webhook 或状态异常，接收器未启动；不会自动移除已有 webhook。"
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
        raise TelegramError("Telegram 返回了无效的消息列表。")
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
        answer = "目前只处理你直接发送的文字请求，暂不处理转发消息。"
    elif not text:
        answer = "目前只支持文字请求，暂不处理图片、语音或附件。"
    elif command == "/new" and reset is not None:
        reset()
        answer = "已开始新会话，近期对话和邮件快照已清空，长期偏好保留。"
    elif command in {"/start", "/help"}:
        answer = (
            "可以聊天、发送‘总结最新一封邮件’，或明确要求记住、修改、忘记长期偏好。会保留近期对话；/new 开始新会话，长期偏好保留。"
            "普通文字会交给 GPT 识别任务；私人内容请用 /private 你的问题，全程使用 Gemma。含私人资料的会话会继续留在本地，直到 /new。"
        )
    elif text.startswith("/") and command != "/private":
        answer = "未知命令。可直接发送文字问题，或用 /private 你的问题。"
    elif command == "/private" and not rest.strip():
        answer = "请在 /private 后面填写需要本地处理的问题。"
    else:
        private = command == "/private" or any(
            key in message for key in ("reply_to_message", "external_reply", "quote")
        )
        request = rest.strip() if command == "/private" else text
        context = RequestContext(
            privacy=Privacy.SENSITIVE if private else Privacy.PUBLIC,
            source=Source.USER_INPUT,
        )
        try:
            answer = handle(request, context)
        except ConversationError:
            # Continuing could reload an old public state after a private save failed.
            # This fixed notice has no content directives; uncertain sends propagate.
            send(
                "近期对话文件读写失败。本轮业务可能已执行，长期记忆修改也可能已保存；"
                "会话隐私状态可能未保存，接收器将停止。请修复本地存储后重启；继续私人话题时请明确使用 /private。"
            )
            raise
        except (ProviderError, GmailError):
            answer = (
                "本次请求处理失败，模型、邮箱或本地会话暂不可用。请稍后重新发送请求。"
            )
    try:
        send(answer)
    except MessageContentError:
        # The original text never reached Hermes. A fixed notice is safe to send;
        # uncertain transport failures still propagate without a retry.
        send(
            "本轮回复内容无法通过纯文本发送检查，已阻止发送。请换一种方式提问；接收器会继续运行。"
        )
    return True

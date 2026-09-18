"""A bounded local conversation, separate from long-term USER.md preferences."""

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.routing import Complexity
from features.email import Email

MAX_TURNS = 6
HISTORY_CHARS = 12000
EMAIL_CHARS = 16000


class ConversationError(RuntimeError):
    """Conversation state could not be safely loaded or saved."""


@contextmanager
def conversation_session(path: Path) -> Iterator["Conversation"]:
    """Persist successful turns and privacy restrictions even when a turn fails."""
    state = load_conversation(path)
    was_private = state.private
    try:
        yield state
    except BaseException:
        # Failed requests add no turn, but must not reopen the cloud boundary.
        if state.private and not was_private:
            save_conversation(path, state)
        raise
    else:
        save_conversation(path, state)


@dataclass
class Conversation:
    turns: list[dict[str, str]] = field(default_factory=list)
    private: bool = False
    email: Email | None = None
    complexity: Complexity = Complexity.NORMAL

    def record(
        self,
        message: str,
        answer: str,
        *,
        private: bool,
        complexity: Complexity,
        email: Email | None = None,
    ) -> None:
        self.private = self.private or private or email is not None
        self.complexity = complexity
        if email is not None:
            self.email = Email(
                email.sender[:1000],
                email.subject[:1000],
                email.body[:EMAIL_CHARS]
                + ("\n[后续邮件正文未保留]" if len(email.body) > EMAIL_CHARS else ""),
            )
        self.turns.append(
            {
                "user": message[: HISTORY_CHARS // 2],
                "assistant": answer[: HISTORY_CHARS // 2],
            }
        )
        self.turns = self.turns[-MAX_TURNS:]
        while (
            len(self.turns) > 1
            and sum(len(t["user"]) + len(t["assistant"]) for t in self.turns)
            > HISTORY_CHARS
        ):
            self.turns.pop(0)

    def payload(self, *, include_email: bool) -> dict:
        data = {"history": self.turns}
        if include_email and self.email is not None:
            data["current_email"] = asdict(self.email)
        return data


def load_conversation(path: Path) -> Conversation:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            set(data) != {"turns", "private", "email", "complexity"}
            or type(data["private"]) is not bool
        ):
            raise ValueError("Invalid conversation")
        turns = data["turns"]
        if (
            not isinstance(turns, list)
            or len(turns) > MAX_TURNS
            or any(
                not isinstance(turn, dict)
                or set(turn) != {"user", "assistant"}
                or any(not isinstance(value, str) for value in turn.values())
                for turn in turns
            )
        ):
            raise ValueError("Invalid turns")
        if sum(len(t["user"]) + len(t["assistant"]) for t in turns) > HISTORY_CHARS:
            raise ValueError("History exceeds budget")
        raw_email = data["email"]
        if raw_email is not None and (
            not isinstance(raw_email, dict)
            or set(raw_email) != {"sender", "subject", "body"}
            or any(not isinstance(value, str) for value in raw_email.values())
            or len(raw_email["body"]) > EMAIL_CHARS + 100
            or len(raw_email["sender"]) > 1000
            or len(raw_email["subject"]) > 1000
        ):
            raise ValueError("Invalid email snapshot")
        email = Email(**raw_email) if raw_email is not None else None
        return Conversation(
            turns,
            data["private"] or email is not None,
            email,
            Complexity(data["complexity"]),
        )
    except FileNotFoundError:
        return Conversation()
    except (OSError, ValueError, TypeError, KeyError):
        raise ConversationError(
            "会话文件无法读取；请检查本地文件，或开始新会话。"
        ) from None


def save_conversation(path: Path, conversation: Conversation) -> None:
    temporary = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        data = {
            "turns": conversation.turns,
            "private": conversation.private,
            "email": asdict(conversation.email) if conversation.email else None,
            "complexity": conversation.complexity.value,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(data, stream, ensure_ascii=False)
        os.replace(temporary, path)
    except OSError:
        raise ConversationError("会话文件保存失败，本轮结果未保存。") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

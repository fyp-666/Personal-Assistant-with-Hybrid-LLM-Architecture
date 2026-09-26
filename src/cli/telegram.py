"""Receive bound Telegram private messages in the WSL foreground; Ctrl+C stops the receiver."""

import argparse
import fcntl
import os
from pathlib import Path

from adapters.gmail import query_gmail
from adapters.messaging import DeliveryError, send_message
from adapters.telegram import (
    TelegramError,
    check_polling_available,
    get_updates,
    load_telegram_config,
    reply_to_update,
)
from app.assistant import ToolCheckpointError, handle_message
from app.conversation import (
    Conversation,
    ConversationError,
    conversation_session,
    save_conversation,
)
from app.runtime import create_providers, manage_calendar, read_user_preferences
from features.memory import update_user_memory


def save_offset(path: Path, offset: int) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(str(offset), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="hybrid-assistant telegram", description=__doc__
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Reply to one authorized message and exit, for testing",
    )
    args = parser.parse_args(argv)
    profile = Path.home() / ".hermes/profiles/hw3-local"
    try:
        config = load_telegram_config(profile)
        state = profile / "telegram-inbound"
        state.mkdir(mode=0o700, exist_ok=True)
        with (state / "receiver.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise TelegramError(
                    "A project receiver is already running. Stop it first."
                ) from None
            check_polling_available(config)
            path = state / "offset"
            if path.exists():
                offset = int(path.read_text(encoding="utf-8"))
                if offset < 0:
                    raise ValueError("Invalid offset")
            else:
                # On first launch, discard old queued updates rather than execute them.
                pending = get_updates(config, offset=-1, timeout=0)
                offset = pending[-1]["update_id"] + 1 if pending else 0
                save_offset(path, offset)
            providers = create_providers(load_local_context=False)

            conversation_path = (
                profile / "conversations" / f"telegram-{config.chat_id}.json"
            )

            def reset():
                save_conversation(conversation_path, Conversation())

            def handle(text, context):
                reply = None
                try:
                    with conversation_session(conversation_path) as conversation:
                        reply = handle_message(
                            text,
                            providers,
                            context=context,
                            read_emails=query_gmail,
                            update_memory=update_user_memory,
                            load_preferences=read_user_preferences,
                            manage_calendar=lambda request: manage_calendar(
                                request, offline=context.offline
                            ),
                            conversation=conversation,
                            persist_state=lambda state: save_conversation(
                                conversation_path, state
                            ),
                        )
                except ConversationError:
                    if reply is not None:
                        # The handler returned; only the final session save failed.
                        raise ToolCheckpointError(reply) from None
                    raise
                execution = (
                    reply.execution.provider.value if reply.execution else "none"
                )
                print(
                    f"initial_branch={reply.decision.branch.value} decision_provider={reply.decision.provider.value} answer_provider={execution} "
                    f"decision_steps={reply.decision_count} tool_calls={reply.tool_count} stop_reason={reply.stop_reason}",
                    flush=True,
                )
                return reply.text

            def send(text):
                send_message(text, target=f"telegram:{config.chat_id}")

            print(
                "Telegram receiver started. Only the bound private chat is accepted; Ctrl+C stops the receiver.",
                flush=True,
            )
            while True:
                for update in get_updates(config, offset=offset):
                    next_offset = update["update_id"] + 1
                    if next_offset <= offset:
                        continue
                    # Record before execution: crashes/uncertain sends are not replayed.
                    save_offset(path, next_offset)
                    offset = next_offset
                    if reply_to_update(
                        update, config, handle=handle, send=send, reset=reset
                    ):
                        print("Replied to one request.", flush=True)
                        if args.once:
                            return
    except KeyboardInterrupt:
        print("Receiver stopped.")
    except (TelegramError, DeliveryError, ConversationError) as error:
        parser.exit(1, f"{error}\n")
    except (OSError, ValueError):
        parser.exit(
            1,
            "The receiver cannot read or write local state. Check telegram-inbound in the Local profile.\n",
        )


if __name__ == "__main__":
    main()

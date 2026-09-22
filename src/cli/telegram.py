"""在 WSL 前台接收已绑定的 Telegram 私聊消息；Ctrl+C 停止。"""

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
from app.assistant import handle_message
from app.conversation import (
    Conversation,
    ConversationError,
    conversation_session,
    save_conversation,
)
from app.runtime import create_providers, manage_calendar
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
        "--once", action="store_true", help="回复一条已授权消息后退出，便于测试"
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
                raise TelegramError("已有一个项目接收器在运行，请先停止它。") from None
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
            classifiers = create_providers(load_local_context=False)
            providers = create_providers()

            conversation_path = (
                profile / "conversations" / f"telegram-{config.chat_id}.json"
            )

            def reset():
                save_conversation(conversation_path, Conversation())

            def handle(text, context):
                with conversation_session(conversation_path) as conversation:
                    reply = handle_message(
                        text,
                        providers,
                        classifiers=classifiers,
                        context=context,
                        read_emails=query_gmail,
                        update_memory=update_user_memory,
                        manage_calendar=lambda request: manage_calendar(
                            request, offline=context.offline
                        ),
                        conversation=conversation,
                    )
                execution = (
                    reply.execution.provider.value if reply.execution else "none"
                )
                print(
                    f"任务={reply.intent.task.value} 识别={reply.intent.classifier.value} 执行={execution}",
                    flush=True,
                )
                return reply.text

            def send(text):
                send_message(text, target=f"telegram:{config.chat_id}")

            print("Telegram 接收器已启动。仅处理已绑定私聊；Ctrl+C 停止。", flush=True)
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
                        print("已回复一条请求。", flush=True)
                        if args.once:
                            return
    except KeyboardInterrupt:
        print("接收器已停止。")
    except (TelegramError, DeliveryError, ConversationError) as error:
        parser.exit(1, f"{error}\n")
    except (OSError, ValueError):
        parser.exit(
            1,
            "接收器无法读写本地状态，请检查 Local profile 的 telegram-inbound 目录。\n",
        )


if __name__ == "__main__":
    main()

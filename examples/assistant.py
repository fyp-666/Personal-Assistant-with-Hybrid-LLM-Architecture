"""处理一条自然语言请求：回答问题，或读取并摘要最新一封 Gmail 邮件。"""

import argparse
from pathlib import Path

from hybrid_assistant.assistant import handle_message
from hybrid_assistant.conversation import (
    Conversation,
    ConversationError,
    load_conversation,
    save_conversation,
)
from hybrid_assistant.email import Email
from hybrid_assistant.execution import ProviderError
from hybrid_assistant.gmail import GmailError, load_gmail_credentials, read_gmail_email
from hybrid_assistant.memory import update_user_memory
from hybrid_assistant.routing import Privacy, RequestContext, Source
from hybrid_assistant.runtime import create_providers


def read_latest_email() -> Email | None:
    address, password = load_gmail_credentials()
    return read_gmail_email(address, password)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "message", help="允许发给 GPT 的当前请求；私人内容请加 --private"
    )
    parser.add_argument(
        "--private", action="store_true", help="输入含私人内容，仅使用本地模型"
    )
    parser.add_argument(
        "--offline", action="store_true", help="仅使用本地模型，不连接 Gmail"
    )
    parser.add_argument(
        "--new", action="store_true", help="清空近期上下文后处理这条消息，保留长期偏好"
    )
    args = parser.parse_args()
    context = RequestContext(
        privacy=Privacy.SENSITIVE if args.private else Privacy.PUBLIC,
        source=Source.USER_INPUT,
        offline=args.offline,
    )
    path = Path.home() / ".hermes/profiles/hw3-local/conversations/cli.json"
    try:
        if args.new:
            save_conversation(path, Conversation())
        conversation = load_conversation(path)
        reply = handle_message(
            args.message,
            create_providers(),
            classifiers=create_providers(load_local_context=False),
            context=context,
            read_latest_email=read_latest_email,
            update_memory=update_user_memory,
            conversation=conversation,
        )
        save_conversation(path, conversation)
    except (ProviderError, GmailError, ConversationError) as error:
        parser.exit(1, f"请求失败：{error}\n")
    except ValueError as error:
        parser.error(str(error))
    print(
        f"识别模型：{reply.intent.classifier.value}（回退：{reply.intent.used_fallback}）"
    )
    print(f"任务类型：{reply.intent.task.value}")
    if reply.execution is not None:
        print(
            f"执行模型：{reply.execution.provider.value}（回退：{reply.execution.used_fallback}）"
        )
    print()
    print(reply.text)


if __name__ == "__main__":
    main()

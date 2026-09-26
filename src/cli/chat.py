"""结合近期对话回答问题、查询 Gmail、操作 Google 日历或修改长期偏好。"""

import argparse
from pathlib import Path

from adapters.gmail import GmailError, query_gmail
from app.assistant import ToolCheckpointError, handle_message
from app.conversation import (
    Conversation,
    ConversationError,
    ConversationVersionError,
    conversation_session,
    save_conversation,
)
from app.runtime import create_providers, manage_calendar, read_user_preferences
from core.execution import ProviderError
from core.routing import Privacy, RequestContext, Source
from features.calendar_actions import CalendarError
from features.memory import update_user_memory


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="hybrid-assistant chat", description=__doc__)
    parser.add_argument(
        "message", help="当前请求；公共会话会共享近期上下文，私人内容请加 --private"
    )
    parser.add_argument(
        "--private", action="store_true", help="输入含私人内容，仅使用本地模型"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="仅使用本地模型，不连接 Gmail 或 Google 日历",
    )
    parser.add_argument(
        "--new", action="store_true", help="清空近期上下文后处理这条消息，保留长期偏好"
    )
    args = parser.parse_args(argv)
    context = RequestContext(
        privacy=Privacy.SENSITIVE if args.private else Privacy.PUBLIC,
        source=Source.USER_INPUT,
        offline=args.offline,
    )
    path = Path.home() / ".hermes/profiles/hw3-local/conversations/cli.json"
    reply = None
    try:
        if args.new:
            save_conversation(path, Conversation())
        providers = create_providers(load_local_context=False)
        with conversation_session(path) as conversation:
            reply = handle_message(
                args.message,
                providers,
                context=context,
                read_emails=query_gmail,
                update_memory=update_user_memory,
                load_preferences=read_user_preferences,
                manage_calendar=lambda request: manage_calendar(
                    request, offline=context.offline
                ),
                conversation=conversation,
                persist_state=lambda state: save_conversation(path, state),
            )
    except ConversationVersionError as error:
        parser.exit(1, f"{error}\n本轮未调用模型或执行工具，原会话文件未修改。\n")
    except ConversationError as error:
        confirmed = error.reply if isinstance(error, ToolCheckpointError) else reply
        if confirmed is not None:
            print(confirmed.text)
            parser.exit(
                1,
                "近期会话保存失败，已执行的操作不会因此撤销，请勿重复提交。"
                "隐私状态可能未保存；请修复本地存储后重新查询核实，"
                "继续私人话题时请明确使用 --private。\n",
            )
        parser.exit(
            1,
            f"{error}\n本轮业务可能已执行，长期记忆修改也可能已保存。隐私状态可能未保存；修复会话文件前请继续使用 --private。\n",
        )
    except (ProviderError, GmailError, CalendarError) as error:
        parser.exit(1, f"请求失败：{error}\n")
    except ValueError as error:
        parser.error(str(error))
    print(
        f"决策模型：{reply.decision.provider.value}（回退：{reply.decision.used_fallback}）"
    )
    print(f"首步分支：{reply.decision.branch.value}")
    print(
        f"决策步数：{reply.decision_count}；工具次数：{reply.tool_count}；结束原因：{reply.stop_reason}"
    )
    if reply.execution is not None:
        print(
            f"回答模型：{reply.execution.provider.value}（回退：{reply.execution.used_fallback}）"
        )
    print()
    print(reply.text)


if __name__ == "__main__":
    main()

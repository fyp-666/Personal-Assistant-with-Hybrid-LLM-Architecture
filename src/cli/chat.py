"""Answer with recent context, query Gmail, manage Google Calendar, or update preferences."""

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
        "message",
        help="Current request; public conversations share recent context. Use --private for private content",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Process private content using the local model only",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the local model only, without connecting to Gmail or Google Calendar",
    )
    parser.add_argument(
        "--new",
        action="store_true",
        help="Clear recent context before this request, preserving saved preferences",
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
        parser.exit(
            1,
            f"{error}\nNo model or tools were called. The original conversation file was not modified.\n",
        )
    except ConversationError as error:
        confirmed = error.reply if isinstance(error, ToolCheckpointError) else reply
        if confirmed is not None:
            print(confirmed.text)
            parser.exit(
                1,
                "Conversation saving failed. Completed operations are not undone; do not submit them again. "
                "Privacy state may not have been saved. Fix local storage and query again to verify. "
                "Use --private explicitly when continuing a private topic.\n",
            )
        parser.exit(
            1,
            f"{error}\nOperations may have completed and preference edits may have been saved. Privacy state may not have been saved; use --private until conversation storage is repaired.\n",
        )
    except (ProviderError, GmailError, CalendarError) as error:
        parser.exit(1, f"Request failed: {error}\n")
    except ValueError as error:
        parser.error(str(error))
    print(
        f"Decision provider: {reply.decision.provider.value} (fallback: {reply.decision.used_fallback})"
    )
    print(f"Initial branch: {reply.decision.branch.value}")
    print(
        f"Decision steps: {reply.decision_count}; tool calls: {reply.tool_count}; stop reason: {reply.stop_reason}"
    )
    if reply.execution is not None:
        print(
            f"Answer provider: {reply.execution.provider.value} (fallback: {reply.execution.used_fallback})"
        )
    print()
    print(reply.text)


if __name__ == "__main__":
    main()

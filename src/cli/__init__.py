"""One CLI for assistant capabilities; load only the selected command."""

import argparse
from importlib import import_module


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Personal AI assistant: chat, email, calendars, and saved preferences."
    )
    commands = parser.add_subparsers(dest="command", required=True, title="Commands")
    for name, description in (
        ("chat", "Process a natural-language request and retain context"),
        ("telegram", "Receive messages from the bound Telegram private chat"),
        (
            "gmail",
            "Read and summarize Gmail, with optional batches, daily reports, and delivery",
        ),
        ("memory", "Explicitly remember, change, or forget long-term preferences"),
        (
            "calendar",
            "Google Calendar authorization, file briefings, and due reminders",
        ),
    ):
        commands.add_parser(name, help=description, add_help=False)
    args, remaining = parser.parse_known_args(argv)
    module = import_module(f"cli.{args.command}")
    module.main(remaining)

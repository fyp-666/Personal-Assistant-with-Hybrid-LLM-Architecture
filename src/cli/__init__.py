"""One CLI for assistant capabilities; load only the selected command."""

import argparse
from importlib import import_module


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="个人 AI 助手：聊天、邮件、日历和长期偏好。"
    )
    commands = parser.add_subparsers(dest="command", required=True, title="功能")
    for name, description in (
        ("chat", "处理一条自然语言请求并保留上下文"),
        ("telegram", "接收已绑定 Telegram 私聊"),
        ("gmail", "读取并摘要 Gmail，可选批量、日报和推送"),
        ("memory", "明确记住、修改或忘记长期偏好"),
        ("calendar", "Google 日历授权、本地简报和到期提醒"),
    ):
        commands.add_parser(name, help=description, add_help=False)
    args, remaining = parser.parse_known_args(argv)
    module = import_module(f"cli.{args.command}")
    module.main(remaining)

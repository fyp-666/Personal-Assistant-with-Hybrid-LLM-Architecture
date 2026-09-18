"""Deliver generated text through Hermes' configured messaging platforms."""

import os
import subprocess
from pathlib import Path


class DeliveryError(RuntimeError):
    """Delivery failed or its outcome could not be confirmed."""


def send_message(text: str, *, target: str) -> None:
    """Send once to a caller-selected target using the private Hermes profile."""
    if not text.strip():
        raise DeliveryError("不能发送空消息。")
    if "MEDIA:" in text.upper():
        raise DeliveryError("摘要含有 Hermes 附件标记；本入口只发送文本。")
    profile = Path.home() / ".hermes/profiles/hw3-local"
    env = {
        key: os.environ[key]
        for key in ("HOME", "PATH", "LANG", "LC_ALL")
        if key in os.environ
    }
    env["HERMES_HOME"] = str(profile)
    env["PATH"] = os.pathsep.join(
        (str(Path.home() / ".hermes/bin"), env.get("PATH", os.defpath))
    )
    command = [
        str(Path.home() / ".local/bin/hermes"),
        "--profile",
        "hw3-local",
        "send",
        "--to",
        target,
        "--file",
        "-",
        "--quiet",
    ]
    try:
        result = subprocess.run(
            command,
            input=text,
            capture_output=True,
            encoding="utf-8",
            timeout=45,
            cwd=profile,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise DeliveryError(
            "未能确认消息送达；请先检查 Telegram，避免重复发送。"
        ) from None
    if result.returncode != 0:
        raise DeliveryError(
            "消息发送未完成；请先检查 Telegram，再排查 Hermes 配置和网络。"
        )

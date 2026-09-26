"""Deliver generated text through Hermes' configured messaging platforms."""

import os
import subprocess
from pathlib import Path


class DeliveryError(RuntimeError):
    """Delivery failed or its outcome could not be confirmed."""


class MessageContentError(DeliveryError):
    """Text was rejected locally before any delivery attempt."""


def send_message(text: str, *, target: str) -> None:
    """Send once to a caller-selected target using the private Hermes profile."""
    if not text.strip():
        raise MessageContentError("Cannot send an empty message.")
    if "MEDIA:" in text.upper():
        raise MessageContentError(
            "The summary contains a Hermes attachment marker. This entry point sends text only."
        )
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
            "Message delivery is unconfirmed. Check Telegram first to avoid duplicate sends."
        ) from None
    if result.returncode != 0:
        raise DeliveryError(
            "Message delivery did not complete. Check Telegram first, then the Hermes configuration and network."
        )

"""Single-turn text calls through the installed Hermes CLI in WSL."""

import os
import subprocess
from pathlib import Path

from .execution import ProviderError


def call_hermes(
    prompt: str,
    *,
    profile: Path,
    timeout: float = 90,
    load_context: bool = False,
) -> str:
    """Call a trusted profile; optionally load its context files and memory."""
    home = profile.expanduser().resolve()
    if home.parent.name != "profiles" or home.name == "default":
        raise ValueError("Use a named profile directory under profiles/")
    if not (home / "config.yaml").is_file():
        raise ProviderError(f"Hermes profile {home.name!r} is not configured")

    # Do not inherit provider overrides or credentials from the calling shell.
    env = {
        key: os.environ[key]
        for key in ("HOME", "PATH", "LANG", "LC_ALL")
        if key in os.environ
    }
    # Reuse the scanner installed alongside Hermes in named profiles too.
    env["PATH"] = os.pathsep.join(
        (str(Path.home() / ".hermes" / "bin"), env.get("PATH", os.defpath))
    )
    env.update(HERMES_HOME=str(home), HERMES_SAFE_MODE="1")
    command = [
        str(Path.home() / ".local" / "bin" / "hermes"),
        "--profile",
        home.name,
        "chat",
        "--cli",
        "--oneshot",
        "-Q",
        "--query-file",
        "-",
        "--max-turns",
        "1",
        "--run-budget",
        "60",
    ]
    # Hermes ties context files and persistent memory to the same CLI switch.
    if not load_context:
        command.append("--ignore-rules")
    try:
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            check=False,
            encoding="utf-8",
            timeout=timeout,
            cwd=home,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ProviderError(
            f"Hermes profile {home.name!r} could not complete the call"
        ) from None
    if result.returncode != 0:
        raise ProviderError(
            f"Hermes profile {home.name!r} exited with code {result.returncode}"
        )
    reply = result.stdout.strip()
    if not reply:
        raise ProviderError(f"Hermes profile {home.name!r} returned an empty reply")
    return reply

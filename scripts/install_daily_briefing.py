"""Install the project's script-only Hermes job; email inference stays in the script."""

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
PROFILE = Path.home() / ".hermes/profiles/hw3-local"
NAME = "hw3-daily-email"


def main() -> None:
    script_path = PROFILE / "scripts" / f"{NAME}.sh"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "#!/usr/bin/env bash\n"
        "# HW3 daily email briefing: managed by this project.\n"
        "set -euo pipefail\n"
        f"cd {shlex.quote(str(PROJECT))}\n"
        "systemctl --user start hw3-ollama\n"
        f"exec {shlex.quote(str(PROJECT / '.venv/bin/python'))} "
        f"{shlex.quote(str(PROJECT / 'examples/gmail_summary.py'))} "
        "--daily --send --quiet\n"
    )
    if (
        script_path.exists()
        and "# HW3 daily email briefing:" not in script_path.read_text()
    ):
        raise RuntimeError("Existing script is not owned by this installer")
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o700)

    # Keep all credentials and other profile settings intact.
    env_path = PROFILE / ".env"
    raw = env_path.read_text(encoding="utf-8")
    key = "HERMES_TIMEZONE"
    value = "America/Los_Angeles"
    pattern = rf"(?m)^{key}=[^\r\n]*"
    if len(re.findall(pattern, raw)) > 1:
        raise RuntimeError("Duplicate HERMES_TIMEZONE entries")
    updated = (
        re.sub(pattern, f"{key}={value}", raw)
        if re.search(pattern, raw)
        else raw.rstrip("\n") + f"\n{key}={value}\n"
    )
    env_path.write_text(updated, encoding="utf-8")
    env_path.chmod(0o600)

    job_file = PROFILE / "cron/jobs.json"
    stored = json.loads(job_file.read_text()) if job_file.exists() else {"jobs": []}
    jobs = stored.get("jobs", []) if isinstance(stored, dict) else stored
    matching = [job for job in jobs if job.get("name") == NAME]
    if len(matching) > 1:
        raise RuntimeError("More than one project daily job exists")

    env = {
        key: os.environ[key]
        for key in ("HOME", "PATH", "LANG", "LC_ALL")
        if key in os.environ
    }
    env.update(HERMES_HOME=str(PROFILE), HERMES_TIMEZONE=value)
    env["PATH"] = (
        str(Path.home() / ".hermes/bin") + os.pathsep + env.get("PATH", os.defpath)
    )
    command = [str(Path.home() / ".local/bin/hermes"), "--profile", "hw3-local", "cron"]
    options = [
        "--name",
        NAME,
        "--script",
        script_path.name,
        "--no-agent",
        "--workdir",
        str(PROJECT),
        "--deliver",
        "local",
        "--failure-deliver",
        "telegram",
    ]
    if matching:
        action = ["edit", matching[0]["id"], "--schedule", "0 8 * * *"]
    else:
        action = ["create", "0 8 * * *"]
    subprocess.run(command + action + options, env=env, cwd=PROJECT, check=True)
    # Windows owns the wall-clock trigger, including daylight-saving changes.
    subprocess.run(command + ["pause", NAME], env=env, cwd=PROJECT, check=True)


if __name__ == "__main__":
    main()

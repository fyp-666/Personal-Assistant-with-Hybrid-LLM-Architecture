"""Apply identified preference updates to a local Hermes USER.md file."""

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from difflib import unified_diff
from functools import partial
from pathlib import Path

from adapters.hermes import call_hermes
from core.execution import ProviderError, execute_plan
from core.routing import Provider, RequestContext, plan_route

ENTRY_SEPARATOR = "\n§\n"
USER_MEMORY_LIMIT = 1375  # Matches the installed Hermes default USER.md budget.


@dataclass(frozen=True)
class MemoryUpdate:
    """Actual file contents before and after a validated update."""

    before: str
    after: str

    @property
    def changed(self) -> bool:
        return self.before != self.after


def render_memory_update(update: MemoryUpdate) -> str:
    """Describe the committed changes without a second model call."""
    if not update.changed:
        return "Long-term memory is unchanged. The preference may already exist or the request may lack clear long-term information. Specify the preference to remember, change, or forget."
    changes = unified_diff(
        update.before.splitlines(), update.after.splitlines(), n=0, lineterm=""
    )
    lines = list(changes)[2:]  # Skip file headers; show only actual changed lines.
    details = "\n".join(
        line
        for line in lines
        if line.startswith(("+", "-")) and line[1:].strip() != "§"
    )
    return "Long-term memory updated (- removed, + added):\n" + details


def _read_user_memory(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return ""


def _apply_edits(before: str, reply: str) -> str:
    """Validate the entire model proposal before any file is written."""
    try:
        payload = json.loads(reply)
        if not isinstance(payload, dict) or set(payload) != {"operations"}:
            raise ValueError("Expected an object containing operations")
        operations = payload["operations"]
        if not isinstance(operations, list):
            raise TypeError("operations must be a list")
        if not operations:
            return before
        entries = [
            entry.strip() for entry in before.split(ENTRY_SEPARATOR) if entry.strip()
        ]
        original_entries = entries.copy()
        for operation in operations:
            if not isinstance(operation, dict):
                raise TypeError("Each operation must be an object")
            action = operation.get("action")
            keys = {
                "add": {"action", "content"},
                "replace": {"action", "old_text", "content"},
                "remove": {"action", "old_text"},
            }
            if (
                not isinstance(action, str)
                or action not in keys
                or set(operation) != keys[action]
            ):
                raise ValueError("Unknown operation or fields")
            for key in keys[action] - {"action"}:
                if not isinstance(operation[key], str) or "§" in operation[key]:
                    raise ValueError(
                        "Operation content must be text without the entry separator"
                    )
            if action == "add":
                content = operation["content"].strip()
                if not content:
                    raise ValueError("New content must not be empty")
                if content not in entries:
                    entries.append(content)
                continue
            old_text = operation["old_text"]
            matches = [i for i, entry in enumerate(entries) if old_text in entry]
            if not old_text.strip() or len(matches) != 1:
                raise ValueError("Old text must uniquely match an existing entry")
            index = matches[0]
            if action == "remove":
                entries.pop(index)
            else:
                if entries[index].count(old_text) != 1:
                    raise ValueError(
                        "The replacement target is not unique within its entry"
                    )
                replacement = operation["content"]
                # Ignore boundary punctuation only when checking whether a model
                # accidentally supplied existing context as replacement text.
                boundary_chars = " \t\r\n，,。.;；：:!?！？"
                replacement_body = replacement.strip(boundary_chars)
                if replacement_body == entries[index].strip(boundary_chars):
                    # A model may supply the complete existing entry for a
                    # fragment replacement. It is already the requested text.
                    continue
                prefix, _, suffix = entries[index].partition(old_text)
                prefix_body = prefix.strip(boundary_chars)
                suffix_body = suffix.strip(boundary_chars)
                if (prefix_body and replacement_body.startswith(prefix_body)) or (
                    suffix_body and replacement_body.endswith(suffix_body)
                ):
                    raise ValueError(
                        "A partial replacement duplicates unchanged context. Supply only the replacement fragment"
                    )
                content = (prefix + replacement + suffix).strip()
                if not content:
                    raise ValueError("Use remove to delete an entire entry")
                entries[index] = content
        if entries == original_entries:
            return before
        after = ENTRY_SEPARATOR.join(entries)
        if len(after) > USER_MEMORY_LIMIT:
            raise ValueError(
                "The user profile exceeds 1375 characters. Shorten the preferences first"
            )
        return after
    except (ValueError, TypeError) as error:
        raise ProviderError(f"Cannot apply the proposed memory edit: {error}") from None


def _save_user_memory(path: Path, before: str, after: str) -> None:
    """Use the same lock and entry format as Hermes; replace the file atomically."""
    import fcntl  # This project runs inside WSL / Linux.

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".md.lock").open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if _read_user_memory(path) != before:
            raise ProviderError(
                "The user profile changed during model extraction. Submit the request again"
            )
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as output:
                temporary = Path(output.name)
                output.write(after)
            os.replace(temporary, path)  # NamedTemporaryFile uses mode 600.
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def update_user_memory(
    request: str,
    *,
    profile: Path | None = None,
    generate: Callable[[str], str] | None = None,
) -> MemoryUpdate:
    """Validate a model proposal and commit it to the local preference file."""
    if not request.strip():
        raise ValueError("Specify the preference to remember, change, or remove.")
    if profile is None:
        profile = Path.home() / ".hermes/profiles/hw3-local"
    profile = profile.expanduser().resolve()
    path = profile / "memories/USER.md"
    before = _read_user_memory(path)
    prompt = (
        "Merge the user's long-term preferences into the existing profile using minimal text edits. Return only JSON, without code fences or explanations. "
        "The input may be a recognized preference or a direct request to remember, change, or forget one. "
        "Process preferences only. Do not store current queries, summaries, questions, or temporary tasks in the profile. "
        'Use {"operations":[...]}. Return an empty list if there is no long-term information to save or the preference already exists. '
        'New entry: {"action":"add","content":"A concise new preference"}. '
        'Partial edit: {"action":"replace","old_text":"Exact original fragment","content":"Replacement fragment"}. '
        'Forget an entire entry: {"action":"remove","old_text":"A unique original fragment from that entry"}. '
        "Copy old_text verbatim from the current profile so it matches uniquely. replace changes only that fragment. "
        "The scope of content must match old_text. For a few changed words, provide only their replacement. "
        "To replace a whole entry, old_text must be the complete old entry and content the complete new entry, preserving all other requirements. "
        "Do not pair a partial old_text with a full new entry; that would duplicate unchanged text. "
        "For example, to switch summary language from English to French, use old_text=use English and content=use French. "
        "Preserve existing requirements not mentioned in this request. A brief restatement does not authorize deleting other details. "
        "For example, changing only the summary language preserves formatting, missing-information handling, and other entries. "
        "Do not duplicate other entries or store editing instructions, passwords, tokens, "
        "raw email bodies, or temporary tasks. The profile's section sign (§) is only an entry separator; do not include it in operation fields. "
        "Input (JSON):\n"
        + json.dumps(
            {"user_request": request, "current_user_profile": before},
            ensure_ascii=False,
        )
    )
    # The profile has no tools. Extraction is a text call, with no model-side writes.
    if generate is None:
        providers = {
            Provider.OPENAI: partial(
                call_hermes, profile=profile.parent / "hw3-openai"
            ),
            Provider.LOCAL: partial(call_hermes, profile=profile),
        }
        reply = execute_plan(plan_route(RequestContext()), prompt, providers).text
    else:
        reply = generate(prompt)
    after = _apply_edits(before, reply)
    if after != before:
        _save_user_memory(path, before, after)
    return MemoryUpdate(before, after)

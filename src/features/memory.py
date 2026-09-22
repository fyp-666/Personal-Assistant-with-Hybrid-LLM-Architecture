"""Apply identified preference updates locally to Hermes USER.md."""

import json
import os
import tempfile
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path

from adapters.hermes import call_hermes
from core.execution import ProviderError

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
        return "长期记忆没有变化。偏好可能已存在，或请求缺少明确的长期信息；可以具体说明要记住、修改或忘记的偏好。"
    changes = unified_diff(
        update.before.splitlines(), update.after.splitlines(), n=0, lineterm=""
    )
    lines = list(changes)[2:]  # Skip file headers; show only actual changed lines.
    details = "\n".join(
        line
        for line in lines
        if line.startswith(("+", "-")) and line[1:].strip() != "§"
    )
    return "长期记忆已更新（- 删除，+ 新增）：\n" + details


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
            raise ValueError("需要 operations 对象")
        operations = payload["operations"]
        if not isinstance(operations, list):
            raise TypeError("operations 必须是列表")
        if not operations:
            return before
        entries = [
            entry.strip() for entry in before.split(ENTRY_SEPARATOR) if entry.strip()
        ]
        original_entries = entries.copy()
        for operation in operations:
            if not isinstance(operation, dict):
                raise TypeError("操作必须是对象")
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
                raise ValueError("未知操作或字段")
            for key in keys[action] - {"action"}:
                if not isinstance(operation[key], str) or "§" in operation[key]:
                    raise ValueError("操作内容必须是文本，不能包含条目分隔符")
            if action == "add":
                content = operation["content"].strip()
                if not content:
                    raise ValueError("新增内容不能为空")
                if content not in entries:
                    entries.append(content)
                continue
            old_text = operation["old_text"]
            matches = [i for i, entry in enumerate(entries) if old_text in entry]
            if not old_text.strip() or len(matches) != 1:
                raise ValueError("旧内容必须唯一匹配一个已有条目")
            index = matches[0]
            if action == "remove":
                entries.pop(index)
            else:
                if entries[index].count(old_text) != 1:
                    raise ValueError("待替换片段在条目中不唯一")
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
                    raise ValueError("局部替换重复包含未修改的前后文，请仅提供替换片段")
                content = (prefix + replacement + suffix).strip()
                if not content:
                    raise ValueError("删除整条请使用 remove")
                entries[index] = content
        if entries == original_entries:
            return before
        after = ENTRY_SEPARATOR.join(entries)
        if len(after) > USER_MEMORY_LIMIT:
            raise ValueError("用户档案超过 1375 字符，请先精简偏好")
        return after
    except (ValueError, TypeError) as error:
        raise ProviderError(f"无法应用模型给出的记忆修改：{error}") from None


def _save_user_memory(path: Path, before: str, after: str) -> None:
    """Use the same lock and entry format as Hermes; replace the file atomically."""
    import fcntl  # This project runs inside WSL / Linux.

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".md.lock").open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if _read_user_memory(path) != before:
            raise ProviderError("用户档案在模型提取期间发生变化，请重新发起请求")
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


def update_user_memory(request: str, *, profile: Path | None = None) -> MemoryUpdate:
    """Apply a preference statement or edit; injected profiles must be local."""
    if not request.strip():
        raise ValueError("请提供要记住、修改或删除的偏好。")
    if profile is None:
        profile = Path.home() / ".hermes/profiles/hw3-local"
    profile = profile.expanduser().resolve()
    path = profile / "memories/USER.md"
    before = _read_user_memory(path)
    prompt = (
        "将用户表达的长期偏好合并到现有档案，生成最小文本修改。只输出 JSON，不要代码块或解释。"
        "输入可以是已识别的偏好陈述，也可以是用户直接给出的记住/修改/忘记请求。"
        "仅处理偏好；本次查询、总结、回答、临时待办等指令不能写入档案。"
        '格式为 {"operations":[...]}。没有需保存的长期信息或偏好已存在时返回空列表。'
        '新增条目：{"action":"add","content":"简短的新偏好陈述"}；'
        '局部修改：{"action":"replace","old_text":"需要改动的原文片段","content":"替换片段"}；'
        '忘记整个条目：{"action":"remove","old_text":"该条目独有的原文片段"}。'
        "old_text 必须从当前档案逐字复制，并唯一匹配；replace 只替换这个片段，"
        "content 的范围必须与 old_text 一致，只改几个字就只提供对应的替换片段。"
        "若确需替换整个条目，old_text 必须是完整旧条目，content 是保留其余约定的完整新条目。"
        "不能用局部 old_text 配上完整的新条目，否则会重复拼接未修改的部分。"
        "例如把摘要语言从中文改为英文，只需 old_text=使用中文，content=使用英文。"
        "当前请求没有提及的原有约定必须保留；简短重述偏好不表示要删除其余细节。"
        "例如只改变摘要语言时，原有的排版、信息缺失处理和其他条目均保留。"
        "不复制其他已有条目，不保存编辑指令、密码、令牌、"
        "原始邮件正文或临时待办。当前档案中的 § 仅是条目分隔符，不放进操作字段。"
        "输入（JSON）：\n"
        + json.dumps(
            {"user_request": request, "current_user_profile": before},
            ensure_ascii=False,
        )
    )
    # The profile has no tools. Extraction is a text call, with no model-side writes.
    reply = call_hermes(prompt, profile=profile)
    after = _apply_edits(before, reply)
    if after != before:
        _save_user_memory(path, before, after)
    return MemoryUpdate(before, after)

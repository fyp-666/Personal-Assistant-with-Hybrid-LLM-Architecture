"""Run bounded decisions with tool feedback and durable, non-replayed effects."""

import json
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Literal

from adapters.gmail import GmailError
from app.conversation import Conversation, ConversationError, bound_email_result
from app.decision import USER_TIMEZONE, DecisionBranch, StepDecision, decide_next_step
from core.execution import ExecutionResult, ProviderError, execute_plan
from core.routing import Privacy, Provider, RequestContext, plan_route
from features.calendar_actions import (
    MAX_CALENDAR_RESULTS,
    CalendarError,
    CalendarRequest,
    CalendarResult,
    render_calendar_result,
)
from features.email import EmailQuery, EmailSearchResult
from features.memory import MemoryUpdate, render_memory_update


@dataclass(frozen=True)
class MemoryOutcome:
    """Confirmed outcome of this request's optional memory step."""

    status: Literal["updated", "unchanged", "failed"]
    text: str


@dataclass(frozen=True)
class AssistantReply:
    text: str
    decision: StepDecision  # First step, retained for request-level metadata.
    execution: ExecutionResult | None = None
    memory: MemoryOutcome | None = None
    decision_count: int = 0
    tool_count: int = 0
    stop_reason: str = "completed"


class ToolCheckpointError(ConversationError):
    """A confirmed reply exists, but storing its conversation state failed."""

    def __init__(self, reply: AssistantReply):
        super().__init__("已取得回复，但会话状态保存失败。")
        self.reply = replace(reply, stop_reason="persistence_failed")


def _update_memory(
    request: str, updater: Callable[..., MemoryUpdate], generate: Callable[[str], str]
) -> MemoryOutcome:
    try:
        update = updater(request, generate=generate)
    except (ProviderError, OSError, UnicodeError):
        # Do not let a failed optional step suppress the independent answer,
        # or expose provider diagnostics / local paths to a messaging adapter.
        return MemoryOutcome(
            "failed",
            "未能确认长期记忆更新成功。请检查模型连接、档案权限或修改指令；本次其他请求会继续处理。",
        )
    return MemoryOutcome(
        "updated" if update.changed else "unchanged", render_memory_update(update)
    )


def _email_sources(result: EmailSearchResult) -> str:
    """Show the actual query scope and stable result numbers without inference."""
    query = result.query
    lines = [f"收件箱查询：本次返回 {len(result.emails)} 封，上限 {query.limit} 封。"]
    if query.subject is not None:
        lines.append(f"主题包含：{query.subject}")
    if query.received_since is not None:
        lines.append(
            f"收件时间：{query.received_since.isoformat()}（含）至 "
            f"{query.received_before.isoformat()}（不含）"
        )
    lines.append("顺序：按邮件加入收件箱的顺序，从新到旧。")
    for number, email in enumerate(result.emails, 1):
        lines.append(f"[{number}] 发件人：{email.sender}\n主题：{email.subject}")
        if not email.body.strip():
            lines.append("正文：没有可摘要的文本，图片或附件内容尚未解析。")
    if result.has_more:
        lines.append(
            "还有匹配邮件未展示；本次回答仅覆盖以上结果，可缩小日期或主题范围。"
        )
    return "\n".join(lines)


@dataclass(frozen=True)
class _ToolOutcome:
    capability: str
    operation: str
    status: Literal["completed", "not_executed", "unconfirmed"]
    detail: str
    executed: bool = False
    email_result: EmailSearchResult | None = None
    calendar_result: CalendarResult | None = None

    def model_data(self, requested: dict, actual: dict) -> dict:
        data = {
            "capability": self.capability,
            "operation": self.operation,
            "status": self.status,
            "detail": self.detail,
            "requested_arguments": requested,
            "arguments": actual,
        }
        # Each result is bounded by the existing email/calendar limits, and
        # there can be at most max_tool_calls observations in one run.
        result_state = Conversation(
            email_result=self.email_result, calendar_result=self.calendar_result
        ).payload()
        for key in ("email_result", "calendar_result"):
            if key in result_state:
                data[key] = result_state[key]
        return data


def _render_tool_receipts(
    outcomes: list[_ToolOutcome], calendar_goal: str | None
) -> str:
    """Keep requested query results and failures without repeating write lookups."""
    if not outcomes:
        return ""
    visible = [
        prior
        for prior in outcomes[:-1]
        if prior.status != "completed"
        or prior.operation != "query"
        or prior.capability == "email"
        or calendar_goal == "query"
    ] + [outcomes[-1]]
    query_count = sum(
        item.operation == "query" and item.status == "completed" for item in visible
    )
    query_number = 0
    receipts = []
    for item in visible:
        if item.operation == "query" and item.status == "completed" and query_count > 1:
            query_number += 1
            receipts.append(f"查询结果 {query_number}：\n{item.detail}")
        else:
            receipts.append(item.detail)
    return "\n\n".join(receipts)


def _execute_tool(
    request: EmailQuery | CalendarRequest,
    *,
    state: Conversation,
    context: RequestContext,
    read_emails: Callable[[EmailQuery], EmailSearchResult],
    manage_calendar: Callable[[CalendarRequest], CalendarResult] | None,
) -> _ToolOutcome:
    if isinstance(request, CalendarRequest):

        def outcome(status, detail, *, executed=False, result=None):
            return _ToolOutcome(
                "calendar",
                request.operation,
                status,
                detail,
                executed=executed,
                calendar_result=result,
            )

        if manage_calendar is None:
            return outcome("not_executed", "日历操作暂未配置，本次未执行。")
        if request.operation in {"update", "cancel"} and not any(
            item.event_id == request.event_id
            and item.version == request.version
            and item.status == "confirmed"
            for item in state.calendar_items
        ):
            return outcome(
                "not_executed",
                "目标或版本不在当前已确认记录中，本次未修改或取消任何日程。",
            )
        try:
            result = manage_calendar(request)
            if (
                result.operation != request.operation
                or result.query != request.query
                or (
                    request.operation in {"update", "cancel"}
                    and result.items[0].event_id != request.event_id
                )
            ):
                raise CalendarError(
                    "日历返回结果与请求不符；请重新查询核实实际状态，勿重复写入。"
                )
        except CalendarError as error:
            return outcome("unconfirmed", str(error), executed=True)
        return outcome(
            "completed",
            render_calendar_result(result, include_identifiers=False),
            executed=True,
            result=result,
        )

    if context.offline:
        return _ToolOutcome(
            "email",
            "query",
            "not_executed",
            "离线模式无法查询 Gmail；可以继续讨论已保存的邮件资料。",
        )
    try:
        result = read_emails(request)
    except GmailError:
        return _ToolOutcome(
            "email",
            "query",
            "unconfirmed",
            "本次邮箱查询未完成，未取得新结果；已有邮件资料仅为历史快照。",
            executed=True,
        )
    if result.query != request:
        return _ToolOutcome(
            "email",
            "query",
            "unconfirmed",
            "邮箱返回的查询范围与请求不一致，本次结果未采用。",
            executed=True,
        )
    bounded = bound_email_result(result)
    detail = _email_sources(bounded)
    if not bounded.emails:
        detail += "\n没有符合这些条件的邮件。"
    return _ToolOutcome(
        "email", "query", "completed", detail, executed=True, email_result=bounded
    )


def handle_message(
    message: str,
    providers: Mapping[Provider, Callable[[str], str]],
    *,
    context: RequestContext,
    read_emails: Callable[[EmailQuery], EmailSearchResult],
    update_memory: Callable[..., MemoryUpdate],
    manage_calendar: Callable[[CalendarRequest], CalendarResult] | None = None,
    conversation: Conversation | None = None,
    now: datetime | None = None,
    load_preferences: Callable[[], str] | None = None,
    persist_state: Callable[[Conversation], None] | None = None,
    max_steps: int = 5,
    max_tool_calls: int = 4,
    max_elapsed_seconds: float = 240,
) -> AssistantReply:
    """Keep deciding after reads, with one calendar write allowed per user request.

    The time budget is checked before starting another step, never by interrupting
    an in-flight write. The existing provider/API timeouts still bound those calls.
    Callers can checkpoint confirmed results before the next model runs.
    """
    if any(type(n) is not int or n < 1 for n in (max_steps, max_tool_calls)):
        raise ValueError("决策步数与工具次数上限必须是正整数。")
    if (
        type(max_elapsed_seconds) not in (int, float)
        or not math.isfinite(max_elapsed_seconds)
        or max_elapsed_seconds <= 0
    ):
        raise ValueError("处理时限必须是有限正数。")
    started = time.monotonic()
    state = conversation if conversation is not None else Conversation()
    # Only trusted request restrictions persist. A provider fallback is run-local.
    if state.private:
        context = replace(context, privacy=Privacy.SENSITIVE)
    if context.privacy is Privacy.SENSITIVE or not context.cloud_allowed:
        state.private = True
    current_time = now if now is not None else datetime.now(USER_TIMEZONE)
    preferences = load_preferences() if load_preferences is not None else ""
    execution_context = context
    initial_decision = None
    calendar_goal = None
    memory = None
    preferences_dirty = False
    decisions = 0
    tool_calls = 0
    write_completed = False
    seen_requests = set()
    outcomes: list[_ToolOutcome] = []
    tool_history: list[dict] = []

    def generate_memory(prompt: str) -> str:
        nonlocal execution_context
        try:
            result = execute_plan(plan_route(execution_context), prompt, providers)
        except ProviderError:
            execution_context = replace(execution_context, cloud_allowed=False)
            raise
        if result.used_fallback:
            execution_context = replace(execution_context, cloud_allowed=False)
        return result.text

    def finish(text, execution=None, *, stop_reason="completed"):
        if memory is not None:
            text = memory.text + "\n\n" + text
        state.record(
            message,
            text,
            private=state.private,
            complexity=initial_decision.context.complexity,
        )
        return AssistantReply(
            text,
            initial_decision,
            execution,
            memory,
            decisions,
            tool_calls,
            stop_reason,
        )

    def stop(detail, reason):
        receipts = _render_tool_receipts(outcomes, calendar_goal)
        if receipts:
            detail += "\n以下是本轮已取得的实际结果：\n" + receipts
        return finish(detail, stop_reason=reason)

    for step in range(1, max_steps + 1):
        if (
            initial_decision is not None
            and time.monotonic() - started >= max_elapsed_seconds
        ):
            return stop("已达到本轮处理时限，未再执行后续操作。", "time_limit")
        if preferences_dirty and load_preferences is not None:
            try:
                preferences = load_preferences()
            except (ProviderError, OSError, UnicodeError):
                return stop("偏好读取失败，后续处理已停止。", "preferences_unavailable")
            preferences_dirty = False
        run_state = {
            "step": step,
            "remaining_steps": max_steps - step,
            "tool_calls_remaining": max_tool_calls - tool_calls,
            "calendar_goal": calendar_goal,
            "write_completed": write_completed,
            "memory_processed": initial_decision is not None,
            "memory_outcome": asdict(memory) if memory is not None else None,
            "tool_history": tool_history,
        }
        decisions += 1
        try:
            decision = decide_next_step(
                message,
                providers,
                context=execution_context,
                conversation=state,
                now=current_time,
                user_preferences=preferences,
                run_state=run_state,
            )
        except ProviderError:
            if initial_decision is None:
                raise
            return stop("后续模型决策暂不可用，未重试任何工具。", "decision_failed")
        execution_context = decision.context
        if decision.used_fallback:
            execution_context = replace(execution_context, cloud_allowed=False)
        if initial_decision is None:
            initial_decision = decision
            calendar_goal = decision.calendar_goal
            if decision.memory_request is not None:
                memory = _update_memory(
                    decision.memory_request, update_memory, generate_memory
                )
                preferences_dirty = memory.status != "failed"
        elif decision.memory_request is not None:
            # Defense in depth if a custom decision provider bypasses the parser.
            return stop("本轮记忆步骤已处理，未重复保存。", "repeated_memory")

        if decision.branch is DecisionBranch.ANSWER:
            text = decision.answer
            emails = [o.email_result for o in outcomes if o.email_result is not None]
            if emails:
                sources = [
                    (f"查询{i}：\n" if len(emails) > 1 else "") + _email_sources(result)
                    for i, result in enumerate(emails, 1)
                ]
                text = "\n\n".join([*sources, text])
            execution = ExecutionResult(
                decision.provider, decision.answer, decision.used_fallback
            )
            return finish(text, execution)

        request = (
            decision.calendar_request
            if decision.branch is DecisionBranch.CALENDAR
            else decision.email_query
        )
        if request is None:
            return stop("工具参数缺失，本次拟议操作未执行。", "invalid_request")
        requested = request.to_dict()
        if isinstance(request, CalendarRequest):
            if decision.calendar_goal != calendar_goal:
                return stop("后续日历操作超出本轮原定目标，未执行。", "goal_changed")
            if request.operation != "query":
                if request.operation != calendar_goal:
                    return stop("本轮没有对应的日历写入目标，未执行。", "goal_changed")
                if write_completed:
                    return stop(
                        "本轮已完成一个日历写入，未重复或追加写入。", "write_limit"
                    )
            elif calendar_goal in {"update", "cancel"}:
                # Target discovery is a date-bounded candidate read, not a literal
                # title search. Keep the original description for the next model
                # decision; never map natural-language phrases to hardcoded names.
                request = replace(
                    request,
                    query=replace(request.query, text=None, limit=MAX_CALENDAR_RESULTS),
                )
        actual = request.to_dict()
        fingerprint = (
            decision.branch.value,
            write_completed,
            json.dumps(actual, sort_keys=True),
        )
        if fingerprint in seen_requests:
            return stop(
                "查询或操作条件未变化，已停止重复调用；请补充可区分目标的信息。",
                "repeated_tool",
            )
        if tool_calls >= max_tool_calls:
            return stop("已达到本轮工具次数上限，未执行后续操作。", "tool_limit")
        if time.monotonic() - started >= max_elapsed_seconds:
            return stop("已达到本轮处理时限，本次拟议操作未执行。", "time_limit")
        seen_requests.add(fingerprint)
        outcome = _execute_tool(
            request,
            state=state,
            context=execution_context,
            read_emails=read_emails,
            manage_calendar=manage_calendar,
        )
        outcomes.append(outcome)
        tool_calls += int(outcome.executed)
        tool_history.append(outcome.model_data(requested, actual))
        if outcome.status != "completed":
            # A failed/uncertain transport is not permission to replay a write.
            return stop(
                "本轮工具未取得可确认的成功结果，后续操作已停止。", outcome.status
            )
        state.apply_results(
            email_result=outcome.email_result, calendar_result=outcome.calendar_result
        )
        if outcome.capability == "calendar" and outcome.operation != "query":
            write_completed = True
        if persist_state is not None:
            try:
                persist_state(state)
            except ConversationError:
                # A persistence failure must stop execution without hiding the
                # confirmed side effect or presenting the turn as completed.
                reply = stop(
                    "会话保存失败，后续操作已停止。已执行的操作不会因此撤销，请勿重复提交。",
                    "persistence_failed",
                )
                raise ToolCheckpointError(reply) from None
        if decision.result_mode == "direct":
            return finish(_render_tool_receipts(outcomes, calendar_goal))
    return stop("已达到本轮决策步数上限，未再调用模型或工具。", "step_limit")

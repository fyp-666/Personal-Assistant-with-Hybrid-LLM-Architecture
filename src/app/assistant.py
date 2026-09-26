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
    decision_providers: tuple[Provider, ...] = ()  # Successfully parsed decisions only.
    reasoning_delegated: bool = False


class ToolCheckpointError(ConversationError):
    """A confirmed reply exists, but storing its conversation state failed."""

    def __init__(self, reply: AssistantReply):
        super().__init__(
            "A reply is available, but conversation state could not be saved."
        )
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
            "The preference update could not be confirmed. Check the model connection, profile permissions, or edit instructions; the rest of this request will continue.",
        )
    return MemoryOutcome(
        "updated" if update.changed else "unchanged", render_memory_update(update)
    )


def _email_sources(result: EmailSearchResult) -> str:
    """Show the actual query scope and stable result numbers without inference."""
    query = result.query
    lines = [
        f"Inbox query: returned {len(result.emails)} messages; limit {query.limit}."
    ]
    if query.subject is not None:
        lines.append(f"Subject contains: {query.subject}")
    if query.received_since is not None:
        lines.append(
            f"Received range: {query.received_since.isoformat()} (inclusive) to "
            f"{query.received_before.isoformat()} (exclusive)"
        )
    lines.append("Order: newest to oldest by arrival in the inbox.")
    for number, email in enumerate(result.emails, 1):
        lines.append(f"[{number}] Sender: {email.sender}\nSubject: {email.subject}")
        if not email.body.strip():
            lines.append(
                "Body: no summarizable text; images and attachments have not been parsed."
            )
    if result.has_more:
        lines.append(
            "More matching messages are available. This answer covers only the results above; narrow the date or subject range."
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
            receipts.append(f"Query result {query_number}:\n{item.detail}")
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
            return outcome(
                "not_executed",
                "Calendar operations are not configured. This operation was not performed.",
            )
        if request.operation in {"update", "cancel"} and not any(
            item.event_id == request.event_id
            and item.version == request.version
            and item.status == "confirmed"
            for item in state.calendar_items
        ):
            return outcome(
                "not_executed",
                "The target or version is not among the confirmed records. No event was modified or cancelled.",
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
                    "The calendar result does not match the request. Query again to verify the actual state; do not repeat the write."
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
            "Gmail cannot be queried offline. Previously saved email data remains available for discussion.",
        )
    try:
        result = read_emails(request)
    except GmailError:
        return _ToolOutcome(
            "email",
            "query",
            "unconfirmed",
            "The inbox query did not complete and returned no new results. Existing email data is only a historical snapshot.",
            executed=True,
        )
    if result.query != request:
        return _ToolOutcome(
            "email",
            "query",
            "unconfirmed",
            "The returned email query scope differs from the request. These results were not used.",
            executed=True,
        )
    bounded = bound_email_result(result)
    detail = _email_sources(bounded)
    if not bounded.emails:
        detail += "\nNo messages match these conditions."
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
        raise ValueError("Decision and tool-call limits must be positive integers.")
    if (
        type(max_elapsed_seconds) not in (int, float)
        or not math.isfinite(max_elapsed_seconds)
        or max_elapsed_seconds <= 0
    ):
        raise ValueError("The time limit must be a finite positive number.")
    started = time.monotonic()
    state = conversation if conversation is not None else Conversation()
    # Privacy restrictions and active model are separate persisted state.
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
    decision_providers: list[Provider] = []
    started_with_reasoning = (
        plan_route(context, active_provider=state.active_provider).primary
        is Provider.NIM
    )
    reasoning_active = started_with_reasoning
    reasoning_delegated = False
    reasoning_request = None
    provider_notices: list[str] = []
    memory_fallback_provider: Provider | None = None
    write_completed = False
    seen_requests = set()
    outcomes: list[_ToolOutcome] = []
    tool_history: list[dict] = []

    def generate_memory(prompt: str) -> str:
        nonlocal execution_context, memory_fallback_provider
        route = plan_route(execution_context, active_provider=state.active_provider)
        try:
            result = execute_plan(route, prompt, providers)
        except ProviderError:
            execution_context = replace(execution_context, cloud_allowed=False)
            if route.primary is not Provider.LOCAL:
                memory_fallback_provider = route.primary
            raise
        if result.used_fallback and result.provider is Provider.LOCAL:
            execution_context = replace(execution_context, cloud_allowed=False)
            memory_fallback_provider = route.primary
        return result.text

    def finish(text, execution=None, *, stop_reason="completed"):
        if provider_notices:
            text = "\n".join(provider_notices) + "\n\n" + text
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
            tuple(decision_providers),
            reasoning_delegated,
        )

    def stop(detail, reason):
        receipts = _render_tool_receipts(outcomes, calendar_goal)
        if receipts:
            detail += "\nActual results obtained during this request:\n" + receipts
        return finish(detail, stop_reason=reason)

    for step in range(1, max_steps + 1):
        if (
            initial_decision is not None
            and time.monotonic() - started >= max_elapsed_seconds
        ):
            return stop(
                "The request time limit was reached. No further operations were performed.",
                "time_limit",
            )
        if preferences_dirty and load_preferences is not None:
            try:
                preferences = load_preferences()
            except (ProviderError, OSError, UnicodeError):
                return stop(
                    "Preference loading failed. Further processing stopped.",
                    "preferences_unavailable",
                )
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
            "reasoning_delegated": reasoning_delegated,
            "reasoning_active": reasoning_active,
            "reasoning_request": reasoning_request,
            "reasoning_available": (
                not reasoning_delegated
                and not started_with_reasoning
                and not reasoning_active
                and step < max_steps
                and Provider.NIM in providers
                and plan_route(
                    execution_context, active_provider=state.active_provider
                ).primary
                is Provider.OPENAI
            ),
        }
        requested_provider = plan_route(
            execution_context,
            reasoning=reasoning_active,
            active_provider=state.active_provider,
        ).primary
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
                reasoning=reasoning_active,
            )
        except ProviderError:
            if initial_decision is None:
                raise
            return stop(
                "The next model decision is unavailable. No tools were retried.",
                "decision_failed",
            )
        # A custom decision implementation cannot loosen trusted restrictions.
        execution_context = replace(
            decision.context,
            privacy=(
                Privacy.SENSITIVE
                if execution_context.privacy is Privacy.SENSITIVE
                else decision.context.privacy
            ),
            offline=execution_context.offline or decision.context.offline,
            cloud_allowed=execution_context.cloud_allowed
            and decision.context.cloud_allowed,
        )
        decision_providers.append(decision.provider)
        # Only a parsed main decision establishes which model actually took over.
        # This is saved with normal replies and existing tool checkpoints.
        state.active_provider = decision.provider
        reasoning_active = decision.provider is Provider.NIM
        fallback_from = (
            requested_provider if decision.used_fallback else memory_fallback_provider
        )
        if fallback_from is not None and (
            decision.used_fallback or decision.provider is Provider.LOCAL
        ):
            names = {
                Provider.OPENAI: "GPT",
                Provider.NIM: "NVIDIA",
                Provider.LOCAL: "Local",
            }
            provider_notices.append(
                f"{names[fallback_from]} is unavailable. "
                f"Continuing this conversation with {names[decision.provider]}."
            )
            memory_fallback_provider = None
        if decision.used_fallback and decision.provider is Provider.LOCAL:
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
            return stop(
                "Memory was already processed for this request. It was not saved again.",
                "repeated_memory",
            )

        if decision.branch is DecisionBranch.DELEGATE_REASONING:
            if reasoning_delegated or started_with_reasoning:
                return stop(
                    "Reasoning was already delegated in this request. Further handoffs stopped.",
                    "repeated_reasoning",
                )
            if (
                plan_route(
                    execution_context, active_provider=state.active_provider
                ).primary
                is not Provider.OPENAI
                or decision.provider is not Provider.OPENAI
            ):
                return stop(
                    "Reasoning delegation is unavailable under the current local-only policy. No content was sent to NVIDIA.",
                    "reasoning_forbidden",
                )
            if Provider.NIM not in providers:
                return stop(
                    "The reasoning provider is unavailable. No handoff was performed.",
                    "reasoning_unavailable",
                )
            if decision.calendar_goal != calendar_goal:
                return stop(
                    "The reasoning handoff changed the original calendar goal. It was not performed.",
                    "goal_changed",
                )
            if not decision.delegate_reasoning:
                return stop(
                    "The reasoning handoff did not provide a reason. It was not performed.",
                    "invalid_reasoning",
                )
            if step >= max_steps:
                return stop(
                    "The decision-step limit leaves no room for a reasoning handoff.",
                    "step_limit",
                )
            if time.monotonic() - started >= max_elapsed_seconds:
                return stop(
                    "The request time limit was reached. No reasoning handoff was performed.",
                    "time_limit",
                )
            reasoning_delegated = True
            reasoning_active = True
            reasoning_request = decision.delegate_reasoning
            continue

        if decision.branch is DecisionBranch.ANSWER:
            text = decision.answer
            emails = [o.email_result for o in outcomes if o.email_result is not None]
            if emails:
                sources = [
                    (f"Query {i}:\n" if len(emails) > 1 else "")
                    + _email_sources(result)
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
            return stop(
                "Tool arguments are missing. The proposed operation was not performed.",
                "invalid_request",
            )
        requested = request.to_dict()
        if isinstance(request, CalendarRequest):
            if decision.calendar_goal != calendar_goal:
                return stop(
                    "The calendar operation exceeds the original goal. It was not performed.",
                    "goal_changed",
                )
            if request.operation != "query":
                if request.operation != calendar_goal:
                    return stop(
                        "There is no matching calendar write goal for this request. It was not performed.",
                        "goal_changed",
                    )
                if write_completed:
                    return stop(
                        "One calendar write already completed in this request. No repeated or additional write was performed.",
                        "write_limit",
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
                "The query or operation is unchanged. Repeated calls stopped; provide information that distinguishes the target.",
                "repeated_tool",
            )
        if tool_calls >= max_tool_calls:
            return stop(
                "The tool-call limit was reached. No further operations were performed.",
                "tool_limit",
            )
        if time.monotonic() - started >= max_elapsed_seconds:
            return stop(
                "The request time limit was reached. The proposed operation was not performed.",
                "time_limit",
            )
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
                "The tool did not return a confirmed successful result. Further operations stopped.",
                outcome.status,
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
                    "Conversation saving failed. Further operations stopped. Completed operations are not undone; do not submit them again.",
                    "persistence_failed",
                )
                raise ToolCheckpointError(reply) from None
        if decision.result_mode == "direct":
            return finish(_render_tool_receipts(outcomes, calendar_goal))
    return stop(
        "The decision-step limit was reached. No further model or tool calls were made.",
        "step_limit",
    )

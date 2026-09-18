# Personal-Assistant-with-Hybrid-LLM-Architecture

> The automated test suite stays local and is not published. Test commands in this historical snapshot require a locally available tests/ directory.

## Development environment (WSL)

Project code runs in Ubuntu on WSL with Python 3.11.16. Its `.venv` is
separate from the Hermes runtime at `~/.hermes/hermes-agent/venv`.
The current checkpoint provides an installable `hybrid_assistant` package,
a deterministic route planner for OpenAI, NIM, and Local, a small executor with
Local fallback, a Hermes text-call adapter, and calendar/email summaries using local Gemma. Real Gmail briefs can now be
pushed to Telegram every day at 08:00 Pacific. Further workflows are added incrementally.

In Windows PowerShell, enter Ubuntu:

```powershell
wsl -d Ubuntu
```

For a fresh checkout, run the following in Ubuntu. This assumes the existing
Hermes-provided uv and managed Python 3.11.16 installation on this machine;
`--offline` prevents downloads.

```bash
cd /mnt/d/ai_agent_projects/hw3
~/.hermes/bin/uv venv --python 3.11.16 --offline .venv
```

To use the existing environment in an Ubuntu terminal:

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
python --version
command -v python
```

Expected: `Python 3.11.16` and
`/mnt/d/ai_agent_projects/hw3/.venv/bin/python`.
Activation affects the current shell; `deactivate` exits it without deleting
the environment. `.venv` is already ignored by Git.

In a VS Code window connected to WSL, install the Microsoft Python extension
in WSL if needed, then run **Python: Select Interpreter** and select
`/mnt/d/ai_agent_projects/hw3/.venv/bin/python`.

## Install and check the package

After activating the project environment as above, run these commands in Ubuntu:

```bash
~/.hermes/bin/uv sync --locked
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

`uv sync --locked` installs the project in editable mode and its development
requirements into `.venv`, using the versions recorded in `uv.lock`.
Editing files in `src/hybrid_assistant/` therefore takes effect without
reinstalling the package. After deliberately changing dependencies, run
`uv sync` to update the lockfile; use `--locked` for normal setup.

- `pyproject.toml`: package metadata, Python range, development dependencies,
  and test/lint settings.
- `src/hybrid_assistant/routing.py`: chooses a provider from trusted metadata.
- `src/hybrid_assistant/execution.py`: calls the planned providers and returns
  the actual provider, reply text, and whether a fallback was used.
- `src/hybrid_assistant/hermes.py`: sends one text request to an installed Hermes profile.
- `src/hybrid_assistant/runtime.py`: builds the shared provider registry from WSL home profiles.
- `src/hybrid_assistant/intent.py`: identifies task type, complexity and private-context needs from the current message.
- `src/hybrid_assistant/assistant.py`: handles chat, follow-ups and the latest-email summary through existing functions.
- `src/hybrid_assistant/conversation.py`: stores bounded recent dialogue, privacy state and the current email snapshot.
- `examples/assistant.py`: runs that unified entry from the WSL terminal.
- `src/hybrid_assistant/telegram.py`: polls the existing bot and authorizes the bound private-chat user before task handling.
- `examples/telegram_bot.py`: receives Telegram requests, calls the shared handler and replies through Hermes.
- `examples/identify_task.py`: previews task identification and execution routing without running a business task.
- `src/hybrid_assistant/memory.py`: extracts explicit preference edits with Local Gemma, validates them and saves the existing Hermes USER.md.
- `examples/remember.py`: a natural-language command for adding, changing or forgetting user preferences.
- `src/hybrid_assistant/calendar.py`: calendar data, Local summaries, and source-fact rendering.
- `src/hybrid_assistant/email.py`: local email summarization and source-header rendering.
- `src/hybrid_assistant/gmail.py`: read-only single/batch Gmail IMAP input and MIME decoding.
- `src/hybrid_assistant/messaging.py`: text delivery through the Hermes CLI.
- `examples/gmail_summary.py`: summarize INBOX emails; `--limit` selects a count, `--daily` selects all arrivals in the preceding 24 hours, `--subject` filters, and `--send` delivers to Telegram.
- `scripts/install_daily_briefing.ps1`: installs the Windows 08:00 trigger and a Hermes script job via the companion Python installer.
- `scripts/run_daily_briefing.ps1`: launches WSL and runs the Hermes job, reporting its result to Windows.
- `src/hybrid_assistant/briefing.py`: reusable ordered email summaries and combined daily briefing.
- `examples/calendar_reminder.py`: a runnable synthetic calendar event.
- `examples/calendar_briefing.py`: multiple synthetic events supplied out of order.
- `examples/calendar_from_file.py`: loads the editable synthetic `examples/data/calendar.json` and filters its target date.
- `examples/email_summary.py`: one synthetic email summarized by real local Gemma.
- `examples/daily_briefing.py`: the combined synthetic briefing with real local inference.
- `config/hermes/`: non-secret OpenAI, NIM, and Local profile templates.
- `tests/test_execution.py`: verifies execution with Python's built-in `Mock`.
- `tests/test_import.py`: checks that the installed package can be imported.
- `.env.example`: comments only; the package does not load `.env` or manage OAuth.
  Hermes owns authentication and its profile state.

The expected result is 452 passing tests. They cover routing, model execution,
email/calendar workflows, memory, task identification, Telegram delivery and
persistent multi-turn context, without live model or network calls.

## Handle a natural-language request

Run consecutive requests from the WSL terminal; `--new` starts a fresh conversation:

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
systemctl --user start hw3-ollama
python examples/assistant.py --new "用两句话解释 Python 列表和元组的区别。"
python examples/assistant.py "第二种适合什么情况？"
python examples/assistant.py "总结最新收到的一封邮件。"
```

The first commands answer a public question and its follow-up. The latest-email
command classifies the request, reads the latest INBOX message and
summarizes it with Local Gemma. Output shows the actual classifier, actual
execution provider and answer. Gmail credentials are loaded only for the email
branch; its reader and summary reuse the existing business modules.

Complex public questions use NIM; known-private inputs use `--private`, and
`--offline` keeps models local and prevents Gmail access. Only the current
permitted message is sent to the classifier. Unsupported tasks receive an
explanation; a specific-message request is not treated as the latest email.
This CLI does not receive or send Telegram messages; the Telegram entry below
uses the same handler. Both entries persist recent conversation context separately
under `~/.hermes/profiles/hw3-local/conversations/`. Public history can follow a
switch between GPT and NIM. Email follow-ups use the same saved email snapshot.
Once a conversation uses private data or Local execution, later turns stay Local
until `--new` (CLI) or `/new` (Telegram). Long-term USER.md preferences are preserved.
Explicit requests to remember, change or forget preferences now call the existing
Local memory updater from either entry. Replies show the actual saved changes.
Existing batch/daily/memory commands remain available. See [the context walkthrough](docs/conversation.md).

At the handler checkpoint, 383 offline tests and Ruff passed. Eight live scenarios passed, including actual
GPT and NIM answers, a real Gmail-to-Gemma summary, private chat, and requests
that stop before unsupported business execution. See [the handler walkthrough](docs/assistant.md).

## Telegram conversation entry

Start the receiver in a WSL terminal and keep it running:

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
systemctl --user start hw3-ollama
python examples/telegram_bot.py
```

Send a question or `总结最新一封邮件` to the already configured bot. The receiver
accepts only the bound user in that private chat, calls `handle_message()`, and
replies through the existing `hermes send` integration to the same fixed chat.
Use `/private your request` for Local-only classification and execution;
`/help` explains the available input, and `/new` clears recent dialogue and the
email snapshot. Restarting the receiver restores that chat's conversation.
You can also say `请记住：邮件摘要用中文` or explicitly ask to modify/forget a
preference. Local Gemma proposes the edit, Python validates and saves USER.md,
and the bot returns the actual changes. `/new` preserves long-term memory.

`Ctrl+C` stops the foreground receiver. `--once` replies to one authorized
message and exits for testing. No bot token or account setup is repeated. State
for polling is stored under `~/.hermes/profiles/hw3-local/telegram-inbound/`; the first start
skips old queued updates, and subsequent starts reuse the saved offset. The
offset is saved before handling to avoid automatic replay after an uncertain
send; an interrupted request may need to be sent again. Polling/delivery errors
stop the process with a concise error rather than silently retrying replies.
Two user-driven round trips passed: a GPT answer and a real Gmail-to-Gemma
summary were both delivered through Hermes. Both one-shot test receivers exited
cleanly; use the normal command above to keep receiving requests.
See [the Telegram code and usage walkthrough](docs/telegram-inbound.md).

## Task identification and route preview

From the activated WSL project environment:

```bash
python examples/identify_task.py "总结最新收到的一封邮件。"
python examples/identify_task.py "比较两种分布式任务队列方案，分析一致性、故障恢复和成本，给出迁移计划。"
```

GPT identifies these as an email summary and complex public reasoning; the
execution plans select Local and NIM respectively. This command prints the plan
only: it does not fetch mail, answer the question, update memory or send Telegram
messages. The unified entry above now handles chat and the latest-email summary; the Telegram receiver below now reuses that handler.
The supplied description may be sent to GPT. For private input, start Ollama
and use `--private`; `--offline` also keeps classification and execution local.

At the identification-only checkpoint, 351 offline tests and Ruff passed. Eleven live classification scenarios passed,
including eight GPT calls, two direct Gemma calls and an injected GPT failure
followed by real Gemma inference. These checks validate classification and route
planning, not business execution. See [the code walkthrough](docs/intent.md).

## Combined daily briefing

Run the complete synthetic example from a WSL terminal:

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
systemctl --user start hw3-ollama
python examples/daily_briefing.py
```

`build_daily_briefing(events, emails, providers)` accepts a list of calendar
events and a list of emails, returning one plain-text briefing. The example
selects September 8, 2026 in `America/Los_Angeles`: two of its three events pass
`select_events_for_date()`, while the next-day event is excluded. It also supplies
two emails. Selected calendar events are summarized together in one Local call;
each email gets a separate Local call in input order. This example therefore
makes three model calls; its `timezone` keyword uses the same zone as date selection. All sections are joined under `每日简报`, with original
calendar details and email headers retained alongside generated summaries.

`build_calendar_briefing()` reuses `summarize_calendar()` and the fact renderer.
The email loop reuses `summarize_email()` and `render_email_summary()`. A calendar
`ProviderError` displays `日程摘要暂不可用` and email processing continues. Each
email failure similarly preserves its sender/subject with `邮件摘要暂不可用`.
Missing Local registration (`KeyError`) and unexpected programming errors propagate.
Private content never falls back to a remote model.

An empty email list displays `暂无邮件`; a nonempty calendar still calls Local.
An empty calendar displays `暂无日程` while email processing proceeds normally.
If both lists are empty, no model call is needed. For a single email, pass `[email]`.

The corrected real-model check took about 4.9 seconds for the four selected
file-backed events and 7.2 seconds for the daily briefing. The calls used only
`hw3-local`. The calendar sample correctly described the 23:30 Los Angeles event;
the daily sample described the 3.5-hour gap between the 10:00–10:30 meeting and
14:00 discussion. These are synthetic sample checks, not a general accuracy guarantee.

Briefing generation and calendar date selection are implemented. The example
uses an explicit target date and timezone, then prints the result. Email selection
belongs to the caller; the real Gmail entry point and its scheduled delivery are
described below. This synthetic example remains useful without real accounts. To check the composition behavior without a model:

```bash
python -m pytest -q tests/test_briefing.py
```

## Calendar reminders and briefing

Run any calendar example in the activated WSL project environment with Ollama:

```bash
systemctl --user start hw3-ollama
python examples/calendar_reminder.py
python examples/calendar_briefing.py
```

Both examples now call real local Gemma through `build_calendar_briefing()`.
The first supplies one event; the second supplies two events out of order.
Each nonempty calendar gets one model-generated summary describing the schedule
and supported points to watch, shown alongside the original event details.
No calendar account is needed for these synthetic inputs.

The call chain is:

```text
CalendarEvent list -> build_calendar_briefing -> summarize_calendar
  -> plan_route(SENSITIVE, CALENDAR) -> execute_plan -> call_hermes
  -> hw3-local profile -> Ollama / Gemma
```

`CalendarEvent` holds `title`, timezone-aware `starts_at`, positive integer
`duration_minutes`, and `location`. `summarize_calendar()` orders the selected
events by actual start, serializes them as JSON (with explicit ISO timestamps),
and sends one prompt through the existing Local route. The optional keyword
`timezone` defaults to UTC; examples pass `America/Los_Angeles`. Before the call,
start times are converted to that zone and end times are computed from durations
on the UTC timeline, including daylight-saving boundaries. Original event objects
and their displayed source facts remain unchanged. Calendar text is treated
as data in the prompt; it does not supply routing metadata.

`render_calendar_reminder()` and `render_calendar_briefing()` remain formatting
helpers for source details. They preserve exact supplied timestamps, UTC offsets,
durations, and locations; they do not replace the model task. Model prose is shown
separately under `日程摘要（模型生成）`, and may still contain factual errors.
A failed Local call produces `日程摘要暂不可用` alongside the source details.
This does not silently substitute a successful AI summary or call a remote model.

Sorting compares UTC instants, including repeated wall times during daylight
saving changes, without mutating the input list. The caller selects which events
to include. An empty selection displays `暂无日程` without invoking a model.
Real calendar scheduling and delivery remain later steps; the email schedule is described below.

Run focused offline tests with:

```bash
python -m pytest -q tests/test_calendar.py
```

### Select events for a date

`select_events_for_date(events, target_date, timezone)` converts each start to
the supplied timezone and compares its date with `target_date`. It returns a new
list containing the original matching event objects in input order. Sorting and
rendering continue to use the existing calendar functions.

Given the event list, the daily example wires selection before generation:

```python
from datetime import date
from zoneinfo import ZoneInfo

from hybrid_assistant.calendar import select_events_for_date

target_date = date(2026, 9, 8)
timezone = ZoneInfo("America/Los_Angeles")
selected_events = select_events_for_date(events, target_date, timezone)
briefing = build_daily_briefing(selected_events, emails, providers, timezone=timezone)
```

Pass a `date` object and an explicit timezone object such as `ZoneInfo`; strings,
`datetime` targets, and an omitted/None timezone are not accepted. A caller that
wants today can use `datetime.now(timezone).date()` to choose the target date;
the selector itself never reads the clock.

For example, `2026-09-09 06:30 UTC` falls on September 8 in Los Angeles and is
included for that date. A start at local midnight is included; the following
midnight is excluded. Events starting the previous day are excluded even when
they continue past midnight. The original timestamps and display offsets are
preserved. Empty input or no matches returns `[]`.

The date-selection tests include different source offsets, midnight boundaries,
23-hour and 25-hour daylight-saving dates, and original object/order preservation.
Run them without Ollama or any model calls:

```bash
python -m pytest -q tests/test_calendar.py -k date_selection
```

### Test without a calendar account

Run an editable file-backed fixture without a calendar account or API credentials.
This example uses real local Gemma, so start Ollama first:

```bash
systemctl --user start hw3-ollama
python examples/calendar_from_file.py
```

`examples/data/calendar.json` contains seven synthetic events plus `target_date`
and `timezone`. The example reads JSON, converts each record into the existing
`CalendarEvent`, selects the target date, and calls `build_calendar_briefing()`
for one Local summary plus source details. The file path
is relative to the example script, so changing the working directory does not
change which fixture is read.

The default target is September 8, 2026 in Los Angeles. Four events appear in this
order: 当天零点事项, 团队会议, 项目讨论, 跨时区同步会议. The last event is stored as
September 9 at 06:30 UTC, which is September 8 at 23:30 in Los Angeles; its source
UTC timestamp is intentionally preserved in the output. The previous-day start
and both next-day events are excluded.

Edit the JSON to try other dates, timezones, or event values. September 9 selects
two events; September 10 selects none and prints `暂无日程`. This fixture tests
file input, conversion, selection, and real local summarization. It does not test third-party
calendar authentication or API connectivity.

## Single-email summary with local Gemma

Run this example in a WSL terminal. Keep the terminal open while using Ollama:

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
systemctl --user start hw3-ollama
python examples/email_summary.py
```

The example contains a synthetic email; it does not connect to a mailbox.
If WSL just started, allow the Ollama service a few seconds to initialize.
The first output line should be `provider=local, used_fallback=False`.

`Email` stores sender, subject, and body. `summarize_email(email, providers)`
assigns `Source.EMAIL` and `Privacy.SENSITIVE` inside the workflow, then reuses
`plan_route()` -> `execute_plan()` -> the existing Local Hermes callable.
The example registers only the `hw3-local` profile. If Local fails, the failure
propagates without trying a remote model.

`asdict()` turns the email dataclass into a dictionary; `json.dumps()` packages
its fields as quoted data, preserving newlines and quotes. The prompt asks for
a short Chinese summary while retaining key dates and quantities. Instructions
inside the email cannot change the metadata assigned by the Python workflow.
JSON packaging and a prompt are not a guarantee of correct model behavior.

`render_email_summary(email, result.text)` displays the original sender and
subject, followed by a separate `摘要（模型生成）` section. The generated prose is
not used to overwrite the source headers. The trusted provider mapping and
isolated Local profile remain the same integration boundary as before.

The recorded real Gemma check took 11.381 seconds and retained the fixture's
`2026-09-08 16:00 (UTC-07:00)` deadline, `1` PDF, `2` screenshots, and the request
to check that attachments open. Its session recorded `gemma4:e4b-it-qat`, the
loopback endpoint, one API call, and zero tool calls. These checks apply to that
synthetic response; the application does not yet have a general factual
validator for generated summaries, and later responses can vary.

Run the focused offline tests with:

```bash
python -m pytest -q tests/test_email.py
```

## Automatic routing

The assistant selects the provider automatically from the task context:

| Request | Primary | Fallback |
| --- | --- | --- |
| Ordinary public task | OpenAI OAuth | Local Gemma |
| Complex public reasoning | NVIDIA NIM | Local Gemma |
| Private content or offline mode | Local Gemma | None |

Both remote paths fall back directly to Local. There is no manual provider
selector or additional NIM -> OpenAI hop.

`RequestContext` carries source, privacy, complexity, and offline/cloud metadata.
`plan_route()` returns a `RoutePlan` with `primary`, ordered `fallbacks`, and a
reason code. It only plans the route; it does not call a model.

Email/calendar, sensitive content, unknown privacy/source, and an explicit
cloud prohibition stay local. Complexity defaults to `Complexity.NORMAL`;
`Complexity.COMPLEX` selects NIM only for public user input with cloud permitted.
The existing enum and boolean validation rejects invalid metadata.

The new `identify_task()` entry uses GPT to classify only the current permitted
user message, then passes the result through this existing routing policy.
Known-private or offline inputs use Local even for classification. The caller
controls source and disclosure permission; model labels cannot clear those
restrictions. Fetched email, calendar, private memory and related history are
never attached to GPT. See [task identification and its call chain](docs/intent.md).

```python
from hybrid_assistant.routing import (
    Complexity,
    Privacy,
    Provider,
    RequestContext,
    Source,
    plan_route,
)

plan = plan_route(
    RequestContext(
        privacy=Privacy.PUBLIC,
        source=Source.USER_INPUT,
        complexity=Complexity.COMPLEX,
    )
)
print(plan.primary.value)  # nim
assert plan.fallbacks == (Provider.LOCAL,)
```

Adding `offline=True` produces a Local-only plan. The executor follows the
plan's fallback only after a `ProviderError`. The execution rules are verified with Mock calls; the Hermes probe below also
connects an ordinary public request to the existing OpenAI OAuth setup.

Run the routing tests in the activated Ubuntu environment:

```bash
python -m pytest -q tests/test_routing.py
```

## Execution and fallback

`execute_plan(plan, prompt, providers)` calls the primary first and follows the
plan's fallback on `ProviderError`. Each provider function accepts a string and
returns a string. The result contains the actual `provider`, reply `text`, and
`used_fallback`. Primary success, including directly using Local for privacy or
offline mode, has `used_fallback=False`; a successful fallback has `True`.

The mapping is wired by trusted application code, not chosen by message text.
The executor expects a trusted plan produced by `plan_route()`; it does not
classify content or validate the real endpoint behind a registered function.
The Hermes probe below selects a named profile before starting the agent.

This runnable example uses `unittest.mock.Mock` to simulate a failure and a test
reply. There is no separate fake-model module and no model or network call:

```python
from unittest.mock import Mock

from hybrid_assistant.execution import ProviderError, execute_plan
from hybrid_assistant.routing import (
    Privacy,
    Provider,
    RequestContext,
    Source,
    plan_route,
)

plan = plan_route(RequestContext(privacy=Privacy.PUBLIC, source=Source.USER_INPUT))
remote_call = Mock(side_effect=ProviderError("Remote unavailable"))
local_call = Mock(return_value="Local reply")
result = execute_plan(
    plan, "Hello", {Provider.OPENAI: remote_call, Provider.LOCAL: local_call}
)

print(result.provider.value)  # local
print(result.text)  # Local reply
print(result.used_fallback)  # True
remote_call.assert_called_once_with("Hello")
local_call.assert_called_once_with("Hello")
```

Each planned provider is attempted once, stopping at the first success. There
are no retries of the same model or routes invented outside the plan.
`ProviderError` signals an expected model-call failure. The Hermes adapter
translates launch failures, timeouts, nonzero exits, and empty replies into this
exception; programming errors propagate immediately without fallback. The
executor starts each planned provider once; Hermes may retry internally within
that call.

Missing registrations raise `KeyError` immediately, including a missing primary
when Local is registered. Primary success needs no registered fallback. If the
last permitted call raises `ProviderError`, that same error is re-raised. A
Local-only request never tries a remote provider, even if Local fails or is
missing. `used_fallback` marks the fallback path, not a measured quality score.

Run the focused execution tests in the activated Ubuntu environment:

```bash
python -m pytest -q tests/test_execution.py
```

## Hermes integration and shared wiring (WSL)

All model-backed entry points use `create_providers()` from `hybrid_assistant.runtime`.
It binds the existing `call_hermes()` to each named profile and returns a provider
registry. Creation performs no model calls and reads no credentials; profiles
are checked only when their route is actually used. A local email summary can
therefore run without configured remote credentials.

All three runtime profiles now live together in the WSL user's home:

| Route | Active configuration | Authentication / model |
| --- | --- | --- |
| OpenAI | `~/.hermes/profiles/hw3-openai/config.yaml` | Hermes-owned OAuth / `gpt-5.6-sol` |
| NIM | `~/.hermes/profiles/hw3-nim/config.yaml` | Profile `.env` / Nemotron 3 Super |
| Local | `~/.hermes/profiles/hw3-local/config.yaml` | Local Ollama / `gemma4:e4b-it-qat` |

On this machine, `~` is `/home/fyp`. These are independent profiles under one
parent directory. OpenAI continues to use the existing root OAuth grant; NIM's
key is in `~/.hermes/profiles/hw3-nim/.env`. Hermes retains session records under
each profile even when memory injection is disabled. The project-local Local
and NIM profiles were migrated with their credentials and session data preserved.

The repository's `config/hermes/*.yaml` files are **installation templates**.
Hermes reads the installed `config.yaml` paths above. Edit an installed file to
change this machine's runtime configuration; update the corresponding template
when the intended project default changes.

For a fresh setup after installing Hermes and logging in through its root OAuth
profile, run from the project directory in WSL. Existing profile directories are
left in place; credentials are never copied from an empty template:

```bash
for provider_name in openai nim local; do
    profile_dir="$HOME/.hermes/profiles/hw3-$provider_name"
    if [ ! -d "$profile_dir" ]; then
        HERMES_HOME="$HOME/.hermes" ~/.local/bin/hermes --profile default profile create "hw3-$provider_name" --no-alias --no-skills &&
            install -m 600 "config/hermes/$provider_name.yaml" "$profile_dir/config.yaml"
    fi
done
```

Use the same registry for direct routed requests and business workflows:

```python
from hybrid_assistant.execution import execute_plan
from hybrid_assistant.routing import Privacy, RequestContext, Source, plan_route
from hybrid_assistant.runtime import create_providers

providers = create_providers()
context = RequestContext(privacy=Privacy.SENSITIVE, source=Source.USER_INPUT)
plan = plan_route(context)
result = execute_plan(plan, "Reply with exactly LOCAL_GEMMA_OK.", providers)
print(result.provider.value, result.text, result.used_fallback)
```

Expected: `local LOCAL_GEMMA_OK False`. `Privacy.PUBLIC` with the same source
selects OpenAI with Local fallback. Adding `offline=True` keeps the request local.
`Privacy.PUBLIC` + `Source.USER_INPUT` + `Complexity.COMPLEX` selects NIM with Local
fallback. The caller supplies trusted metadata; this function does not classify
arbitrary prompt text. Email workflows set their own private source metadata.

The call chain is:

```text
entry point -> create_providers() -> reusable provider registry
business workflow -> plan_route() -> execute_plan()
    -> selected registry callable -> call_hermes() -> Hermes -> model
```

`call_hermes(prompt, profile=Path(...))` starts the installed Hermes CLI through
Python's standard-library `subprocess.run()`. The prompt travels through stdin;
stdout becomes the reply. Known process failures become `ProviderError`, which
lets the executor follow the permitted fallback. Hermes owns authentication and
model communication. No project SDK, OAuth-token copying, or internal Hermes
imports are required.

All three templates disable default tools, coding auto-selection, Hermes provider fallback,
compression, titles, and background review. Local now loads the built-in USER.md
profile; OpenAI and NIM keep memory disabled. The adapter pins `HERMES_HOME`,
`--profile`, and the working directory before startup. It passes `--ignore-rules`
by default; the shared provider factory enables context loading only for Local. `HERMES_SAFE_MODE=1` disables
extensions while preserving profile config. In this installed Hermes version,
the CLI flag `--safe-mode` would also discard that config, so it is not used.
The child environment excludes inherited provider overrides; `~/.hermes/bin`
remains on PATH for the existing scanner.

Profile configuration and the installed runtime remain trusted inputs. Tests
cover configured routing and failures; they do not establish OS-level network
isolation. The 2026-09-08 review and profile migration are recorded in
[the review notes](docs/reviews/2026-09-08.md).

## Local Gemma runtime (WSL)

The selected model is [Gemma 4 E4B QAT](https://ollama.com/library/gemma4:e4b-it-qat),
using Ollama 0.33.3. The verified model ID is `ee6656371218`; its download is about
6.1 GB. QAT is quantization-aware training: this variant uses reduced-precision
weights to reduce memory needs. The default E4B tag is a larger download; use
the explicit `gemma4:e4b-it-qat` tag shown here.

Ollama is installed at `~/.local/opt/ollama-0.33.3`, with a command symlink at
`~/.local/bin/ollama`. Models are stored at `~/.ollama/models`, outside Git and
the project Python environment. These paths are inside the existing WSL distro
stored on the D drive. The installation used the official Linux archive in the
user directory because system installation required an interactive password.
See [Ollama's installation documentation](https://docs.ollama.com/linux).

The versioned [user service configuration](config/ollama/hw3-ollama.service)
keeps the server on `127.0.0.1:11434`, disables Ollama Cloud, and limits concurrent
loading to one model. [Ollama documents local-only mode here](https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features).
For a fresh setup after installing Ollama at `~/.local/bin/ollama`:

```bash
mkdir -p ~/.config/systemd/user
install -m 644 config/ollama/hw3-ollama.service ~/.config/systemd/user/hw3-ollama.service
systemctl --user daemon-reload
systemctl --user enable --now hw3-ollama
ollama pull gemma4:e4b-it-qat
```

For daily use, keep a WSL terminal or VS Code WSL window open:

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
systemctl --user start hw3-ollama
ollama list
```

The service may need a few seconds to initialize immediately after WSL starts.
To chat directly with Gemma, independently of the project router:

```bash
ollama run gemma4:e4b-it-qat --think=false
```

Use `/bye` to leave that chat. `ollama ps` shows loaded models; idle models
unload after Ollama's default five minutes. `ollama stop gemma4:e4b-it-qat`
unloads it immediately. `systemctl --user stop hw3-ollama` stops the server.
Systemd services alone do not keep WSL alive, so closing all WSL sessions can
stop the server and the next use will load it again.
[Microsoft's WSL systemd notes](https://learn.microsoft.com/en-us/windows/wsl/systemd).

Both the service and [Hermes local profile](config/hermes/local.yaml) use an
actual 65,536-token context. A 4K context worked directly in Ollama, but installed
Hermes rejected it because its minimum is 64,000 tokens. Gemma E4B supports up
to 128K; the selected 64K setting fits the measured hardware budget.
[Google model details](https://ai.google.dev/gemma/docs/core).
The profile disables thinking and caps replies at 256 tokens for short tests.

On this RTX 5060 Laptop GPU, the recorded 64K checks were:

| Check | Observed result |
| --- | --- |
| Raw model load | About 6.5 s after the initial setup run |
| Raw warm short reply | 0.155 s total; 7 output tokens, about 74 tokens/s during generation |
| Hermes private / offline calls | About 4.1 / 4.5 s; no remote callable invoked |
| Simulated remote outage -> real Local | About 8.4 s; `used_fallback=True` |
| Structured calendar extraction | Correct `10:00`, `30`, and `线上`; about 2.4 s |
| GPU usage | Ollama reports GPU execution and 65,536 context; total GPU use about 6.2 GiB including other usage |

These are small synthetic checks, not general performance or quality benchmarks.
The first-ever initialization was slower (about 63 s at 4K); first-use timings
can differ substantially from warm calls. A free-text calendar summary also
rewrote `10:00` inaccurately, while the structured extraction preserved it.
Email summaries preserve source headers and use explicit fact-preservation prompts; successful routing
does not establish summary accuracy. All inspected Hermes sessions used
`custom` / loopback, the Gemma model, and zero tools. The outage was injected
with `Mock`; the fallback answer came from real Gemma.

## NVIDIA NIM setup (WSL)

The [NIM template](config/hermes/nim.yaml) selects Hermes' built-in `nvidia`
provider and `nvidia/nemotron-3-super-120b-a12b`. Hermes supplies NVIDIA's
OpenAI-compatible base URL, `https://integrate.api.nvidia.com/v1`, and a
16,384-token output limit. The model enables reasoning by default; the short
Local profile's disabled thinking and 256-token limit are not copied here.
[Official hosted model and request example](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b).

No additional project SDK or provider class is needed. The existing chain is
`plan_route()` -> `execute_plan()` -> `call_hermes()` -> the selected Hermes
profile. `Provider.NIM` is our routing label; `nvidia` is Hermes' provider name.

The shared profile setup above creates `hw3-nim`; it is already configured on
this machine. `config/hermes/nim.env.example` documents the required variable
name only. To configure a new key, edit the installed profile's `.env` directly;
never copy the blank template over an existing credential file.

Open the [official model page](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b),
sign in, and use **Generate API Key** (called **Get API Key** in the
[quickstart](https://docs.api.nvidia.com/nim/docs/api-quickstart)). Put the key
only in the profile's local `.env`, replacing the empty value after
`NVIDIA_API_KEY=`. In a VS Code WSL terminal:

```bash
code ~/.hermes/profiles/hw3-nim/.env
```

Save that file. Do not put the key in a chat, a committed YAML file, or the
example template. Runtime credentials live outside the repository. Hermes reads
its own profile `.env`; the project does not load a root `.env`, and `call_hermes()`
does not forward API keys exported in the parent shell.

After saving the key, use the shared factory for a synthetic complex request:

```python
from hybrid_assistant.execution import execute_plan
from hybrid_assistant.routing import (
    Complexity,
    Privacy,
    RequestContext,
    Source,
    plan_route,
)
from hybrid_assistant.runtime import create_providers

providers = create_providers()
plan = plan_route(
    RequestContext(
        privacy=Privacy.PUBLIC,
        source=Source.USER_INPUT,
        complexity=Complexity.COMPLEX,
    )
)
result = execute_plan(
    plan,
    "Synthetic planning puzzle: A takes 2 hours; B takes 3 hours after A; "
    "C takes 4 hours after A. B and C can run in parallel. D takes 1 hour "
    "after both B and C. What is the minimum total time? Answer briefly.",
    providers,
)
print(result.provider.value, result.text, result.used_fallback)
```

The planned route is NIM -> Local; the correct puzzle answer is 7 hours.
A successful NIM call reports `nim` and `False`. If the NIM call raises
`ProviderError`, real local Gemma can answer and reports `local` and `True`;
that does not prove NIM succeeded. Keep a WSL session open for Ollama.

Authenticated NIM inference is verified: the planning puzzle returned
`7 hours` in 6.78 seconds, with `provider=nim` and `used_fallback=False`.
The completed session recorded `nvidia`,
`https://integrate.api.nvidia.com/v1`,
`nvidia/nemotron-3-super-120b-a12b`, one model API call, and zero tool calls.
This is a synthetic connection check, not a general reasoning benchmark.

The earlier missing-key check passed through the real `hw3-nim` profile and
fell back to real Gemma (`NIM_MISSING_KEY_LOCAL_OK`, `used_fallback=True`).
The local session recorded the Gemma model and zero tools. Router, executor,
adapter, and dependencies required no changes for NIM; the existing 169-test
suite and Ruff checks passed at configuration setup.

The adapter keeps its existing 60-second Hermes run budget and 90-second
process timeout. Long reasoning calls can still time out and follow the
planned Local fallback. Keep the profile key in its home-directory `.env`.

## Real Gmail and Telegram connection

Calendar work is paused while connecting Gmail and Telegram. Gmail uses an
application password over IMAP/TLS. The reader opens INBOX read-only and fetches
selected messages using BODY.PEEK[], preserving read flags. One IMAP connection
reads at most `--limit N` messages in descending UID order (default 1). An optional
subject filter narrows the matches before selecting N. This is INBOX arrival order,
not the sender's Date header; fewer than N matches returns all available matches.
Existing Local Gemma summarization is reused; optional delivery uses `hermes send`
with the private profile's Telegram configuration. No project runtime dependency
is needed; Hermes' own environment requires python-telegram-bot==22.8, matching
the installed Hermes version. See the setup guide for the installation command.

See [the setup and test steps](docs/gmail-telegram.md). Fill the new Gmail account's
address and application password in `~/.hermes/profiles/hw3-local/gmail.json`.
Telegram settings remain in that profile's `.env`. Repository templates contain
empty values only; active credentials stay in WSL home.

```bash
python examples/gmail_summary.py
# Preview the latest three emails, with a separate Local model call for each:
python examples/gmail_summary.py --limit 3
# Deliver their combined briefing to the configured Telegram chat:
python examples/gmail_summary.py --limit 3 --send
# Select up to three matching emails:
python examples/gmail_summary.py --subject "课程通知" --limit 3 --send
```

Batch mode (`--limit > 1`) reuses `build_email_briefing()`, which also serves
the daily briefing. Each expected model failure retains that email's headers and
an unavailable notice while other emails continue. Single mode retains its
fail-on-model-error behavior. Mail-reading/decoding failures stop before delivery.
Real Gmail login, latest-message retrieval and one Local Gemma summary passed
on 2026-09-08 in about 14.4 seconds (10.8 seconds for the Hermes model call).
The 452 offline tests cover parsing, selection, routing, task identification, memory and delivery behavior.
A real three-email preview passed in 17.46 seconds with three hw3-local calls;
no batch Telegram message was sent during that check.
Telegram bot authentication and private-chat binding passed. A real Gmail ->
Local Gemma -> Telegram run completed in about 10 seconds with Hermes exit 0;
the user confirmed receipt and successfully tested the commands. The missing Telegram library
was installed only in Hermes' own environment, preserving existing package versions.

## Daily Gmail briefing at 08:00 Pacific

The daily job reports every message still in INBOX whose Gmail INTERNALDATE is
within `[run time - 24 hours, run time)`. It does not use the sender's Date header
or impose a message-count limit. Read and unread messages are included; archived,
Spam and Trash messages are outside this INBOX scope. Each selected email gets
its own Local Gemma summary, then the combined report goes to the bound Telegram
chat. Empty windows send an explicit no-new-email report.

A live six-email daily preview passed in 33.19 seconds using six Local calls.
The installed Windows task then completed a real six-email Telegram delivery
in about 45 seconds (Windows result 0, Hermes status ok).

Preview or send immediately from the activated WSL project environment:

```bash
systemctl --user start hw3-ollama
python examples/gmail_summary.py --daily
python examples/gmail_summary.py --daily --send
```

Install or update the scheduled task from **Windows PowerShell**:

```powershell
cd D:\ai_agent_projects\hw3
.\scripts\install_daily_briefing.ps1
Get-ScheduledTaskInfo -TaskName "HW3 Daily Email Briefing"
```

The installer targets this machine's Ubuntu/fyp WSL environment and expects the
Windows time zone to be Pacific Standard Time. An offset-free daily Windows
trigger follows Pacific daylight-saving changes. Windows wakes/starts WSL and
runs the Hermes script job; VS Code and the Hermes gateway need not stay open.
Hermes' own job stays paused between runs, because Windows owns the schedule.
The runner enables it, runs it synchronously, and pauses it in `finally`.

The task uses the logged-in Windows account. The computer must be on, or in a
sleep state that allows wake timers, with network access; it cannot run while
powered off or signed out. A missed run starts when available and covers the
24 hours before its actual start. It does not backfill older missed days.
The report is sent after reading and model generation complete, so 08:00 is the
start time. See [the operating guide](docs/gmail-telegram.md#5-每天早上-0800-自动推送)
for manual triggering, pausing, failure behavior and the installed file locations.

## Persistent email-summary preferences

Hermes now loads `~/.hermes/profiles/hw3-local/memories/USER.md` at the start
of each Local call. The installed preference asks for Chinese summaries with
actions first and deadlines next, using two labeled lines. Email examples and
the scheduled daily job automatically reuse it through `create_providers()`.

View/edit that file in WSL with:

```bash
code ~/.hermes/profiles/hw3-local/memories/USER.md
python examples/email_summary.py
```

Explicit natural-language updates are now available in WSL:

```bash
python examples/remember.py "请记住：邮件摘要用中文，先列行动，再列截止时间。"
python examples/remember.py "修改邮件摘要偏好：先列截止时间，再列行动。"
```

Each command asks Local Gemma for structured add/replace/remove edits. Python
validates the full proposal, checks that the file has not changed during inference,
and saves it atomically in the existing Hermes USER.md format. The command displays
the actual diff. A replace edits only the matched text fragment, preserving other
parts of the entry. Invalid or ambiguous proposals are rejected before writing.
All model tools stay disabled. Regular email summaries read the resulting profile;
OpenAI/NIM calls do not load it. Telegram and `examples/assistant.py` now dispatch
explicit memory-update requests to the same updater. Classification sees only the
current permitted message; extraction always uses Local with the current USER.md.
Recent chat and email snapshots are not automatically copied into long-term memory.
`remember.py` and chat replies share the same actual-change renderer. A plain request
to rewrite the current answer remains a follow-up, not a preference update.
No new database or runtime dependency is added. See [the memory guide](docs/memory.md) for the call chain,
configuration, file lifecycle and real cross-process verification.

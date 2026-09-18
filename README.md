# Personal Assistant with Hybrid LLM Architecture

A personal AI assistant built on Hermes Agent, with automatic OpenAI / NVIDIA NIM / Local Gemma routing, Gmail summaries, Telegram conversations and persistent preferences.

The project owns routing, workflows and conversation state. Hermes owns model execution, authentication and message delivery. Application code runs in **WSL Ubuntu with Python 3.11**; the project has no third-party runtime dependencies.

## Start using it

The existing machine already has Hermes profiles and account credentials. After updating an existing checkout to the current source layout, run `~/.hermes/bin/uv sync --locked` once in WSL to refresh the editable installation and command. From a **WSL terminal**:

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
systemctl --user start hw3-ollama
hybrid-assistant --help
hybrid-assistant chat --new "用两句话解释 Python 列表和元组的区别。"
hybrid-assistant chat "第二种适合什么情况？"
```

To receive messages from the configured Telegram private chat:

```bash
hybrid-assistant telegram
```

Keep that process running; Ctrl+C stops it. `hw3-ollama` is the Ollama service name; `gemma4:e4b-it-qat` is the model. Model calls start on demand. The daily briefing uses a separate scheduled job.

For a new checkout or machine, follow [setup](docs/setup.md), then [Gmail and Telegram configuration](docs/gmail-telegram.md).

## Commands and implemented features

| Command | Behavior |
| --- | --- |
| `chat "message"` | Chat, follow-ups, latest Gmail summary and explicit preference updates |
| `telegram` | Receive and reply to the configured user's private chat |
| `gmail` | Summarize the latest INBOX email locally |
| `gmail --limit 3` | Summarize up to three emails; `--subject "text"` filters first |
| `gmail --daily` | Summarize all INBOX arrivals in the preceding 24 hours |
| `memory "request"` | Add, change or remove a persistent preference with Local Gemma |
| `calendar config/calendar.example.json` | Summarize selected events from a local JSON file |

Prefix each command with `hybrid-assistant`. From the repository root, `python src/main.py` provides the same subcommands. Use a subcommand's `--help` for its options. Gmail previews by default; `--send` delivers to Telegram. `--quiet` requires `--send` and hides summary content from command output.

Examples:

```bash
hybrid-assistant chat "总结最新一封邮件。"
hybrid-assistant chat "这封邮件要求我做什么？"
hybrid-assistant chat --private "请根据我的偏好解释这个概念。"
hybrid-assistant gmail --subject "课程通知" --limit 3
hybrid-assistant calendar config/calendar.example.json --date 2026-09-08 --timezone America/Los_Angeles
```

The `memory` command and explicit chat memory requests **change the real USER.md** and show the committed diff. Ordinary chat and emails are not automatically saved as preferences.

## Routing and privacy

| Input | Classification | Execution |
| --- | --- | --- |
| Permitted public message | OpenAI | OpenAI for normal work; NIM for complex work |
| Known private / offline message | Local | Local |
| Fetched email or calendar data | Never sent to the public classifier | Local |
| Remote model failure | Existing permitted fallback | Local, with no further remote fallback |

The classifier receives only the current permitted message. It cannot loosen caller privacy restrictions. New conversations default to public input: use `chat --private` or Telegram `/private` for private text.

CLI and Telegram persist separate recent conversations. Public history can follow a model switch between OpenAI and NIM. An email follow-up uses the saved same-email snapshot. Known private requests and actual Local execution lock the conversation to Local, even if processing fails. Later turns stay Local until `chat --new` or Telegram `/new`; these resets preserve long-term preferences.

## Repository structure

```text
src/
  main.py               # python src/main.py; shares the hybrid-assistant CLI
  cli/                  # chat, telegram, gmail, memory, calendar commands
  app/                  # handler, intent, conversation and runtime wiring
  core/                 # deterministic routing and provider execution
  features/             # email, calendar, briefing and memory workflows
  adapters/             # Hermes, Gmail and Telegram integration
config/                 # non-secret examples and installation templates
scripts/                # Windows / Hermes daily scheduling installers and runner
tests/                  # local-only offline tests; not included in GitHub checkouts
docs/                   # setup, architecture and feature guides
examples/gmail_summary.py # compatibility entry for an already installed daily job
```

The five packages live directly under `src/`, without an outer `hybrid_assistant` package. They are installed together and exposed through `hybrid-assistant`. The remaining `examples/gmail_summary.py` forwards to the Gmail command because the existing external launcher still refers to that path. New schedule installations use the installed command. Hardcoded demonstration scripts and the standalone intent-preview command were removed; their reusable workflows remain, with relevant automated tests kept locally.

## Current boundaries

- Timed calendar alerts are still missing. The calendar command selects and summarizes events; it does not schedule or send reminders.
- Chat supports the latest email. Subject/batch/daily selection is available through the Gmail command.
- Daily reports and chat context remain separate. A pushed daily report is not automatically available for follow-up questions.
- The Telegram receiver runs in the foreground; background service operation has not been added.
- An 08:00 America/Los_Angeles schedule is installed. Check its actual enabled state before expecting delivery; the review observed the Windows task disabled and left it unchanged.
- Generated classifications and summaries can be wrong. Tests verify routing, state and failure behavior, not arbitrary model factual accuracy.

## Verify

In the activated WSL project environment, including a fresh GitHub checkout:

```bash
python -m ruff check .
python -m ruff format --check .
~/.hermes/bin/uv lock --check
```

The `tests/` directory is kept locally and excluded from Git; GitHub checkouts do not include the test suite. Maintainers with the local tests can additionally run `python -m pytest -q`. The automated suite uses injected providers and transports; it does not require Telegram input or send real messages. Historical live checks are recorded in `Task.md`; current review results belong in the review report.

## Documentation

- [Architecture and module responsibilities](docs/architecture.md)
- [Environment and model setup](docs/setup.md)
- [Chat workflow](docs/assistant.md) and [task classification](docs/intent.md)
- [Conversation state](docs/conversation.md) and [persistent memory](docs/memory.md)
- [Telegram receiver](docs/telegram-inbound.md)
- [Gmail, Telegram delivery and the daily schedule](docs/gmail-telegram.md)
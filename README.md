# Personal Assistant with Hybrid LLM Architecture

A personal AI assistant built on Hermes Agent, with GPT by default and Local Gemma for explicit privacy/offline requests or provider failures, Gmail summaries, Google Calendar and local reminders, Telegram conversations and persistent preferences.

The project owns routing, workflows and conversation state. Hermes owns model execution, model authentication and message delivery. Application code runs in **WSL Ubuntu with Python 3.11**; Google Calendar uses Google's official Python client and OAuth libraries.

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

For a new machine, install Hermes separately, create the project environment with Python 3.11 and run `uv sync --locked`. Configure the `hw3-openai`, `hw3-nim` and `hw3-local` Hermes profiles under `~/.hermes/profiles/`, using the non-secret templates in `config/hermes/`. Gmail and Telegram credentials belong in the Local profile, following `config/gmail.example.json` and `config/telegram.env.example`; keep credentials outside the checkout. Google Calendar uses a separate desktop OAuth flow described below; Gmail continues to use IMAP.

## Commands and implemented features

| Command | Behavior |
| --- | --- |
| `chat "message"` | Contextual chat, Gmail queries, calendar operations and preference updates |
| `telegram` | Receive and reply to the configured user's private chat |
| `gmail` | Summarize the latest INBOX email using GPT with Local fallback |
| `gmail --limit 3` | Summarize up to three emails; `--subject "text"` filters first |
| `gmail --daily` | Summarize all INBOX arrivals in the preceding 24 hours |
| `calendar reminders` | Sync the configured calendar and preview due reminders |
| `calendar reminders --send` | Send one due batch to the bound Telegram chat |
| `calendar reminders --send --watch` | Keep checking every 30 seconds in the foreground |
| `calendar reminders --status` | Inspect reminder delivery status counts |
| `memory "request"` | Add, change or remove a persistent preference with Local Gemma |
| `calendar config/calendar.example.json` | Summarize selected events from a local JSON file |

Prefix each command with `hybrid-assistant`. From the repository root, `python src/main.py` provides the same subcommands. Use a subcommand's `--help` for its options. Gmail previews by default; `--send` delivers to Telegram. `--quiet` requires `--send` and hides summary content from command output.

Examples:

```bash
hybrid-assistant chat "总结上周主题包含面试的邮件，最多3封。"
hybrid-assistant chat "第二封要求我做什么？"
hybrid-assistant chat "那改成昨天的。"
hybrid-assistant chat --private "请根据我的偏好解释这个概念。"
hybrid-assistant chat "请记住邮件摘要用中文，并总结最新一封主题含周报的邮件。"
hybrid-assistant gmail --subject "课程通知" --limit 3
hybrid-assistant chat "明天下午三点提醒我交报告。"
hybrid-assistant chat "改到同一天下午四点。"
hybrid-assistant chat "提前半小时提醒，日程时间不变。"
hybrid-assistant chat "明天有哪些日程？"
hybrid-assistant calendar config/calendar.example.json --date 2026-09-08 --timezone America/Los_Angeles
```

The `memory` command and recognized long-term preferences in chat **change the real USER.md** and show the committed diff. Request understanding recognizes clear preferences such as “I usually prefer short explanations,” without requiring a fixed “remember this” phrase. Request understanding is instructed to exclude one-off answer instructions, ordinary biographical details and email contents; model mistakes can still cause an unnecessary preference update.

## Routing and privacy

| Input | Request understanding | Answer / optional memory step |
| --- | --- | --- |
| Default conversation, email or calendar data | GPT | GPT |
| Explicit /private, --private, or cloud restriction | Local | Local |
| Offline request | Local | Local; remote data retrieval disabled |
| GPT connection/provider failure | Local fallback | Local for the remaining request; later requests try GPT again |

Every request receives the bounded conversation context. Email/calendar data does not itself force Local, and complexity no longer automatically selects NIM. The NIM adapter remains available but is outside the default route. Classifiers never load profile files implicitly. Answer providers read saved user preferences; model output cannot loosen explicit privacy restrictions.

CLI and Telegram keep separate recent conversations. Explicit private requests lock their conversation to Local until chat --new or Telegram /new. Availability fallback does not set this lock. Older conversation files preserve their previous privacy lock during migration; start a new conversation to use the new default. Resetting a conversation preserves saved events and long-term preferences.

Each conversation retains its latest email query and numbered results. Calendar context keeps up to ten known records, updating individual IDs/versions after a mutation, alongside the last operation receipt. A new calendar query replaces this working set, including an empty query. These are contextual snapshots; writes still verify the current source version.

Chat uses three capability labels: `chat`, `email` and `calendar`. An independent optional `memory_request` carries the current user's clearly expressed long-term preference or edit, so one message can update memory and still ask a question or query mail. Memory uses one extraction call through the selected route plus deterministic patch validation; there is no separate semantic-equivalence check, and limited wording-only updates are acceptable. The handler commits memory first, then answers with the updated preferences. It reports the actual memory outcome even if the query or answer fails; a memory failure does not cancel the remaining request. Email scope is structured data, not a new task label for every phrase. Queries support subject text, paired received-time bounds and a count (default 5, maximum 10). Dates use America/Los_Angeles with an inclusive start and exclusive end. Results follow descending INBOX UID order; one extra matching UID (and received time when filtered) is checked without fetching its body, so the reply can disclose incomplete results. The shared history remains at most 6 exchanges / 12,000 characters; all saved email bodies share a 16,000-character budget including truncation notices. Existing single-email conversation files migrate on load and are written in the new versioned format on the next save.

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
examples/gmail_summary.py # compatibility entry for an already installed daily job
```

The five packages live directly under `src/`, without an outer `hybrid_assistant` package. They are installed together and exposed through `hybrid-assistant`. The remaining `examples/gmail_summary.py` forwards to the Gmail command because the existing external launcher still refers to that path. New schedule installations use the installed command. Hardcoded demonstration scripts and the standalone intent-preview command were removed; their reusable workflows remain, with relevant automated tests kept locally.

## Current boundaries

- Calendar operations use the bound Google calendar, or local SQLite before binding. Single timed events and standalone reminders are supported; recurring/all-day events and invitations are not.
- Reminders require the foreground checking command to be running. Late reminders are eligible for up to 15 minutes; older ones expire. Confirmed sends are not repeated, and uncertain outcomes require manual inspection. This is not a guarantee of exactly-once delivery.
- Chat email queries support subject text, received dates and up to 10 results. Sender filters, semantic body search and larger chat result sets need clarification or a narrower request; natural-language parsing can still be wrong, so check the displayed query scope.
- The standalone Gmail command retains its single-email, batch and daily workflows, including per-email summaries. Chat uses a shared answer over its bounded result set.
- Daily reports and chat context remain separate. A pushed daily report is not automatically available for follow-up questions.
- The Telegram receiver runs in the foreground; background service operation has not been added.
- An 08:00 America/Los_Angeles schedule is installed. Check its actual enabled state before expecting delivery; the review observed the Windows task disabled and left it unchanged.
- Generated classifications, query ranges and answers can be wrong. Tests verify routing, state and failure behavior, not arbitrary model factual accuracy.

## Verify

In the activated WSL project environment, including a fresh GitHub checkout:

```bash
python -m ruff check .
python -m ruff format --check .
~/.hermes/bin/uv lock --check
```

The automated tests and internal working documents stay local and are excluded from publication. Maintainers with the local suite can run `python -m pytest -q`; these tests use temporary data and injected transports, without sending real messages.

## Google Calendar and reminders

Before binding an account, chat uses the local SQLite calendar at `~/.hermes/profiles/hw3-local/calendar.sqlite3`. After binding, Google Calendar becomes the source for chat and reminders. Existing local events are not automatically uploaded, and a Google error never falls back to a separate local calendar.

Create a Google Cloud project, enable **Google Calendar API**, configure Google Auth Platform, and create a **Desktop app** OAuth client. If the OAuth app is in Testing, add your own Google account as a test user. Download the client JSON outside the checkout. Follow [Google's Python setup guide](https://developers.google.com/workspace/calendar/api/quickstart/python).

In an activated **WSL terminal**, authorize and create a dedicated calendar:

```bash
hybrid-assistant calendar google auth --client-secrets /mnt/c/Users/YOUR_USER/Downloads/YOUR_CLIENT.json
# Open the printed URL in the browser on this computer and complete Google consent.
hybrid-assistant calendar google connect --name "AI 助手"
hybrid-assistant calendar google status
```

The default OAuth scope is `calendar.app.created`: create secondary calendars and manage their events. To bind a calendar you already own, use `auth --existing --client-secrets ...`, then `connect --calendar-id YOUR_CALENDAR_ID`; this requests owned-event access plus read-only calendar metadata. Connection commands do not overwrite an existing binding or create duplicate calendars on retry. If creation has an uncertain result, inspect Google first and bind its actual ID.

The browser callback listens only on loopback port 8765 for up to five minutes; `auth --port 8766` can select another port. OAuth credentials and configuration are stored privately under `~/.hermes/profiles/hw3-local/google-calendar/`. Expired/revoked authorization produces a clear error; rerun `auth` to reauthorize the same account with the same scope option. External OAuth apps left in Testing may have refresh tokens expire after seven days; see [Google's token expiration rules](https://developers.google.com/identity/protocols/oauth2#expiration).

Chat and Telegram support structured `query`, `create`, `update` and `cancel`. Dates use America/Los_Angeles by default; explicitly requested IANA timezones are supported. Queries filter event start times, include the lower bound, exclude the upper bound, and return up to 10 records with optional literal title matching.

```bash
hybrid-assistant chat --private --new "明天下午三点提醒我交报告。"
hybrid-assistant chat "改到同一天下午四点，提前半小时提醒。"
hybrid-assistant chat "取消刚才的交报告日程。"
hybrid-assistant calendar google query --from 2030-01-02T00:00:00-08:00 --until 2030-01-03T00:00:00-08:00
```

The Google query command reads directly without a model; replace its example dates with the range to inspect. Updates/cancellations require a known source-bound event ID and version. The adapter checks Google's ETag both on reading and through `If-Match` on writing. Requery after a conflict. It patches only requested fields and preserves unrelated event data. New events use private visibility; this controls calendar sharing, separately from model routing. `/new` clears conversation snapshots while retaining saved events and preferences.

Meetings need an explicit duration. A standalone reminder uses duration zero inside the assistant; Google represents it as one minute marked free, with a private marker preserving the reminder meaning. One explicit popup reminder is also used as the Telegram reminder lead. Google's default calendar notifications are not automatically mirrored to Telegram. Recurring/all-day/special events and multiple/email reminder settings are not handled; queries disclose omitted records. Events with attendees can be read if otherwise supported, but this version does not modify/cancel them or send invitations.

To send reminders, keep a separate foreground command running:

```bash
hybrid-assistant calendar reminders
hybrid-assistant calendar reminders --send
hybrid-assistant calendar reminders --send --watch
hybrid-assistant calendar reminders --status
```

Preview refreshes Google's local reminder cache but sends nothing. Sending checks Google first, reconciles edits/cancellations, then rereads each due event immediately before claiming it. Unsupported records are reported and do not block other supported reminders. Sync failures prevent sending from stale data. External edits can still race after the final check; Google and Telegram do not share an atomic transaction.

The SQLite file is a per-calendar delivery ledger, not an independent editable copy. The checker covers the maximum 28-day reminder lead, processes at most 10 due reminders per batch, and accepts reminders up to 15 minutes late. It records attempts before sending, preserves sent/uncertain states across metadata changes, and never automatically retries uncertain deliveries. Delivery still requires WSL and the checking process to remain running; no background service is installed.

The request-understanding model receives each known event's start, end, duration and other fields. For a create/update it computes and returns the complete proposed event, including starts_at, ends_at and duration_minutes. Python checks that all fields are valid and that end minus start equals duration; it rejects missing or inconsistent proposals rather than calculating a replacement. It verifies the target/version, writes actual changed fields and renders the result without another model call. Reminder checking and delivery require no model. GPT handles these requests by default; --private selects Local. --offline blocks Google access and never writes to an alternative calendar.

`--store PATH` on the reminders command explicitly selects a local database for isolated use. The older `calendar config/calendar.example.json` entry remains a file briefing. Credentials, calendar data, internal docs and tests stay local.

# kettle

English | [简体中文](README.zh-CN.md)

kettle watches for "has X happened yet?" questions. At the times you configure, it
researches each one with an AI model that can search the web and read pages (Claude Code,
or the Anthropic, OpenAI or Gemini API), and when the answer turns into "yes" it pushes a
summary with sources to your iPhone via [Bark](https://github.com/Finb/Bark).

You don't have to write the monitoring rules yourself: describe what you're waiting for
in plain words, and the AI researches the current state, finds the authoritative sources,
writes precise resolution criteria, and starts monitoring. If it has already happened,
you're told right away instead.

Typical uses: a firmware getting jailbreak support again, a product opening pre-orders
in your region, a library shipping a feature, an official announcement being published.

## Requirements

- Linux with systemd (user units). The CLI also runs on macOS, but scheduling is up to you;
  Windows is not supported (file locking uses `fcntl`).
- Python 3.11+. Standard library only, nothing to install.
- One research engine (see [Engines](#engines)): [Claude Code](https://code.claude.com)
  installed and logged in (the default), or an Anthropic / OpenAI / Gemini API key.
- The [Bark](https://github.com/Finb/Bark) app on iOS, for push notifications.

## Setup

```sh
cp config.example.toml config.toml   # fill in bark_key; set [server] host/token for remote access
python -m kettle test-notify         # check that pushes arrive
./install.sh                         # install systemd user units: probe timer + web service
```

`install.sh` fills the `@KETTLE_DIR@` / `@PYTHON@` placeholders in `systemd/` with the
current directory and the path of `python3`. To keep running after you log out, run
`loginctl enable-linger` once.

API keys go in `.env` (gitignored), one per line, only for the engines you use:

```sh
cat > .env <<'KEYS'
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
KEYS
chmod 600 .env
```

## Engines

Probes and monitor setup each pick an engine in `config.toml` (`[probe]` and `[analyze]`;
`[analyze]` inherits anything it leaves out from `[probe]`), so you can e.g. set up
monitors with a stronger model and run daily probes with a cheaper one.

| `engine` | How it researches | Credentials |
|---|---|---|
| `claude-code` (default) | headless `claude -p` with WebSearch / WebFetch | Claude Code login, or `ANTHROPIC_API_KEY` |
| `anthropic` | Messages API + web search / web fetch server tools | `ANTHROPIC_API_KEY` |
| `openai` | Responses API + `web_search` | `OPENAI_API_KEY` |
| `gemini` | `generateContent` + Google Search grounding + URL context | `GEMINI_API_KEY` |

- `claude-code` uses your Claude subscription unless `ANTHROPIC_API_KEY` is in `.env`;
  the key is passed only to the `claude` child process. Don't put it in your global shell
  environment: that would switch your interactive Claude Code to API billing too. Max and
  Team plans include [monthly API credits](https://support.claude.com/en/articles/17154008-monthly-api-credits-for-max-and-team-plans)
  that can pay for API usage.
- The API engines need no CLI and are usually much faster (seconds instead of minutes).
  The `anthropic` engine fetches pages with the cache bypassed, so probes see fresh content.
- Being able to read a specific page matters: good criteria say "fetch this URL and check
  X". Search-only answers are more likely to miss fresh changes. The prompts were tuned on
  Claude; check the first few results when switching to another provider.

## Schedule

```toml
[schedule]
times = ["09:30", "21:30"]   # local time, as many per day as you like
```

At each time, every watching question gets probed once. kettle decides per question
("not probed since the latest slot"), so missed slots are caught up after the machine was
off or asleep, a restart mid-run continues where it stopped, and several drivers never
probe the same question twice. Two drivers are available, and using both is safe:

- `kettle serve` runs a built-in scheduler (checks every minute).
- `kettle run` probes whatever is due and exits. The systemd timer calls it every 15
  minutes; cron works the same way.

`times = []` turns scheduled probing off. Schedule changes apply without a restart.

## Cost

Every watched question is researched once per scheduled time, and setting up a monitor
runs a longer research session. With Claude Code on a subscription this counts against
your plan's usage limits; API engines bill per token plus the provider's search fees.
Model, turn limits and timeout are configurable per task in `config.toml`.

## Usage

```sh
python -m kettle analyze "what to watch for"            # AI researches it and starts monitoring
python -m kettle list                                   # questions and their status
python -m kettle add "question" --criteria "what counts" # add one manually
python -m kettle probe <id> [--no-notify]               # probe one question now
python -m kettle reset <id>                             # watch a resolved question again
python -m kettle remove <id>                            # delete a question
python -m kettle run [--all]                            # probe due questions (--all: every watching one now)
python -m kettle serve                                  # HTTP API + web UI (used by the web service)
```

When a probe concludes "resolved", kettle pushes the summary and sources, marks the
question `resolved`, and stops probing it. Otherwise it stays silent. After 3 consecutive
probe failures you get a warning push. `--no-notify` probes without pushing and without
marking the question resolved.

See `questions.example.toml` for the question format. `questions.toml` itself is created
and rewritten by kettle.

## Web UI / API

After `python -m kettle serve`, open `http://<host>:<port>/` (default port 8730). The page
lets you add monitors, follow running jobs, probe, reset, edit criteria, delete, and
browse probe history. It works on phones and supports dark mode.

`/api/*` requires `Authorization: Bearer <token>` (the token lives in `[server]` in
`config.toml`). Analysis and probes take minutes, so these endpoints return a job right
away; poll the job for the result.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/analyze` | `{"intent": "...", "notify": true}` → research and start monitoring; returns a job |
| `GET` | `/api/jobs` / `/api/jobs/{id}` | recent background jobs / one job's status and result |
| `GET` | `/api/questions` | questions with status and latest result |
| `POST` | `/api/questions` | add manually: `{"question", "criteria", "id"?}` |
| `PATCH` | `/api/questions/{id}` | edit `question` / `criteria` |
| `DELETE` | `/api/questions/{id}` | delete (probe history is kept) |
| `POST` | `/api/questions/{id}/probe` | probe now; returns a job |
| `POST` | `/api/questions/{id}/reset` | watch again |
| `GET` | `/api/questions/{id}/history?limit=50` | probe history |
| `GET` | `/api/schedule` | probe times, next run, what is being probed now |

```sh
curl -X POST http://host:8730/api/analyze \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"intent": "When does the Switch 2 launch in China"}'
```

### iPhone Shortcut

Submit a monitor by voice or from the share sheet. In the Shortcuts app, create a new
shortcut with these actions:

1. **Ask for Input**: type Text, prompt `What should I watch for?`
2. **Get Contents of URL**: `http://<your host>:8730/api/analyze`. Under "Show More", set:
   - Method: `POST`
   - Headers: `Authorization` = `Bearer <token>`
   - Request Body: JSON, one Text field `intent` = *Provided Input*
3. **Show Notification**: `Submitted. You'll get a push when the analysis is done.`

Name it e.g. "Watch" and say "Hey Siri, Watch". To submit selected text or a link from
other apps, enable "Show in Share Sheet" (Text, URLs) and use *Shortcut Input* for
`intent`, falling back to Ask for Input when it is empty. Add **Show Result** after step 2
to see the server's response while debugging.

### Security

- The server speaks plain HTTP, so the token travels in clear text. Listen on a private
  network only, or put it behind a reverse proxy / tunnel that provides HTTPS before
  exposing it to the internet.
- A token is mandatory when `host` is not a loopback address. Generate a long random one
  with `openssl rand -hex 24`.
- Anyone with the token can add and delete questions and trigger analyses and probes
  that spend your Claude usage.
- The model can only search the web and read pages: `claude-code` runs with just the
  `WebSearch` and `WebFetch` tools allowed, and the API engines only get their providers'
  server-side search tools. None of them can read or write local files or run commands.

## Files

- `kettle/`: the code. `cli` / `server` are entry points, `service` holds shared operations,
  `research` holds the prompts and parses results, `engines/` has one module per engine,
  `schedule` / `scheduler` compute time slots and run the built-in scheduler, `store` handles
  file persistence (flock-guarded, so the timer and the web service can run at the same
  time), `jobs` runs background jobs, `notify` sends Bark pushes.
- `web/index.html`: the web UI.
- `questions.toml`: question definitions (gitignored). You can edit it by hand, but kettle
  rewrites it and keeps only the header comment. See `questions.example.toml` for the format.
- `config.toml` / `.env`: configuration and secrets (gitignored).
- `state.json` / `probes.jsonl`: state and probe history (gitignored).
- `systemd/`: user unit templates, filled in and installed by `install.sh`.

## License

[MIT](LICENSE)

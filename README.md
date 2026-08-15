# omnigauge

One dashboard for **Claude Code**, **OpenAI Codex** and **Grok CLI** usage — plan quota and
token volume, side by side, in your terminal.

No API keys. No telemetry. No network calls of its own. It reads the files those tools
already write to your disk, and asks each CLI for its own quota panel.

```
  OMNIGAUGE                                          my-box · 2026-08-14 20:31 CDT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PLAN QUOTA                        subscription windows · normalized to % CONSUMED
  ─────────────────────────────────────────────────────────────────────────────────
  AGENT             WINDOW                               USED   RESETS         AGE
  claude            week     ██████░░░░░░░░░░░░░░░░░░    23%   Aug 19, 6pm    4m ago
  claude/fable      week     ░░░░░░░░░░░░░░░░░░░░░░░░     0%   —              4m ago
  claude            session  ░░░░░░░░░░░░░░░░░░░░░░░░     2%   12:20am        4m ago
  codex             week     ███████████████████████░    94%   23:04 19 Aug   4m ago ⚠
                             vendor reported "6% left" — inverted here
  codex/spark       week     ░░░░░░░░░░░░░░░░░░░░░░░░     0%   19:41 21 Aug   4m ago
  grok/x premium+   week     ██████░░░░░░░░░░░░░░░░░░    26%   August 17      4m ago

  TOKEN VOLUME                                            local transcripts · 24h
  ─────────────────────────────────────────────────────────────────────────────────
  AGENT      FILES    MSGS     OUTPUT      THINK   CACHE-RD      INPUT      TOTAL
  claude         5   3,560      4.42M      1.24M      1.86B      6.71K      1.86B
  codex        209     209    489.95M    222.87M    180.10B    188.11B    188.60B
  grok           3       3          0          0          0          0      4.26M
```

## Why the numbers are kept apart

This is the whole design, and it is deliberate.

**Codex reports percent *remaining*. Claude and Grok report percent *used*.** Shown raw side
by side, a Codex at "6%" looks healthier than a Claude at "23%" — when in fact Codex is
nearly exhausted and Claude has three quarters left. omnigauge normalizes everything to
**percent consumed** and prints what the vendor actually said underneath, so you can check it.

**Token volume is not the vendors' token count.** Local transcripts record cache reads and
per-turn context re-sends; vendors count something narrower. The figures differ by orders of
magnitude and neither is wrong — they have different denominators. omnigauge shows both
kinds of number and never adds them together or reconciles them into one total.

**Subscriptions have no dollar balance**, so none is shown. Plan usage and API spend are
different products; blending them into one "remaining" figure would be fiction.

## Install

Requires Python 3.8+ and `tmux` (only for quota scraping).

```bash
git clone https://github.com/YOU/omnigauge.git
install -m755 omnigauge/omnigauge ~/.local/bin/omnigauge
omnigauge --refresh
```

You stay logged in through your own CLIs — omnigauge never sees or stores a credential.
It only works for accounts *you* are already signed into on that machine.

## Usage

```bash
omnigauge                      # dashboard (cached quota + live token counts)
omnigauge --refresh            # re-scrape quota from every installed CLI (~30s each)
omnigauge --refresh claude     # just one
omnigauge --lifetime           # all-time totals (incremental cache)
omnigauge --since 7d           # 24h | 7d | 30d | today | all
omnigauge --watch              # live redraw, 10s
omnigauge --watch 5 --quota-every 10m
omnigauge --json               # machine-readable
omnigauge --no-color
```

### Two clocks

Token volume is read from local files (~2s) and can update every few seconds. Plan quota
requires launching the vendor's TUI and reading its panel — ~30s per agent, and it spawns a
real session — so it is cached and refreshed on a slow clock. Every quota row shows its own
age, so a stale number looks stale.

## How it gets the numbers

| Agent | Quota | Tokens |
|---|---|---|
| Claude Code | `/usage` panel | `~/.claude/projects/*/*.jsonl` → per-message `usage` |
| OpenAI Codex | `/status` panel | rollout `info.total_token_usage` |
| Grok CLI | `/usage` panel | session `updates.jsonl` → `totalTokens` |

Quota panels are rendered under `tmux` and read back with `capture-pane`. These CLIs draw
character-by-character with cursor moves; stripping ANSI from a raw pty gives you garbage.
tmux is a real terminal emulator, so it does the rendering and omnigauge reads the finished
screen.

On WSL, Codex keeps **two separate stores** — `~/.codex` and `/mnt/c/Users/<you>/.codex`.
Both are discovered. Searching only one and concluding "nothing here" is a real trap.

## When a parse fails

Vendor TUIs change. omnigauge treats a partial parse as a failure, because a plausible
number with the headline missing is worse than no number:

```
  claude   scraping… PARTIAL — 2 row(s), missing [('week', 'all')]
           raw screen → ~/.local/share/omnigauge/last-scrape-claude.txt
```

Each agent declares the windows it must produce. Miss one and you get a loud warning plus the
raw screen dumped for inspection. Stale rows are never silently reused as fresh.

## Storage

Everything lives in `${XDG_DATA_HOME:-~/.local/share}/omnigauge/` (override with
`OMNIGAUGE_HOME`):

- `usage.db` — SQLite. `snapshots` keeps normalized quota with the vendor's raw string and a
  `collected_at`; `filecache` makes lifetime totals incremental so a 140 GB rollout corpus is
  never rescanned; `insights` keeps the vendor's own "what is driving usage" notes.

Nothing leaves the machine.

## Not implemented, on purpose

**API dollar spend.** OpenAI (`/v1/organization/costs`) and Anthropic (`/v1/organization/cost_report`)
both expose real spend, but they need an org **admin** key — a credential worth more than this
tool. The schema already carries `cost_usd` and a `source` column, so it is a clean addition if
you want it. It would be a separate panel, never merged into plan quota.

## Licence

MIT. See [LICENSE](LICENSE).

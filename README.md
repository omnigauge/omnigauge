# omnigauge

One dashboard for **Claude Code**, **OpenAI Codex** and **Grok CLI** usage — plan quota and
token volume, side by side, in your terminal.

No API keys. No telemetry. No network calls of its own. It reads the files those tools
already write to your disk, and asks each CLI for its own quota panel.

```
 ▟▛ OMNIGAUGE                                                    my-box · 20:31 CDT
 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ▲  codex is at 97% — 5d 2h to reset · tightest window

 ╭─ PLAN QUOTA ──────────────────────────────────────── normalized to % consumed ╮
 │                                                                                │
 │     AGENT            WINDOW                            USED   RESETS IN   READ │
 │  ●  claude           week     █████▎················    24%       4d 9h    now │
 │  ○  claude/fable     week     ······················     0%           —    now │
 │  ●  claude           session  █·····················     5%     12:19am    now │
 │  ●  codex            week     █████████████████████▎    97%       5d 2h     7m │
 │                       vendor said "3% left" — inverted                         │
 │  ○  codex/spark      week     ······················     0%      6d 23h     7m │
 │  ●  grok/x premium+  week     █████▋················    26%      2d 16h     7m │
 │                                                                                │
 ╰── subscription windows · no dollar balance exists for these plans ─────────────╯

 ╭─ TOKEN VOLUME ───────────────────────────────────── local transcripts · 24h ──╮
 │                                                                                │
 │  AGENT       FILES    MSGS     OUTPUT     THINK   CACHE-RD      INPUT    TOTAL │
 │  claude          5   3,806      4.66M     1.32M      2.02B      7.16K    2.03B │
 │  codex         211     211    502.77M   229.01M    185.24B    193.51B  194.01B │
 │  grok            3       3          0         0          0          0    4.26M │
 │                                                                                │
 ╰── not comparable to vendor counters · different denominators ──────────────────╯

 ╭─ WHAT IS DRIVING USAGE ────────────────────────────── reported by the vendor ──╮
 │                                                                                │
 │  ▸ 100% of your usage came from sessions active for 8+ hours                   │
 │  ▸ 99% of your usage was at >150k context                                      │
 │  ▸ 19% of your usage was while 4+ sessions ran in parallel                     │
 │                                                                                │
 ╰────────────────────────────────────────────────────────────────────────────────╯
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

Run it bare in a terminal and it is **interactive** — no flags to remember:

```
 r refresh · w watch · t ink · s 24h · b full · ? help · q quit
```

| Key | Does |
|---|---|
| `r` | refresh quota, all agents |
| `1` `2` `3` | refresh claude / codex / grok only |
| `w` | watch mode — auto redraw |
| `t` | cycle theme |
| `s` | cycle window (24h · 7d · 30d · today · all) |
| `b` | brief — hide lifetime and by-model |
| `?` | key help |
| `q` | quit |

Piped, redirected or given any flag, it prints once and exits, so scripts are
unaffected. `--once` forces that explicitly.

```bash
omnigauge                      # interactive board
omnigauge --once               # print and exit
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

## Workspace trust

Launching Claude in a directory it has not seen raises a blocking trust prompt, which
swallows the keystrokes. omnigauge **will not auto-accept it** — trusting a folder is a
real security decision and it persists. It instead reuses a directory the CLI has
demonstrably run in before, read from Claude's own session registry, and detects the dialog
explicitly if one still appears. Override with `--cwd DIR`.

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

# Contributing

The point of this project is that **adding a source is one file**. If your change
needs the core edited, that is usually a sign the provider contract is missing
something — say so in the issue and we will widen the contract rather than
special-case your vendor.

## Adding a provider

Read [`providers/README.md`](providers/README.md) for the contract, then copy
whichever of [`claude.py`](providers/claude.py), [`codex.py`](providers/codex.py)
or [`grok.py`](providers/grok.py) is closest to your vendor — three references,
each a different shape: line-based parsing that survives injected promo lines,
a tail-read over huge files plus the percent-remaining inversion, and a
collapsed-whitespace parse for a panel that wraps. Drop your file in
`providers/`, run `omnigauge --doctor`, and it appears.

Include in the PR:

- **which files or command you read**, and a redacted sample of the raw shape
- **whether reading quota consumes any of the user's allowance.** For X this was
  verified empirically — two consecutive calls left `project_usage` unchanged —
  and that fact belongs in a code comment, not in someone's memory
- **whether you used a documented surface.** Reading a file the tool already
  writes, or driving its own usage panel, is preferred over an undocumented
  internal endpoint. Both are acceptable; say which, so users can judge

## Three rules that are not style preferences

**Percent used, always.** Some vendors report percent *remaining* — Codex does.
Invert it in your provider and put the vendor's original wording in `raw_value`
so a reader can check the conversion. Getting this backwards makes a nearly
exhausted account look healthy, which is the worst failure this tool can have.

**Fail loudly, never plausibly.** Return `[]` and let the core report
`NO QUOTA PARSED` with the raw screen dumped. Declare the windows that must
parse in `expect`; missing one is a `PARTIAL` and is treated as failure. A
blanket `except: continue` once hid a `NameError` on every Claude file and
printed a tidy row of zeros — that is the bug class this rule exists to prevent.

**Never invent a figure the vendor did not give you.** If a dollar balance only
exists in a web console, report what the API exposes and say the rest is
console-only. `—` beats a number you cannot source.

## Running from source

```bash
git clone <repo> && cd omnigauge
./install.sh          # copies the script AND providers to the data dir
omnigauge --doctor
```

No build step, no dependencies. Python 3.8+ stdlib only, plus `tmux` for quota
scraping. Keep it that way — running on a headless box with nothing installed is
a feature, not an accident.

## Testing a provider

```bash
omnigauge --doctor                  # does it detect?
omnigauge --once --since 24h        # do the token numbers look sane?
omnigauge --refresh <name>          # does quota parse? PARTIAL is a failure
```

A parse failure dumps the raw screen to
`~/.local/share/omnigauge/last-scrape-<name>.txt`. Attach that to the issue.

## Tests

```bash
python3 -m unittest discover -s tests          # CLI: widths, parsers, exit codes, OAuth vector
node tests/site_harness.js site/index.html     # site: real renderer, measured rows
```

The panel-width invariant has broken three times — twice as arithmetic, once as
font fallback — and every catch came from measuring rendered lines, never from
reading the code. The suite renders and measures. A PR that touches any text UI
should keep it green.

## What gets rejected

- Anything that transmits usage data anywhere by default
- Merging subscription quota with dollar spend into one "remaining" figure —
  they are different products and blending them is fiction
- Third-party runtime dependencies in the core
- Silent fallbacks that produce a number when the real one could not be read

# Security Policy

Report privately to [**GitHub private vulnerability reporting**](../../security/advisories/new). Please do not open a public issue
for anything credential-related — a public report is a disclosure.

Expect an acknowledgement within a few days. This is a solo-maintained project,
so please allow reasonable time before disclosing publicly.

## What OmniGauge touches

Being honest about the blast radius, because it is not zero:

- **Reads local transcripts** written by Claude Code, Codex and Grok. These
  contain your conversations. OmniGauge parses token counts and never copies,
  uploads or logs their contents.
- **Stores API credentials** in `~/.local/share/omnigauge/credentials.json` at
  mode `0600`. It **refuses to read that file** if the mode is group- or
  world-readable rather than reading it anyway with a warning.
- **Launches vendor CLIs** under tmux and reads the rendered screen to get plan
  quota. It types only a slash command; it never enters a prompt or sends work.
- **Makes outbound requests** only to vendor APIs you have explicitly configured
  — OpenAI and X today. There is no telemetry, no analytics, no phone-home, and
  no update check.

## In scope

- Credential disclosure through logs, error output, argv, the process table or
  crash dumps
- A provider that exfiltrates transcript contents or credentials
- Path traversal or symlink attacks via the provider loader
- Anything causing credentials to be written with permissive modes
- Command injection through vendor output that reaches a shell

## Out of scope

- Vulnerabilities in the vendor CLIs themselves — report those to the vendor
- A vendor changing its UI so a scrape fails. This is expected; OmniGauge is
  built to fail loudly and dump the raw screen rather than report a wrong number
- Physical access to an already-unlocked machine

## For provider authors

Third-party providers execute with your full user privileges. There is no
sandbox. Read a provider before installing it, exactly as you would any script
you run. A malicious provider can read anything you can.

The loader isolates *failures*, not *intent*: a provider that throws is caught
and reported, but one that chooses to exfiltrate is limited only by your file
permissions.

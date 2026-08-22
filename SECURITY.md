# Security Policy

Report privately to **security@omnigauge.dev**. Please do not open a public issue
for anything credential-related - a public report is a disclosure.

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
  - OpenAI and X today. There is no telemetry, no analytics, no phone-home, and
  no update check.

## In scope

- Credential disclosure through logs, error output, argv, the process table or
  crash dumps
- A provider that exfiltrates transcript contents or credentials
- Path traversal or symlink attacks via the provider loader
- Anything causing credentials to be written with permissive modes
- Command injection through vendor output that reaches a shell

## Out of scope

- Vulnerabilities in the vendor CLIs themselves - report those to the vendor
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

## How a release is checked, and how you can check it

- **Tests** (`python3 -m pytest`, 136 tests) and the generated-file checks run on every pull
  request and push (`ci.yml`, Python 3.8, 3.12 and 3.13) and again before every publish.
- **Trusted publishing**: the package is published by the `publish.yml` workflow through PyPI's
  OIDC trust; no long-lived token exists anywhere.
- **Attestations**: every file on PyPI carries a PEP 740 provenance attestation naming the commit
  and the workflow that built it: `https://pypi.org/integrity/omnigauge/<version>/<file>/provenance`.
- **Reproducible**: `reproducible.yml` rebuilds the wheel and sdist from the tag on a clean
  runner and compares their sha256 with PyPI's digests; they are byte-identical. You can do the
  same: `git checkout v<version> && python3 -m build && sha256sum dist/*` against the digests in
  `https://pypi.org/pypi/omnigauge/<version>/json`.
- **SBOM**: every GitHub Release attaches `omnigauge.cdx.json` (CycloneDX) for a clean install of
  the wheel, which shows the one component there is: the package has no third-party dependencies,
  and `audit.yml` (pip-audit against the PyPA advisory database, on every change and weekly) keeps
  that a checked fact rather than a claim.
- **Static analysis**: CodeQL over the Python on every push and pull request and weekly.
- **OpenSSF Scorecard** and the **OpenSSF Best Practices** badge: live readings of the
  repository's practice, linked from the README.

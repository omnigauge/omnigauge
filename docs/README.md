# OmniGauge documentation

Everything lives in the README and the tool itself, kept in step by tests; this page says where.

- **Install:** `pipx install omnigauge` (or `pip install omnigauge`, or the one-file install in the
  README); Python 3.8 or newer; README section *Install* and *Quickstart*. `omnigauge --update`
  brings an installed copy forward whichever way it was installed.
- **Start:** `omnigauge` prints the board; `omnigauge --refresh` re-reads every source; `--check`
  runs headless and exits 0, 1 or 2 for cron. README section *Usage*.
- **Use:** README sections *How it gets the numbers*, *When a parse fails*, *Storage*, *Alerts*,
  *API spend and credits*; the FACTS legend the tool prints (`omnigauge --legend`) says for every
  source what it can and cannot obtain.
- **Use securely:** what the tool reads, stores and sends is in [SECURITY.md](../SECURITY.md)
  (it reads local transcripts and never uploads them; API keys only at mode 0600 and refused
  when group- or world-readable; no telemetry); how a release is checked is there too.
- **Contribute:** [CONTRIBUTING.md](../CONTRIBUTING.md): adding a source is one file, how to run
  the tests, what a change has to bring. The changelog is [CHANGELOG.md](../CHANGELOG.md).

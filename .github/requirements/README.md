# What the workflows install, pinned by hash

Each `.in` names the tools one workflow needs; the matching `.txt` is the full resolution with a
sha256 for every file pip may download, so `pip install --require-hashes -r <file>` installs exactly
those bytes or nothing. The package itself has no third-party dependencies; this is the tooling
around it (pytest, build, pip-audit, cyclonedx-bom).

| file | used by | resolved for |
|---|---|---|
| `ci.txt` | ci.yml (the tests) | Python 3.8 and newer, with markers per version |
| `publish.txt` | publish.yml (tests, then the build) | Python 3.12 and newer |
| `build.txt` | audit.yml, reproducible.yml (the build) | Python 3.12 and newer |
| `audit.txt` | audit.yml (pip-audit in the clean environment) | Python 3.12 and newer |
| `release.txt` | release.yml (the build, the SBOM generator) | Python 3.12 and newer |

Regenerate after editing an `.in` (the command is also in each `.txt` header):

    uv pip compile --universal --python-version 3.8 --generate-hashes --no-annotate ci.in -o ci.txt
    uv pip compile --universal --python-version 3.12 --generate-hashes --no-annotate <name>.in -o <name>.txt

Dependabot follows these files weekly and bumps the pins and hashes together.

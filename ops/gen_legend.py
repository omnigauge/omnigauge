#!/usr/bin/env python3
"""Regenerate the site's providers-legend data from providers/ truth.

The site is static and cannot read a live registry, so its copy of the legend
is GENERATED from the same modules the CLI loads - and a test fails when the
two disagree. That test is the only thing keeping the page honest; without it
the legend becomes a lie within two releases.

  gen_legend.py --write     rewrite site/index.html's LEGEND block
  gen_legend.py --verify    exit 1 if the committed block disagrees (deploy gate)

Generation is pinned to the REPO's providers/ directory - never the machine's
installed copies - so the output is deterministic for everyone.
"""
import importlib.machinery
import importlib.util
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site", "index.html")
START, END = "/*LEGEND-DATA*/", "/*END-LEGEND-DATA*/"


def registry():
    ld = importlib.machinery.SourceFileLoader("omnigauge", os.path.join(ROOT, "omnigauge"))
    og = importlib.util.module_from_spec(importlib.util.spec_from_loader("omnigauge", ld))
    sys.modules["omnigauge"] = og
    ld.exec_module(og)
    og.PROVIDER_DIRS = [os.path.join(ROOT, "providers")]
    og.load_providers()
    og.all_agents()
    return {"sources": [{"n": n, "k": k, "c": caps} for n, k, caps in og.legend_rows()],
            "negatives": [{"n": n, "why": w} for n, w in og.NEGATIVES]}


def block():
    data = json.dumps(registry(), separators=(",", ":"), sort_keys=True)
    return f"{START}var LEGEND={data};{END}"


FSTART, FEND = "/*FACTS-DATA*/", "/*END-FACTS-DATA*/"


def facts():
    """The numbers the prose used to hand-type - and got wrong by 41% - now
    DERIVED: line count, source and provider counts, test count. Every one of
    these was true when someone typed it; deriving is the only way it stays
    true. Test count comes from pytest's own collector, not a grep."""
    import glob
    import re
    import subprocess
    reg = registry()
    agents = [s["n"] for s in reg["sources"] if s["k"] == "agent"]
    apis = [s["n"] for s in reg["sources"] if s["k"] == "api"]
    with open(os.path.join(ROOT, "omnigauge"), encoding="utf-8") as fh:
        lines = sum(1 for _ in fh)
    mirrors = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOT, "providers", "*.py")))
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", os.path.join(ROOT, "tests")],
                         capture_output=True, text=True, cwd=ROOT)
    m = re.search(r"(\d+) tests? collected", out.stdout + out.stderr)
    tests = int(m.group(1)) if m else 0
    # the version the site shows, from the one place it is set: a hardcoded "BIOS v1.0.3" in
    # the page sat three releases behind until John noticed (2026-08-21); now it cannot drift,
    # because --verify fails the build when the page's FACTS disagree with pyproject.toml
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as fh:
        m = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M)
    version = m.group(1) if m else "?"
    return {"version": version, "lines": lines, "lines_k": f"{lines/1000:.1f}k", "agents": agents, "apis": apis,
            "sources": len(agents) + len(apis), "negatives": [n["n"] for n in reg["negatives"]],
            "mirrors": mirrors, "tests": tests}


def facts_block():
    data = json.dumps(facts(), separators=(",", ":"), sort_keys=True)
    return f"{FSTART}var FACTS={data};{FEND}"


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--verify"
    html = open(SITE, encoding="utf-8").read()
    i, j = html.find(START), html.find(END)
    if i < 0 or j < 0:
        print("LEGEND markers missing from site/index.html", file=sys.stderr)
        return 2
    current = html[i:j + len(END)]
    wanted = block()
    fi, fj = html.find(FSTART), html.find(FEND)
    if fi < 0 or fj < 0:
        print("FACTS markers missing from site/index.html", file=sys.stderr)
        return 2
    fcurrent = html[fi:fj + len(FEND)]
    fwanted = facts_block()
    if mode == "--verify":
        ok = current == wanted and fcurrent == fwanted
        if ok:
            print("legend: site matches providers/  ·  facts: site matches the repo")
            return 0
        if current != wanted:
            print("legend: site DISAGREES with providers/ - run ops/gen_legend.py --write", file=sys.stderr)
        if fcurrent != fwanted:
            print("facts: site DISAGREES with the repo (lines/sources/tests) - run ops/gen_legend.py --write", file=sys.stderr)
        return 1
    if mode == "--write":
        if fcurrent != fwanted:
            html = html[:fi] + fwanted + html[fj + len(FEND):]
            i, j = html.find(START), html.find(END)
            current = html[i:j + len(END)]
        if current == wanted and fcurrent == fwanted:
            print("legend: already current")
            return 0
        open(SITE, "w", encoding="utf-8").write(html[:i] + wanted + html[j + len(END):])
        print("legend: rewritten")
        return 0
    print(f"unknown mode {mode!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

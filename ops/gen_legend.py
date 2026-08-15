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
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site", "index.html")
START, END = "/*LEGEND-DATA*/", "/*END-LEGEND-DATA*/"


def registry_rows():
    ld = importlib.machinery.SourceFileLoader("omnigauge", os.path.join(ROOT, "omnigauge"))
    og = importlib.util.module_from_spec(importlib.util.spec_from_loader("omnigauge", ld))
    sys.modules["omnigauge"] = og
    ld.exec_module(og)
    og.PROVIDER_DIRS = [os.path.join(ROOT, "providers")]
    og.load_providers()
    og.all_agents()
    return [{"n": n, "k": k, "c": caps} for n, k, caps in og.legend_rows()]


def block():
    data = json.dumps(registry_rows(), separators=(",", ":"), sort_keys=True)
    return f"{START}var LEGEND={data};{END}"


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--verify"
    html = open(SITE, encoding="utf-8").read()
    i, j = html.find(START), html.find(END)
    if i < 0 or j < 0:
        print("LEGEND markers missing from site/index.html", file=sys.stderr)
        return 2
    current = html[i:j + len(END)]
    wanted = block()
    if mode == "--verify":
        if current == wanted:
            print("legend: site matches providers/")
            return 0
        print("legend: site DISAGREES with providers/ - run ops/gen_legend.py --write",
              file=sys.stderr)
        return 1
    if mode == "--write":
        if current == wanted:
            print("legend: already current")
            return 0
        open(SITE, "w", encoding="utf-8").write(html[:i] + wanted + html[j + len(END):])
        print("legend: rewritten")
        return 0
    print(f"unknown mode {mode!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

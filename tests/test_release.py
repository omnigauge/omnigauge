"""A release goes out only once the owner approves it on GitHub.

publish.yml is the one workflow a version tag starts, and its publish job runs in the environment
`release`, whose required reviewer is the owner (set in the repository's settings): a tag pushed by
mistake publishes nothing until the owner approves it in the browser. The GitHub Release and the
reproducibility check are called from publish.yml once PyPI has the version, so no other workflow
starts on a tag and gets around that approval.
"""
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = os.path.join(ROOT, ".github", "workflows")


def _text(name):
    with open(os.path.join(WF, name), encoding="utf-8") as fh:
        return fh.read()


def _block(text, head):
    """The lines indented under `head`, a whole line such as "on:" or "  publish:"."""
    lines = text.splitlines()
    assert head in lines, f"no line {head!r}"
    depth = len(head) - len(head.lstrip())
    out = []
    for line in lines[lines.index(head) + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= depth:
            break
        out.append(line)
    return out


def test_only_publish_starts_on_a_version_tag():
    started = sorted(os.path.basename(p) for p in glob.glob(os.path.join(WF, "*.yml"))
                     if any(re.match(r"\s+tags:", line) for line in _block(_text(os.path.basename(p)), "on:")))
    assert started == ["publish.yml"], f"a tag starts {started}; only publish.yml may, behind the owner's approval"


def test_publishing_waits_for_the_owners_approval():
    job = _block(_text("publish.yml"), "  publish:")
    at = [i for i, line in enumerate(job) if line.startswith("    environment:")]
    assert at, "publish.yml's publish job runs in no environment, so nothing waits for the owner"
    said = job[at[0]].split(":", 1)[1].strip() or job[at[0] + 1].strip()
    assert said in ("release", "name: release"), f"publish.yml's publish job runs in {said!r}, not `release`"


def test_the_github_release_and_reproducibility_check_follow_publishing():
    text = _text("publish.yml")
    for name in ("release", "reproducible"):
        job = _block(text, f"  {name}:")
        assert "    needs: publish" in job, f"{name} must wait until PyPI has the version"
        assert f"    uses: ./.github/workflows/{name}.yml" in job, f"publish.yml must call {name}.yml"
        assert "  workflow_call:" in _block(_text(f"{name}.yml"), "on:"), f"{name}.yml must be callable from publish.yml"

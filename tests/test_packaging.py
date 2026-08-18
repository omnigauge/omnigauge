"""The pip/pipx package must carry the single file and EVERY provider mirror.

A mirror that is not shipped silently falls back to the built-in at load - the
exact drift the mirror rule exists to prevent - so the wheel's force-include
list is checked against providers/ on disk, and the package version against
the file's own VERSION.
"""
import glob
import os
import re
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pyproject():
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        return tomllib.load(fh)


def test_every_provider_mirror_is_shipped_in_the_wheel():
    fi = _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    on_disk = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "providers", "*.py")))
    assert on_disk, "no providers on disk?"
    for name in on_disk:
        assert fi.get(f"providers/{name}") == f"omnigauge_cli/providers/{name}", f"providers/{name} is not shipped in the wheel"
    shipped = sorted(k.split("/", 1)[1] for k in fi if k.startswith("providers/"))
    assert shipped == on_disk, f"wheel ships {shipped} but disk has {on_disk}"


def test_the_single_file_is_shipped_beside_its_providers():
    fi = _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert fi.get("omnigauge") == "omnigauge_cli/omnigauge"
    assert _pyproject()["project"]["scripts"]["omnigauge"] == "omnigauge_cli:main"


def test_package_version_matches_the_file():
    with open(os.path.join(ROOT, "omnigauge"), encoding="utf-8") as fh:
        m = re.search(r'^VERSION = "([^"]+)"', fh.read(), re.M)
    assert m, "VERSION not found in the file"
    assert _pyproject()["project"]["version"] == m.group(1)


def test_entry_point_runs_the_file_as_main():
    import importlib.util
    spec = importlib.util.spec_from_file_location("omnigauge_cli", os.path.join(ROOT, "omnigauge_cli", "__init__.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.main)
    assert os.path.basename(mod.SCRIPT) == "omnigauge"

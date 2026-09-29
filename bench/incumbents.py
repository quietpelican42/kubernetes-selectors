"""pykube-ng is excluded: importing pykube.console starts an interactive shell and reads ~/.kube/config.

List parse/match functions for label selectors in the Python Kubernetes libraries.

    python -m venv .cache/inc && .cache/inc/bin/pip install kubernetes kr8s lightkube
    .cache/inc/bin/python bench/incumbents.py
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import pkgutil
import re
import sys
import warnings

LIBS = {"kubernetes": "kubernetes", "kr8s": "kr8s", "lightkube": "lightkube"}
PATTERN = re.compile(r"(parse|match|from_str|loads?).*(selector|label)|(selector|label).*(parse|match|from_str)", re.I)


def public_functions(module: object) -> list[str]:
    return [n for n in dir(module) if PATTERN.search(n) and callable(getattr(module, n, None))]


def main() -> int:
    warnings.simplefilter("ignore")
    missing = [d for d in LIBS if importlib.util.find_spec(LIBS[d]) is None]
    if missing:
        print(f"SKIPPED: not installed: {', '.join(missing)}. See the docstring for install commands.")
        return 0
    for dist, top in LIBS.items():
        version = importlib.metadata.version(dist)
        pkg = importlib.import_module(top)
        hits: list[str] = []
        seen = 0
        for info in pkgutil.walk_packages(pkg.__path__, top + "."):
            skip = (".console", ".models", ".api", ".rest", ".apis", ".resources", ".generic_resource")
            if any(info.name.endswith(x) or (x + ".") in info.name for x in skip):
                continue
            try:
                mod = importlib.import_module(info.name)
            except Exception:
                continue
            seen += 1
            hits += [f"{info.name}.{n}" for n in public_functions(mod)]
        print(f"{dist} {version}: {seen} modules scanned, parse/match functions for selectors: {hits or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Keeps the project organized: feature packages stay independent; only the app shell (gexpro) joins them."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = {"gexsys", "feeds", "gexpro"}
# who may import whom (the app shell composes; features never reach into each other or into the shell)
ALLOWED = {"gexsys": set(), "feeds": set(), "gexpro": {"gexsys", "feeds"}}


def imported_packages(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found & PACKAGES


class TestBoundaries(unittest.TestCase):
    def test_packages_only_import_what_they_may(self):
        bad = []
        for pkg, allowed in ALLOWED.items():
            for f in (ROOT / pkg).rglob("*.py"):
                for other in imported_packages(f) - {pkg} - allowed:
                    bad.append(f"{f.relative_to(ROOT)} imports {other}")
        self.assertEqual(bad, [], "packages must stay independent; join them in gexpro instead")

    def test_every_component_has_the_contract(self):
        from gexpro.components import default_components
        from gexpro.server import collect_routes
        comps = default_components([])
        for c in comps:
            for attr in ("name", "routes", "start", "stop", "build_static"):
                self.assertTrue(hasattr(c, attr), f"{type(c).__name__} lacks {attr}")
        routes = collect_routes(comps)                     # raises if two components claim one path
        self.assertTrue({"/api/all", "/api/indicator", "/api/news", "/api/posts"} <= set(routes))


if __name__ == "__main__":
    unittest.main()

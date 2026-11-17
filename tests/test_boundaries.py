"""The package's boundaries, held by tests rather than by convention."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).parent.parent / "valplan"


def test_only_the_boundary_module_imports_valgebra():
    for path in PACKAGE.glob("*.py"):
        if path.name == "_valgebra.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert "valgebra" not in imported, path.name

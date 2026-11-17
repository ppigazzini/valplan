"""The package's boundaries, held by tests rather than by convention."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).parent.parent / "valplan"


def _imported(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }


def test_only_the_boundary_module_imports_valgebra():
    for path in PACKAGE.glob("*.py"):
        if path.name != "_valgebra.py":
            assert "valgebra" not in _imported(path), path.name


def test_only_the_planning_boundary_imports_valgebra_planning():
    for path in PACKAGE.glob("*.py"):
        if path.name != "_planning.py":
            assert "valgebra_planning" not in _imported(path), path.name

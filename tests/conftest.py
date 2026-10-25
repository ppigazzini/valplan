import json
from pathlib import Path

import pytest

from valplan.contracts import task, tools

HELPDESK = Path(__file__).parent.parent / "examples" / "helpdesk"


@pytest.fixture(scope="session")
def library():
    return tools(json.loads((HELPDESK / "tools.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="session")
def tasks():
    specs = json.loads((HELPDESK / "tasks.json").read_text(encoding="utf-8"))["tasks"]
    return {s["name"]: task(s) for s in specs}


@pytest.fixture(scope="session")
def raw_tools():
    return json.loads((HELPDESK / "tools.json").read_text(encoding="utf-8"))["tools"]

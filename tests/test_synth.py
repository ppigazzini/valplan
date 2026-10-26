import random

import pytest

from valplan.bench import library
from valplan.contracts import task as read_task
from valplan.contracts import tools as read_tools
from valplan.program import Call, Return, Stop, Test, render, stops
from valplan.run import ContractError, run
from valplan.sample import Sampler
from valplan.schema import Unsupported
from valplan.synth import Planner, gaps, witnesses
from valplan.verify import verify


def _plan(library, task, *, weak=False):
    planner = Planner(library, task, witnesses(library, task))
    return planner, planner.plan(max_depth=6, weak=weak)


class TestHelpdesk:
    def test_a_linear_task_gets_the_two_call_program(self, library, tasks):
        _, program = _plan(library, tasks["ticket"])
        assert render(program) == (
            "c1 = find_customer(email=email)\n"
            "c2 = open_ticket(customer_id=c1.customer_id, subject=subject)\n"
            "return c2.ticket_id"
        )

    def test_settling_an_invoice_branches_three_ways_and_is_strong(self, library, tasks):
        planner, program = _plan(library, tasks["settle-latest-invoice"], weak=True)
        assert not planner.weak
        assert stops(program) == 0
        text = render(program)
        assert "if c2.status in refund_invoice.invoice_status:" in text
        assert "if c2.status in void_invoice.invoice_status:" in text
        assert text.endswith("return c2.status")

    @pytest.mark.parametrize(
        ("name", "uncovered"), [("escalate", "c1.tier"), ("vat-for-customer", "c1.country")]
    )
    def test_a_task_no_program_covers_gets_a_weak_one_naming_the_gap(
        self, library, tasks, name, uncovered
    ):
        assert _plan(library, tasks[name])[1] is None
        planner, program = _plan(library, tasks[name], weak=True)
        assert planner.weak
        assert stops(program) == 1
        assert f"stop  # {uncovered} is not covered by this program" in render(program)

    @pytest.mark.parametrize(
        "name", ["ticket", "settle-latest-invoice", "escalate", "vat-for-customer"]
    )
    def test_the_independent_verifier_proves_every_link_of_every_program(
        self, library, tasks, name
    ):
        _, program = _plan(library, tasks[name], weak=True)
        checks = verify(library, tasks[name], program)
        assert all(c.holds or c.relation == "uncovered" for c in checks)
        assert sum(c.relation == "uncovered" for c in checks) == stops(program)


def _mock(raw_tools, seed):
    def impl_for(spec):
        sampler = Sampler(spec["outputSchema"], random.Random(f"{seed}:{spec['name']}"))

        def impl(_arguments):
            drawn = sampler.draw(spec["outputSchema"], tries=200)
            assert drawn, spec["name"]
            return drawn[0]

        return impl

    return {spec["name"]: impl_for(spec) for spec in raw_tools}


class TestExecution:
    @pytest.mark.parametrize("seed", range(25))
    def test_a_strong_program_never_breaks_a_contract_whatever_the_tools_return(
        self, library, tasks, raw_tools, seed
    ):
        task = tasks["settle-latest-invoice"]
        _, program = _plan(library, task)
        answer = run(library, task, program, {"email": "ada@example.org"}, _mock(raw_tools, seed))
        assert task.goal.is_valid(answer)

    def test_a_weak_program_stops_on_its_uncovered_case(self, library, tasks, raw_tools):
        task = tasks["escalate"]
        _, program = _plan(library, task, weak=True)
        impls = _mock(raw_tools, 0)
        impls["find_customer"] = lambda _a: {
            "customer_id": "cus_abcdefgh",
            "tier": "free",
            "country": "IT",
        }
        with pytest.raises(ContractError, match=r"no contract covers c1\.tier"):
            run(library, task, program, {"email": "ada@example.org", "subject": "help"}, impls)

    def test_a_tool_that_breaks_its_own_contract_is_named_at_the_call(
        self, library, tasks, raw_tools
    ):
        task = tasks["ticket"]
        _, program = _plan(library, task)
        impls = _mock(raw_tools, 0)
        impls["find_customer"] = lambda _a: {"customer_id": "nope", "tier": "free", "country": "IT"}
        with pytest.raises(ContractError, match="find_customer returned"):
            run(library, task, program, {"email": "ada@example.org", "subject": "help"}, impls)


def test_programs_are_made_of_known_steps(library, tasks):
    _, program = _plan(library, tasks["settle-latest-invoice"])
    assert isinstance(program[0], Call)
    assert isinstance(program[-1], Test)
    assert not any(isinstance(s, Stop) for s in program)
    assert isinstance(program[-1].other[-1], Test)
    assert isinstance(program[-1].other[-1].other[-1], Return)


class TestSyntheticLibraries:
    @pytest.mark.parametrize("n", [8, 16, 32])
    @pytest.mark.parametrize("seed", [0, 1, 2])
    def test_every_program_found_is_proven_in_full_by_the_verifier(self, n, seed):
        lib_json, spec = library(n, seed)
        lib, task = read_tools(lib_json), read_task(spec)
        program = Planner(lib, task, witnesses(lib, task)).plan(max_depth=6)
        assert program is not None
        checks = verify(lib, task, program)
        assert all(c.holds for c in checks), [c for c in checks if not c.holds]


def test_a_gap_lists_every_uncovered_value_when_the_cells_are_enumerated(library, tasks):
    planner, program = _plan(library, tasks["escalate"], weak=True)
    (gap,) = gaps(planner, program)
    assert gap.var == "c1.tier"
    assert gap.complete
    assert sorted(gap.values) == ["free", "pro"]


def test_a_stop_is_extended_by_a_deeper_continuation_on_the_same_variable():
    def tool(name, args, out):
        return {
            "name": name,
            "inputSchema": {"type": "object", "properties": args, "required": list(args)},
            "outputSchema": {"type": "object", "properties": out, "required": list(out)},
        }

    goal = {"type": "string", "pattern": "^G[0-9]{3}$"}
    k = [{"type": "string", "pattern": f"^K{i}$"} for i in range(4)]
    lib = read_tools(
        {
            "tools": [
                tool("fa", {"x": {"enum": ["a"]}}, {"g": goal}),
                tool("fb", {"x": {"enum": ["b"]}, "k": k[3]}, {"g": goal}),
                tool("k1", {"x": {"enum": ["b"]}}, {"k": k[1]}),
                tool("k2", {"k": k[1]}, {"k": k[2]}),
                tool("k3", {"k": k[2]}, {"k": k[3]}),
            ]
        }
    )
    task = read_task(
        {
            "name": "t",
            "inputs": {
                "type": "object",
                "properties": {"x": {"enum": ["a", "b", "c"]}},
                "required": ["x"],
            },
            "goal": goal,
        }
    )
    planner = Planner(lib, task, witnesses(lib, task))
    program = planner.plan(max_depth=7, weak=True)
    assert program is not None
    assert stops(program) == 1
    assert "c4 = fb(x=x, k=c3.k)" in render(program)
    (gap,) = gaps(planner, program)
    assert gap.values == ("c",)


class TestNumericPrograms:
    @pytest.mark.parametrize(("n", "seed"), [(8, 0), (8, 1), (16, 1), (32, 2)])
    def test_a_branch_the_interval_rule_proves_never_breaks_a_contract_at_run_time(self, n, seed):
        lib_json, spec = library(n, seed, "numbers")
        lib, task = read_tools(lib_json), read_task(spec)
        program = Planner(lib, task, witnesses(lib, task)).plan(max_depth=6)
        assert program is not None
        id_pattern = spec["inputs"]["properties"]["id"]["pattern"]
        start = {"id": id_pattern[1:-1].replace("[a-z0-9]{6}", "abc123"), "k": 15000}
        for trial in range(20):
            answer = run(lib, task, program, start, _mock(lib_json["tools"], f"{n}:{seed}:{trial}"))
            assert task.goal.is_valid(answer)


def test_a_nullable_range_gets_a_strong_program_that_runs_on_both_halves():
    out = {"type": "object", "properties": {"r": {"const": "r"}}, "required": ["r"]}

    def takes(name, arg):
        properties = {"x": arg}
        return {
            "name": name,
            "inputSchema": {"type": "object", "properties": properties, "required": ["x"]},
            "outputSchema": out,
        }

    window = {"type": "number", "exclusiveMinimum": 5000, "exclusiveMaximum": 5001}
    v = {"anyOf": [{"type": "null"}, window]}
    lib = read_tools(
        {
            "tools": [
                {
                    "name": "get",
                    "inputSchema": {"type": "object"},
                    "outputSchema": {"type": "object", "properties": {"v": v}, "required": ["v"]},
                },
                takes("take_null", {"type": "null"}),
                takes("take_pos", {"type": "number", "minimum": 0}),
                takes("take_int", {"type": "integer"}),
            ]
        }
    )
    task = read_task(
        {"name": "t", "inputs": {"type": "object", "properties": {}}, "goal": {"const": "r"}}
    )
    planner = Planner(lib, task, witnesses(lib, task))
    program = planner.plan()
    assert program is not None
    assert not planner.weak

    def returns(result):
        return lambda _arguments: result

    for value in (None, 5000.5):
        impls = {name: returns({"r": "r"}) for name in ("take_null", "take_pos", "take_int")}
        impls["get"] = returns({"v": value})
        assert run(lib, task, program, {}, impls) == "r"


def test_a_required_key_outside_properties_makes_the_tool_uncallable():
    out = {"type": "object", "properties": {"r": {"const": "r"}}, "required": ["r"]}
    needs_token = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a", "token"],
    }
    lib = read_tools({"tools": [{"name": "f", "inputSchema": needs_token, "outputSchema": out}]})
    inputs = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    task = read_task({"name": "t", "inputs": inputs, "goal": {"const": "r"}})
    assert not lib[0].plain
    assert Planner(lib, task, witnesses(lib, task)).plan() is None


class TestRunnerContracts:
    @staticmethod
    def _library():
        out = {
            "type": "object",
            "properties": {"id": {"type": "string"}, "tier": {"enum": ["pro", "free"]}},
            "required": ["id"],
            "additionalProperties": False,
            "dependentRequired": {"tier": ["id"]},
            "allOf": [{"properties": {"id": {"maxLength": 6}}}],
        }
        inputs = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
        lib = read_tools({"tools": [{"name": "get", "inputSchema": inputs, "outputSchema": out}]})
        task = read_task({"name": "t", "inputs": inputs, "goal": {"type": "string"}})
        program = (Call("c1", "get", (("q", "q"),)), Return("c1.id"))
        return lib, task, program

    @pytest.mark.parametrize(
        "result",
        [{"id": "cus_ab", "extra": 1}, {"id": "cus_abc"}, {"id": "cus_ab", "tier": "gold"}],
    )
    def test_a_result_outside_its_output_schema_is_named_at_the_call(self, result):
        lib, task, program = self._library()
        with pytest.raises(ContractError, match="outside its output schema"):
            run(lib, task, program, {"q": "x"}, {"get": lambda _a: result})

    def test_a_missing_input_is_named(self):
        lib, task, program = self._library()
        with pytest.raises(ContractError, match="input q is missing"):
            run(lib, task, program, {}, {"get": lambda _a: {"id": "a"}})


class TestNames:
    def test_a_tool_name_with_dots_plans(self):
        out = {"type": "object", "properties": {"r": {"const": "r"}}, "required": ["r"]}

        def takes(name, arg):
            properties = {"x": arg}
            return {
                "name": name,
                "inputSchema": {"type": "object", "properties": properties, "required": ["x"]},
                "outputSchema": out,
            }

        lib = read_tools(
            {
                "tools": [
                    takes("billing.small", {"type": "integer", "maximum": 9}),
                    takes("billing.large", {"type": "integer", "minimum": 10}),
                ]
            }
        )
        inputs = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
        task = read_task({"name": "t", "inputs": inputs, "goal": {"const": "r"}})
        planner = Planner(lib, task, witnesses(lib, task))
        program = planner.plan()
        assert program is not None
        assert not planner.weak
        assert not [c for c in verify(lib, task, program) if c.relation == "not_subset"]

    def test_an_input_named_like_a_result_is_refused(self):
        inputs = {
            "type": "object",
            "properties": {"c1.id": {"type": "string"}},
            "required": ["c1.id"],
        }
        with pytest.raises(Unsupported, match="named like a call's result"):
            read_task({"name": "t", "inputs": inputs, "goal": True})


class TestDegenerateContracts:
    @staticmethod
    def _tool(name, args, out):
        return {
            "name": name,
            "inputSchema": {"type": "object", "properties": args, "required": list(args)},
            "outputSchema": {"type": "object", "properties": out, "required": list(out)},
        }

    def test_a_result_that_admits_no_value_is_refused(self):
        empty = {"type": "string", "minLength": 5, "maxLength": 2}
        with pytest.raises(Unsupported, match="admits no value"):
            read_tools({"tools": [self._tool("broken", {"x": {"type": "string"}}, {"g": empty})]})

    def test_a_test_whose_branch_only_returns_the_tested_value_is_not_made(self):
        g = {"type": "string", "pattern": "^G[0-9]{3}$"}
        y = {"type": "string", "pattern": "^Y$"}
        lib = read_tools({"tools": [self._tool("use", {"g": g}, {"y": y})]})
        inputs = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
        task = read_task({"name": "t", "inputs": inputs, "goal": g})
        assert Planner(lib, task, witnesses(lib, task)).plan(weak=True) is None

from valplan.program import Call, Return, Stop, Test, from_json, prune, render, stops, to_json


def test_a_program_round_trips_through_json():
    program = (
        Call("c1", "a", (("x", "in"),)),
        Test("c1.y", "b.z", (Call("c2", "b", (("z", "c1.y"),)), Return("c2.w")), (Stop("c1.y"),)),
    )
    assert from_json(to_json(program)) == program
    assert stops(program) == 1


def test_prune_drops_a_call_nothing_reads_and_renumbers():
    program = (
        Call("c1", "a", (("x", "in"),)),
        Call("c2", "unused", (("x", "in"),)),
        Call("c3", "b", (("y", "c1.out"),)),
        Return("c3.out"),
    )
    assert render(prune(program)) == "c1 = a(x=in)\nc2 = b(y=c1.out)\nreturn c2.out"


def test_prune_inside_a_branch_keeps_every_read_on_the_variable_it_named():
    program = (
        Call("c1", "a", (("x", "in"),)),
        Test(
            "c1.s",
            "b.s",
            (
                Call("c2", "b", (("s", "c1.s"),)),
                Call("c3", "fin", (("id", "c2.id"), ("s", "c1.s"))),
                Return("c3.out"),
            ),
            (Stop("c1.s"),),
        ),
    )
    assert prune(program) == program

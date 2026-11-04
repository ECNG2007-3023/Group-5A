"""Milestone 5: files are analysed in dependency order, whatever order the
client sends them in (a front end cannot be expected to know GHDL's rules).
No Docker needed."""
from app.docker_runner import analysis_order

PKG = "package consts is constant W : integer := 4; end package;"
PKG_BODY = "package body consts is end package body;"
ENT = "use work.consts.all;\nentity adder is end entity;"
ARCH = "architecture rtl of adder is begin end architecture;"
TB = "entity adder_tb is end;\narchitecture s of adder_tb is begin\n" \
     "  dut: entity work.adder;\nend architecture;"


def names(files):
    return [n for n, _ in analysis_order(files)]


def test_testbench_first_is_reordered():
    files = [("tb.vhd", TB), ("adder.vhd", ENT), ("consts.vhd", PKG)]
    assert names(files) == ["consts.vhd", "adder.vhd", "tb.vhd"]


def test_already_correct_order_is_kept():
    files = [("consts.vhd", PKG), ("adder.vhd", ENT), ("tb.vhd", TB)]
    assert names(files) == ["consts.vhd", "adder.vhd", "tb.vhd"]


def test_independent_files_keep_sent_order():
    files = [("b.vhd", "entity b is end;"), ("a.vhd", "entity a is end;")]
    assert names(files) == ["b.vhd", "a.vhd"]


def test_architecture_and_package_body_in_own_files():
    files = [("arch.vhd", ARCH), ("body.vhd", PKG_BODY),
             ("ent.vhd", ENT), ("pkg.vhd", PKG)]
    order = names(files)
    assert order.index("pkg.vhd") < order.index("body.vhd")
    assert order.index("pkg.vhd") < order.index("ent.vhd")
    assert order.index("ent.vhd") < order.index("arch.vhd")


def test_case_and_comments_ignored():
    tb = "-- uses work.ghost (only in a comment)\nENTITY T is end;\n" \
         "architecture s of t is begin u: entity WORK.Adder; end;"
    files = [("t.vhd", tb), ("ghost.vhd", "entity ghost is end;"),
             ("adder.vhd", "entity ADDER is end;")]
    assert names(files) == ["ghost.vhd", "adder.vhd", "t.vhd"]


def test_dependency_loop_does_not_hang():
    a = "entity a is end; architecture r of a is begin u: entity work.b; end;"
    b = "entity b is end; architecture r of b is begin u: entity work.a; end;"
    assert sorted(names([("a.vhd", a), ("b.vhd", b)])) == ["a.vhd", "b.vhd"]


def test_unknown_library_units_are_ignored():
    files = [("tb.vhd", "use work.not_sent.all; entity tb is end;")]
    assert names(files) == ["tb.vhd"]

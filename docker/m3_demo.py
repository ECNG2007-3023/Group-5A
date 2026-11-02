"""Milestone 3 demo: run real VHDL jobs through app.docker_runner and show
what comes back. Nothing here is needed by the service; it's just for looking.

Run from the repo root (venv active, Docker Desktop open):
    python docker/m3_demo.py

To try your own VHDL, put the files in a folder and pass the folder and the
testbench name:
    python docker/m3_demo.py my_vhdl_folder my_tb
    python docker/m3_demo.py my_vhdl_folder my_tb 500ns
The VCD from a successful run is saved as demo_output/<testbench>.vcd so you
can open it in GTKWave.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import docker_runner as dr  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "demo_output"

AND_GATE = """\
library ieee;
use ieee.std_logic_1164.all;

entity and_gate is
  port (a, b : in std_logic; y : out std_logic);
end entity;

architecture rtl of and_gate is
begin
  y <= a and b;
end architecture;
"""

AND_GATE_TB = """\
library ieee;
use ieee.std_logic_1164.all;

entity and_gate_tb is
end entity;

architecture sim of and_gate_tb is
  signal a, b, y : std_logic := '0';
begin
  dut: entity work.and_gate port map (a => a, b => b, y => y);

  process
  begin
    a <= '0'; b <= '0'; wait for 10 ns;
    a <= '0'; b <= '1'; wait for 10 ns;
    a <= '1'; b <= '0'; wait for 10 ns;
    a <= '1'; b <= '1'; wait for 10 ns;
    assert y = '1' report "1 and 1 should be 1" severity error;
    wait;
  end process;
end architecture;
"""

RUNAWAY_TB = """\
entity runaway_tb is
end entity;

architecture sim of runaway_tb is
  signal clk : bit := '0';
begin
  process
  begin
    loop
      clk <= not clk;
      wait for 1 ns;
    end loop;
  end process;
end architecture;
"""

DEMOS = [
    ("1. Working AND gate + testbench (should SUCCEED and make a VCD)",
     [{"name": "and_gate.vhd", "content": AND_GATE},
      {"name": "and_gate_tb.vhd", "content": AND_GATE_TB}],
     "and_gate_tb", "100ns", None),
    ("2. Missing semicolon (should fail with analysis_error)",
     [{"name": "and_gate.vhd", "content": AND_GATE.replace("a and b;", "a and b")}],
     "and_gate", "100ns", None),
    ("3. Wrong testbench name (should fail with elaboration_error)",
     [{"name": "and_gate.vhd", "content": AND_GATE}],
     "not_a_real_tb", "100ns", None),
    ("4. Simulation that never ends (should be killed: timeout)",
     [{"name": "runaway_tb.vhd", "content": RUNAWAY_TB}],
     "runaway_tb", "1000sec", 5),
    ("5. Bad file name (should be rejected before Docker: validation_error)",
     [{"name": "../hack.vhd", "content": AND_GATE}],
     "and_gate", "100ns", None),
]


def show(title, files, top, stop_time, timeout_s):
    print("=" * 70)
    print(title)
    print("-" * 70)
    r = dr.run_job(files, top, stop_time, timeout_s=timeout_s)
    print(f"status : {r['status']}")
    print(f"stage  : {r['stage']}")
    print(f"error  : {r['error']}")
    print(f"message: {r['message']}")
    for s in r["stages"]:
        flag = "  (killed: timeout)" if s["timed_out"] else ""
        print(f"  [{s['stage']}] exit {s['exit_code']} in {s['duration_s']} s{flag}")
        print(f"      $ {s['command']}")
        for line in s["output"].strip().splitlines()[:6]:
            print(f"      | {line}")
    if r["vcd"]:
        OUT_DIR.mkdir(exist_ok=True)
        path = OUT_DIR / f"{top}.vcd"
        path.write_bytes(r["vcd"])
        print(f"VCD    : {len(r['vcd'])} bytes, saved to {path}")
    return r


def main():
    status = dr.docker_status()
    print(f"Docker: {status['docker']}   GHDL image: {status['image']}")
    if status["docker"] != "ok" or status["image"] != "present":
        print("Start Docker Desktop and build the image first:\n"
              "  docker build -t p5a-ghdl ./docker")
        return 1

    if len(sys.argv) >= 3:
        folder, top = Path(sys.argv[1]), sys.argv[2]
        stop = sys.argv[3] if len(sys.argv) > 3 else None
        files = [{"name": p.name, "content": p.read_text(encoding="utf-8")}
                 for p in sorted(folder.glob("*.vhd*"))]
        print(f"Files in order: {[f['name'] for f in files]}")
        print("(GHDL analyses them in this order; rename them, e.g. 1_design.vhd,"
              " 2_tb.vhd, if the order matters.)")
        show(f"Your files from {folder}", files, top, stop, None)
    else:
        for demo in DEMOS:
            show(*demo)

    left = dr.get_client().containers.list(
        all=True, filters={"label": dr.config.CONTAINER_LABEL})
    jobs_left = list(dr.config.JOBS_DIR.glob("*")) if dr.config.JOBS_DIR.exists() else []
    print("=" * 70)
    print(f"Leftover job containers: {len(left)}   Leftover job folders: {len(jobs_left)}")
    print("(both should be 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

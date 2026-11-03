
import subprocess
from pathlib import Path


def run_ghdl_command(command, working_directory):
    result = subprocess.run(
        command,
        cwd=working_directory,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        shell=False,
    )

    return {
        "success": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def analyze_vhdl(working_directory, filenames):
    command = [
        "docker", "run", "--rm",
        "-v", f"{Path(working_directory).resolve()}:/work",
        "-w", "/work",
        "group5a-ghdl",
        "ghdl", "-a", "--std=08",
        *filenames,
    ]

    return run_ghdl_command(command, working_directory)


def elaborate_vhdl(working_directory, top_entity):
    command = [
        "docker", "run", "--rm",
        "-v", f"{Path(working_directory).resolve()}:/work",
        "-w", "/work",
        "group5a-ghdl",
        "ghdl", "-e", "--std=08",
        top_entity
    ]

    return run_ghdl_command(command, working_directory)


def simulate_vhdl(working_directory, top_entity):
    command = [
        "docker", "run", "--rm",
        "-v", f"{Path(working_directory).resolve()}:/work",
        "-w", "/work",
        "group5a-ghdl",
        "ghdl", "-r", "--std=08",
        top_entity,
        "--stop-time=50ns",
        "--vcd=wave.vcd"
    ]

    return run_ghdl_command(command, working_directory)

def execute_simulation(working_directory, filenames, top_entity):
    stages = [
        ("analysis", lambda: analyze_vhdl(working_directory, filenames)),
        ("elaboration", lambda: elaborate_vhdl(working_directory, top_entity)),
        ("simulation", lambda: simulate_vhdl(working_directory, top_entity)),
    ]

    results = {}

    for stage_name, run_stage in stages:
        result = run_stage()
        results[stage_name] = result

        if not result["success"]:
            return {
                "success": False,
                "failed_stage": stage_name,
                "results": results,
            }

    return {
        "success": True,
        "failed_stage": None,
        "vcd_file": str(Path(working_directory) / "wave.vcd"),
        "results": results,
    }

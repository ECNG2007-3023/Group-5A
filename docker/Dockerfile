# P5A GHDL job image.
# Contains only GHDL. No Python, no FastAPI: the API launches this image as one
# short-lived container per job (Milestone 3) and passes the ghdl command in.

FROM ubuntu:24.04

RUN apt-get update \
 && apt-get install -y --no-install-recommends ghdl \
 && rm -rf /var/lib/apt/lists/*

# Jobs run as an unprivileged user, never as root.
RUN useradd --create-home --shell /usr/sbin/nologin p5a

# Each job's VHDL files are mounted here by the execution manager.
WORKDIR /work
RUN chown p5a:p5a /work

USER p5a

# Default command is only a smoke test. The execution manager overrides it,
# e.g. ["ghdl", "-a", "and_gate.vhd"], ["ghdl", "-e", "and_gate_tb"],
# ["ghdl", "-r", "and_gate_tb", "--vcd=wave.vcd"].
CMD ["ghdl", "--version"]

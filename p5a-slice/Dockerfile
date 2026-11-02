# P5A GHDL Execution Service: Python + FastAPI + GHDL in one image.
FROM ubuntu:24.04

RUN apt-get update \
 && apt-get install -y --no-install-recommends ghdl python3 python3-venv \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r requirements.txt
COPY app ./app

# Jobs run as an unprivileged user, never as root.
RUN useradd --create-home p5a
USER p5a
ENV P5A_STAGE_TIMEOUT_S=10

EXPOSE 8000
CMD ["/venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

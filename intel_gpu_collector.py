#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error

# --- Configuration ---
# For InfluxDB v2: "http://localhost:8086/api/v2/write?org=YOUR_ORG&bucket=YOUR_BUCKET&precision=ns"
# For InfluxDB v1: "http://localhost:8086/write?db=YOUR_DB&precision=ns"
# For VictoriaMetrics: "http://localhost:8428/write"
WRITE_URL = os.getenv("TSDB_WRITE_URL", "http://localhost:8086/api/v2/write?org=myorg&bucket=metrics&precision=ns")
AUTH_TOKEN = os.getenv("TSDB_TOKEN", "")  # Set for InfluxDB v2 ("Token YOUR_TOKEN") or Basic auth; leave empty if unused
HOST_TAG = socket.gethostname()
SAMPLE_MS = "30000"


def escape_tag(val: str) -> str:
    return str(val).replace(" ", r"\ ").replace(",", r"\,").replace("=", r"\=")


def to_line_protocol(sample: dict, timestamp_ns: int) -> str:
    lines = []
    base_tags = f"host={escape_tag(HOST_TAG)}"

    # 1. Frequency (MHz)
    if "frequency" in sample:
        freq = sample["frequency"]
        lines.append(
            f"intel_gpu_frequency,{base_tags} "
            f"requested={float(freq.get('requested', 0))},actual={float(freq.get('actual', 0))} {timestamp_ns}"
        )

    # 2. Power (Watts)
    if "power" in sample:
        pwr = sample["power"]
        lines.append(
            f"intel_gpu_power,{base_tags} "
            f"gpu={float(pwr.get('GPU', 0))},package={float(pwr.get('Package', 0))} {timestamp_ns}"
        )

    # 3. RC6 Residency (%) & Interrupts (/s)
    rc6 = sample.get("rc6", {}).get("value")
    irq = sample.get("interrupts", {}).get("count")
    if rc6 is not None or irq is not None:
        fields = []
        if rc6 is not None:
            fields.append(f"rc6={float(rc6)}")
        if irq is not None:
            fields.append(f"interrupts={float(irq)}")
        lines.append(f"intel_gpu_general,{base_tags} {','.join(fields)} {timestamp_ns}")

    # 4. IMC Memory Bandwidth (MiB/s)
    if "imc-bandwidth" in sample:
        imc = sample["imc-bandwidth"]
        lines.append(
            f"intel_gpu_imc,{base_tags} "
            f"reads={float(imc.get('reads', 0))},writes={float(imc.get('writes', 0))} {timestamp_ns}"
        )

    # 5. Engines (Render/3D, Blitter, Video, VideoEnhance)
    for engine_name, metrics in sample.get("engines", {}).items():
        etag = escape_tag(engine_name)
        busy = float(metrics.get("busy", 0))
        sema = float(metrics.get("sema", 0))
        wait = float(metrics.get("wait", 0))
        lines.append(
            f"intel_gpu_engine,{base_tags},engine={etag} "
            f"busy={busy},sema={sema},wait={wait} {timestamp_ns}"
        )

    return "\n".join(lines)


def send_metrics(payload: str) -> None:
    if not payload:
        return
    headers = {"Content-Type": "text/plain; charset=utf-8"}
    if AUTH_TOKEN:
        headers["Authorization"] = AUTH_TOKEN

    req = urllib.request.Request(WRITE_URL, data=payload.encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 204):
                print(f"Unexpected HTTP status: {resp.status}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"Failed to write metrics: {e}", file=sys.stderr)


def stream_intel_gpu_top():
    cmd = ["intel_gpu_top", "-J", "-s", SAMPLE_MS]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

    decoder = json.JSONDecoder()
    buffer = ""
    first_sample = True

    try:
        while True:
            chunk = proc.stdout.read(1024)
            if not chunk:
                break
            buffer += chunk

            while True:
                # Strip leading array bracket, whitespace, and commas between objects
                buffer = buffer.lstrip(" \t\r\n[,")
                if not buffer:
                    break
                try:
                    obj, idx = decoder.raw_decode(buffer)
                    buffer = buffer[idx:]

                    if first_sample:
                        first_sample = False
                        continue

                    ts_ns = time.time_ns()
                    lp = to_line_protocol(obj, ts_ns)
                    send_metrics(lp)
                except json.JSONDecodeError:
                    # Incomplete JSON object in buffer; wait for more stdout
                    break
    finally:
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    stream_intel_gpu_top()

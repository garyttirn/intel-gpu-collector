# Intel GPU Top Collector for InfluxDB & VictoriaMetrics

A lightweight, zero-dependency Python daemon that streams real-time metrics from `intel_gpu_top -J` and writes them via **InfluxDB Line Protocol** over HTTP.

Because it writes standard InfluxDB Line Protocol, it works out of the box with **InfluxDB v1**, **InfluxDB v2**, and **VictoriaMetrics** (which natively ingests InfluxDB `/write` payloads).

Created with Gemini

## Features

* **Zero external Python dependencies:** Uses only Python 3's standard library (`subprocess`, `json`, `urllib`, `argparse`).
* **Streaming JSON parser:** Incrementally decodes `intel_gpu_top -J`'s continuous, non-closing JSON array without restarting the process every interval.
* **Accurate sampling:** Automatically discards the first near-zero startup sample emitted by `intel_gpu_top`.
* **Least-privilege systemd support:** Runs as an unprivileged user (`nobody`) using `CAP_PERFMON`.
* **Built-in debug & dry-run modes:** Inspect raw parsed JSON and generated Line Protocol payloads directly from the CLI or `journalctl`.

---

## Metrics Collected

All measurements include the `host=<hostname>` tag.

| Measurement | Tags | Fields | Description |
| :--- | :--- | :--- | :--- |
| `intel_gpu_engine` | `host`, `engine` | `busy`, `sema`, `wait` | Per-engine utilization % (`Render/3D`, `Blitter`, `Video`, `VideoEnhance`, etc.) |
| `intel_gpu_frequency` | `host` | `actual`, `requested` | GPU clock frequencies in MHz |
| `intel_gpu_power` | `host` | `gpu`, `package` | RAPL power consumption in Watts *(hardware-dependent)* |
| `intel_gpu_general` | `host` | `rc6`, `interrupts` | RC6 power-saving sleep residency (%) and interrupts/sec |
| `intel_gpu_imc` | `host` | `reads`, `writes` | Integrated Memory Controller bandwidth in MiB/s *(hardware-dependent)* |

---

## Prerequisites

* **Linux kernel >= 5.8** (for `CAP_PERFMON`; older kernels can use `CAP_SYS_ADMIN`)
* **`intel-gpu-tools`** (`intel_gpu_top` installed at `/usr/bin/intel_gpu_top`):
  ```bash
  # Debian / Ubuntu
  sudo apt install intel-gpu-tools

  # Fedora / RHEL
  sudo dnf install igt-gpu-tools

  # Arch Linux
  sudo pacman -S intel-gpu-tools
  ```
* **Python 3.7+**

---

## Installation

### 1. Install the Collector Script

```bash
sudo cp intel_gpu_collector.py /usr/local/sbin/intel_gpu_collector.py
sudo chmod 755 /usr/local/sbin/intel_gpu_collector.py
```

### 2. Configure the Environment File

Create `/etc/default/intel-gpu-collector`:

```bash
sudo tee /etc/default/intel-gpu-collector > /dev/null <<'EOF'
# --- Target Endpoint (choose one) ---

# InfluxDB v1
TSDB_WRITE_URL="http://localhost:8086/write?db=metrics&precision=ns"

# InfluxDB v2
# TSDB_WRITE_URL="http://localhost:8086/api/v2/write?org=myorg&bucket=metrics&precision=ns"

# VictoriaMetrics
# TSDB_WRITE_URL="http://localhost:8428/write"

# --- Authentication (Optional) ---
# InfluxDB v1 Basic Auth: echo -n "user:pass" | base64 -> "Basic <base64>"
# InfluxDB v2 Token Auth: "Token <your-api-token>"
TSDB_TOKEN=""

# --- Sampling & Debugging ---
SAMPLE_MS="30000"
DEBUG="0"
EOF

sudo chmod 600 /etc/default/intel-gpu-collector
```

### 3. Install & Enable the Systemd Service

Create `/etc/systemd/system/intel-gpu-collector.service`:

```ini
[Unit]
Description=Intel GPU Top Metrics Collector for InfluxDB / VictoriaMetrics
After=network-online.target influxdb.service
Wants=network-online.target

[Service]
Type=simple
User=nobody
Group=nogroup
EnvironmentFile=/etc/default/intel-gpu-collector
ExecStart=/usr/bin/python3 -u /usr/local/bin/intel_gpu_collector.py

# Grant GPU performance counter access without running as root
AmbientCapabilities=CAP_PERFMON
CapabilityBoundingSet=CAP_PERFMON

Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

> **Note:** On RHEL/Fedora/CentOS, change `Group=nogroup` to `Group=nobody`.

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now intel-gpu-collector.service
```

---

## Debugging & CLI Usage

You can run the script interactively with `--debug` and `--dry-run` to inspect the JSON output from `intel_gpu_top` and verify the Line Protocol formatting without writing to your database:

```bash
sudo /usr/local/bin/intel_gpu_collector.py --debug --dry-run --sample-ms 2000
```

### CLI Options

| Flag | Environment Variable | Default | Description |
| :--- | :--- | :--- | :--- |
| `--debug` | `DEBUG=1` | `0` | Print parsed JSON samples, Line Protocol payloads, and HTTP responses to `stderr` |
| `--dry-run` | — | `false` | Parse and log metrics without sending HTTP POST requests |
| `--sample-ms` | `SAMPLE_MS` | `30000` | Sampling interval in milliseconds |

To temporarily enable debug logging on the running systemd service:

1. Set `DEBUG="1"` in `/etc/default/intel-gpu-collector`.
2. Restart and follow logs:
   ```bash
   sudo systemctl restart intel-gpu-collector.service
   sudo journalctl -u intel-gpu-collector.service -f
   ```

---

## Migrating to VictoriaMetrics

VictoriaMetrics natively supports the InfluxDB `/write` endpoint:

1. Edit `/etc/default/intel-gpu-collector`:
   ```bash
   TSDB_WRITE_URL="http://localhost:8428/write"
   TSDB_TOKEN=""
   ```
2. Restart the service:
   ```bash
   sudo systemctl restart intel-gpu-collector.service
   ```

VictoriaMetrics automatically maps measurements and fields to Prometheus-style metrics (e.g., `intel_gpu_engine_busy{host="...",engine="Render/3D"}`).

---

## Grafana Dashboard (Grafana 13+)

1. In Grafana, navigate to **Dashboards → New → Import**.
2. Paste the contents of `grafana-dashboard.json` (or upload the file) and click **Load**.
3. Select your **InfluxDB** data source from the **Data Source** dropdown at the top of the dashboard.
4. *(Recommended)* In your Grafana InfluxDB data source settings, set **Min time interval** to `30s` to match `SAMPLE_MS=30000` and avoid empty intervals when zooming in.

---

## License

MIT

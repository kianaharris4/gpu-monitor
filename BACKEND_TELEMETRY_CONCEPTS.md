# Backend telemetry concepts

This dashboard does not talk to the GPU directly. The backend selects a platform-specific collector, runs the safest available vendor or OS telemetry command, normalizes the result into one `GPUSnapshot`, and sends that snapshot to the browser.

The goal is not to force every device through one command. GPU telemetry is exposed differently across Windows, Linux, discrete GPUs, integrated GPUs, and Jetson SoCs, so the backend chooses the source that best matches the device.

## Backend flow

1. `collectors/factory.py` detects the host platform and available telemetry tools.
2. The selected collector gathers one sample per poll cycle.
3. The collector returns a `GPUSnapshot` from `schema.py`.
4. `main.py` sends snapshots over WebSocket and exposes an HTTP polling fallback.
5. The dashboard renders available fields and displays informational gaps for fields the source cannot provide.

## Collector selection

| Device or environment | Primary collector | Main telemetry source | Best fit |
| --- | --- | --- | --- |
| Windows PC with Intel, NVIDIA, or AMD GPU | `WindowsCollector` | `dxdiag`, Windows GPU performance counters, optional `nvidia-smi` | General Windows laptops/desktops where Windows already exposes adapter metadata and engine counters |
| Linux with discrete NVIDIA GPU | `NvidiaCollector` | `nvidia-smi` | Desktop/server NVIDIA GPUs using the standard NVIDIA driver and NVML stack |
| NVIDIA Jetson | `JetsonCollector` | `tegrastats` | Jetson boards where the GPU is part of the Tegra/Jetson SoC |
| Linux with Intel integrated GPU | `IntelCollector` | `intel_gpu_top` | Intel iGPU systems such as NUCs, laptops, and mini PCs |
| AMD GPU | `AMDCollector` | Currently minimal placeholder support | Future ROCm/AMD telemetry integration |
| Unsupported or missing tool | `NullCollector` | No command; emits explanatory gaps | Systems where the GPU or telemetry command cannot be detected |

## Why these commands are used

| Command or source | Why the backend uses it | What it can provide | Common limitations |
| --- | --- | --- | --- |
| `nvidia-smi` | It is the standard CLI over NVIDIA Management Library for discrete NVIDIA GPUs. | GPU name, utilization, memory, temperature, power, clocks, and process memory on supported drivers. | Usually does not cover Jetson SoC GPUs; requires NVIDIA driver utilities and a loaded driver. |
| `tegrastats` | It is the Jetson-native telemetry tool included with JetPack/L4T environments. | Jetson GPU utilization such as `GR3D` or `GR3D_FREQ`, unified RAM usage, temperature/power strings when exposed. | Output varies by Jetson model and JetPack version; not all fields are present on every board, and parsing may need to accommodate multiple `GR3D` output variants. |
| `intel_gpu_top` | It is the Intel iGPU telemetry tool from `intel-gpu-tools`, and it exposes engine busy data that generic Linux tools often do not. | Aggregate/engine utilization, per-client/process activity when available, and engine-specific busy percentages. | Often requires render/video group access, `cap_perfmon`, or relaxed `perf_event_paranoid` settings. Memory is usually shared system memory rather than dedicated VRAM. |
| `dxdiag` | It is a built-in Windows diagnostic command that reliably reports adapter names, vendor metadata, driver information, and display devices. | GPU name, driver version, adapter metadata. | It is metadata-oriented, not a rich live telemetry source. |
| Windows GPU performance counters | They are the native Windows source for live GPU engine activity. | Engine utilization and process-linked GPU activity when counters map cleanly. | Counter names and adapter mappings can be inconsistent across vendors, drivers, and Windows versions. |
| `nvidia-smi` on Windows | Used as a fallback/richer source when a Windows NVIDIA adapter is present. | NVIDIA aggregate utilization and other NVIDIA-specific metrics. | Only works if the NVIDIA utilities are installed and visible to the dashboard process. |

## Why Jetson uses `tegrastats` instead of `nvidia-smi`

Jetson devices are NVIDIA GPUs, but they are not the same class of device as a PCIe RTX, A-series, or datacenter GPU. A Jetson GPU is integrated into a Tegra/Jetson SoC and shares board-level thermal, power, and memory domains.

`nvidia-smi` is designed around the NVIDIA Management Library path used by standard discrete NVIDIA GPUs. Jetson platforms typically expose their live board/GPU telemetry through Jetson Linux tools such as `tegrastats`, plus model-specific kernel interfaces. Because of that, `tegrastats` is the reliable baseline for Jetson, while `nvidia-smi` is the reliable baseline for discrete NVIDIA GPUs.

In short:

| NVIDIA device type | Preferred command | Reason |
| --- | --- | --- |
| Discrete NVIDIA GPU on Windows/Linux | `nvidia-smi` | Standard driver/NVML telemetry path |
| NVIDIA Jetson SoC | `tegrastats` | Jetson-native telemetry path for SoC GPU, unified memory, thermals, and board data |

## Why one universal command is not used

There is no single cross-vendor command that reports GPU utilization, memory, power, thermals, and per-process activity consistently across all devices. Even when a command exists on multiple systems, the meaning of a metric can differ.

Examples:

| Metric | Why it differs |
| --- | --- |
| GPU memory | Discrete GPUs usually report dedicated VRAM. Integrated GPUs and Jetsons often use shared or unified system memory. |
| Utilization | NVIDIA reports aggregate GPU utilization; Intel often reports engine busy percentages; Windows reports per-engine counters. |
| Power draw | Discrete GPUs may expose board power. Integrated GPUs may not expose package-specific GPU power. Jetson may expose SoC/rail-specific readings. |
| Per-process usage | Some sources report process memory but not process GPU percent. Others report client/engine activity but not dedicated VRAM. |

The dashboard therefore normalizes what exists and shows gaps for what the current telemetry source cannot provide.

## How missing data is handled

Collectors should not crash the dashboard when a metric is unavailable. Instead, they fill:

| Snapshot field | Purpose |
| --- | --- |
| `sources` | Explains which command or OS source populated a metric. |
| `gaps` | Explains why a metric is missing or partial. |
| `caps` | Describes known capabilities for the selected device/source. |

The frontend uses those fields to show informational messages such as missing drivers, missing permissions, unsupported process attribution, or telemetry fields that the vendor source does not expose. In the current Azure-style UI, these messages appear in the telemetry banner below the GPU selector and above the Properties section.

For a concrete list of user-facing messages and fixes, see [TELEMETRY_TROUBLESHOOTING.md](TELEMETRY_TROUBLESHOOTING.md).

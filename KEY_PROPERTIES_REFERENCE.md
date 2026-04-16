# Key Properties Reference

The **Key properties** section summarizes the selected GPU snapshot returned by the active collector. Values can vary by platform, driver, permissions, and vendor telemetry support. When a collector cannot provide a field, the dashboard usually displays `--`, `N/A`, or an informational telemetry banner.

## Overview Key Properties

| Key property | Backing field or expression | Possible values | What it means |
| --- | --- | --- | --- |
| `GPU` | `device_name` | A detected adapter name such as `NVIDIA GeForce RTX 4050 Laptop GPU`, `Intel(R) Iris(R) Xe Graphics`, `NVIDIA Jetson`, `NVIDIA telemetry unavailable`, `No supported GPU detected`, or `--` | The selected GPU or placeholder device name. `--` means the collector did not provide a name. Placeholder names are used so the UI can still explain why telemetry is missing. |
| `PCI location` | `pcie_info`, then `bus_id`, otherwise `Integrated` | PCI/PCIe location text, NVIDIA bus IDs such as `00000000:01:00.0`, `Integrated`, or `--` | Identifies where the GPU is attached. `Integrated` is used when no discrete PCI bus ID is available, which is common for integrated GPUs or some Windows/UMA devices. |
| `Memory type` | `memory.mem_model`, displayed through `memLabel()` | `Dedicated (VRAM)`, `Unified (SoC Memory)`, `Shared (System Memory)`, or `--` | Describes the memory architecture. Dedicated means separate GPU VRAM. Unified means SoC memory shared between CPU/GPU, common on Jetson. Shared means system RAM used by an integrated/mobile GPU. |
| `Driver name` | `vendor` formatted as `<VENDOR> driver` | `NVIDIA driver`, `INTEL driver`, `AMD driver`, `UNKNOWN driver`, or `--` | A friendly driver label derived from the detected vendor. It does not necessarily name the exact kernel module or Windows driver package. |
| `Driver version` | `driver_version` | Vendor version strings such as NVIDIA driver versions, Windows `dxdiag` driver versions, or `--` | The driver version reported by the active collector. Availability depends on collector support and driver tooling. |
| `Dedicated VRAM present` | `memory.mem_model === "dedicated"` | `True` or `False` | `True` means the selected GPU snapshot reports dedicated VRAM. `False` includes shared-memory integrated GPUs, unified-memory SoCs, and fallback snapshots with no dedicated VRAM. |
| `Last checked` | `timestamp` formatted in local time | A local date/time such as `Apr 16, 2026, 2:34:12 PM` | The time the displayed snapshot was last pulled by the dashboard. This is the latest collector sample time, not the selected time-filter range. |

## Memory Type Values

| Raw value | Displayed value | Typical devices | Notes |
| --- | --- | --- | --- |
| `dedicated` | `Dedicated (VRAM)` | Discrete NVIDIA, AMD, and some Windows discrete adapters | Memory is physically separate GPU VRAM. |
| `unified` | `Unified (SoC Memory)` | NVIDIA Jetson and other SoC-style devices | CPU and GPU share one memory pool. |
| `shared` | `Shared (System Memory)` | Intel integrated GPUs, many laptop iGPUs, fallback snapshots | Memory is estimated from system RAM or OS counters rather than dedicated GPU VRAM. |

## Common Placeholder Values

| Value | Where it can appear | Meaning |
| --- | --- | --- |
| `--` | GPU, driver version, driver name, memory type | The active collector did not provide that field. |
| `N/A` | Metric panels and some detail views | The field is known to be unsupported or unavailable from the telemetry source. |
| `Integrated` | PCI location | No PCIe/bus identifier was provided, so the dashboard treats the adapter as integrated or non-discrete. |
| `False` for dedicated VRAM | Dedicated VRAM present | The memory model is not `dedicated`; this can be normal for Intel iGPUs and Jetson unified-memory devices. |

## Collector Notes

| Collector path | Key property behavior |
| --- | --- |
| Windows collector | GPU names and driver versions come from `dxdiag`. NVIDIA live telemetry may be enriched with `nvidia-smi`. Integrated GPUs often show `Integrated` for PCI location and `Shared (System Memory)` for memory type. |
| NVIDIA collector | GPU name, utilization, temperature, power, and memory come from `nvidia-smi`. Per-process details are not currently collected from this path. |
| Jetson collector | Device name is generally `NVIDIA Jetson`; memory is typically `Unified (SoC Memory)` from `tegrastats`. |
| Intel Linux collector | GPU name is derived from `lspci` or `/sys/class/drm` when available. Memory is `Shared (System Memory)`. If device metadata is unavailable, the dashboard may use a generic Intel GPU name. |
| Null/fallback collector | Uses placeholder names such as `NVIDIA telemetry unavailable` or `No supported GPU detected` and emits telemetry availability messages explaining what is missing. |


# Device Metric Source Map

This document explains, for three concrete device examples, where each major dashboard metric comes from in the backend and which `GPUSnapshot` field the frontend actually reads.

The three examples covered here are:

- Intel NUC on Linux using the Intel iGPU collector
- NVIDIA Jetson using the Jetson collector
- Linux device with an NVIDIA discrete GPU using the NVIDIA collector

Assumption:

- "NUC" here means the Linux Intel iGPU path implemented in `collectors/intel.py`.
- If you want, we can add a separate section later for a Windows NUC path from `collectors/windows.py`.

## Common Dashboard Contract

All collectors emit a unified `GPUSnapshot` object defined in [schema.py](schema.py).

The key fields relevant to this document are:

- `device_name`
- `bus_id`
- `pcie_info`
- `util_pct`
- `vendor`
- `driver_version`
- `memory.mem_model`
- `memory.total_mb`
- `memory.used_mb`
- `memory.host_total_mb`
- `memory.host_used_mb`
- `temp_c`
- `power_w`
- `sources`
- `gaps`

The main frontend readers are in [gpu_monitor_dashboard.html](gpu_monitor_dashboard.html):

- `formatPciLocation(s)` for PCI location
- `updateKPI(s)` for top KPI cards
- `pushOvHist(s)` for the overview trend history
- `updateOverviewMetrics(s)` for overview current values
- `updateThermalPowerCards(s)` for temperature and power cards
- `updateMemoryTab(s)` for the memory tab
- `deviceInfoRows(s)` for the Properties panel

Important frontend memory helpers:

- `memoryTotalMb(m)` prefers `memory.total_mb`, then falls back to `memory.host_total_mb`
- `memoryUsedMb(m)` prefers `memory.used_mb`, then `memory.process_used_mb`, then `memory.host_used_mb`
- `memoryUsagePct(m)` computes `(used / total) * 100` using those helpers

That means the dashboard is not always showing raw `memory.total_mb` directly anymore; it now uses the fallback helpers for memory charts and summaries.

---

## 1. Intel NUC Example

Collector: [collectors/intel.py](collectors/intel.py)

### Backend sources used

- GPU identity:
  - `lspci` if available
  - otherwise `/sys/class/drm/.../device`
- GPU utilization:
  - `intel_gpu_top` JSON mode first
  - `intel_gpu_top` text fallback second
- Memory:
  - `/proc/meminfo`
- Temperature:
  - DRM `hwmon` preferred
  - thermal zones fallback if a GPU/GT thermal zone exists
- Power:
  - DRM `hwmon` when the kernel exposes a GPU power reading

### Metric-by-metric map

| Dashboard metric | Frontend field used | Collector field populated | Backend source | Backend field/token name used | Exact backend key/value used |
| --- | --- | --- | --- | --- | --- |
| GPU name | `s.device_name` | `snap.device_name` | `lspci` or sysfs | `device["name"]` | `lspci` line text after bus ID, or sysfs-derived fallback like `Intel GPU (PCI_ID=...)` |
| PCI location | `formatPciLocation(s)` reads `s.pcie_info` then `s.bus_id` | `snap.bus_id`, `snap.pcie_info` | `lspci` or sysfs | `device["bus_id"]` | `device["bus_id"]` from `_find_intel_device_*()` |
| Memory type | `essentialsMemoryType(m)` | `snap.memory.mem_model`, `snap.memory.total_mb` | `/proc/meminfo` | `MemTotal` | `mem_model="unified"` plus `MemTotal` converted to `total_mb` |
| Driver name | `s.vendor ? \`${String(s.vendor).toUpperCase()} driver\` : '--'` | `snap.vendor` | collector constant | `vendor` | `vendor="intel"` hard-coded in `GPUSnapshot(vendor="intel", ...)` |
| Driver version | `s.driver_version` | not populated | none | none | remains `None` |
| Dedicated VRAM present | `m?.mem_model === 'dedicated' ? 'True' : 'False'` | `snap.memory.mem_model` | `/proc/meminfo` plus collector model choice | `mem_model` | `mem_model="unified"` so the displayed value is `False` |
| GPU usage | `s.util_pct` | `snap.util_pct` | `intel_gpu_top` | JSON keys such as `busy`, `busy%`, `busy %`, `sema busy`, `wait`; text `%` columns on engine lines | Highest busy percentage discovered by `_extract_busy_values()` from JSON keys like `busy`, `busy%`, `busy %`, `sema busy`, `wait`; or fallback parsed `%` values from text output |
| Memory usage | `memoryUsagePct(s.memory)`, `ov-current-mem`, `k-mem`, memory tab | `snap.memory.total_mb`, `snap.memory.used_mb`, `snap.memory.host_total_mb`, `snap.memory.host_used_mb` | `/proc/meminfo` | `MemTotal`, `MemAvailable`, fallback `MemFree` | `MemTotal` and `MemAvailable` or `MemFree`; used memory is `MemTotal - MemAvailable` |
| Temperature | `s.temp_c` | `snap.temp_c` when available | DRM `hwmon` preferred, thermal zones fallback | `temp*_input`; fallback thermal-zone `temp` when `type` mentions GPU/GT/graphics | `temp*_input` under `/sys/class/drm/card*/device/hwmon/hwmon*`; fallback `/sys/class/thermal/thermal_zone*/temp` when the zone type includes `gpu`, `gt`, or `graphics` |
| Power draw | `s.power_w` | `snap.power_w` when available | DRM `hwmon` | `power1_average`, fallback `power1_input` | `power1_average` or `power1_input` under `/sys/class/drm/card*/device/hwmon/hwmon*` |

### Intel-specific implementation notes

#### GPU name

The collector tries `_find_intel_device_from_lspci()` first.

- It looks for an `lspci` line containing:
  - `intel`
  - and one of:
    - `vga compatible controller`
    - `display controller`
    - `3d controller`
- It stores:
  - `snap.device_name = device.get("name")`
  - `snap.bus_id = device.get("bus_id")`
  - `snap.pcie_info = device.get("bus_id")`

If `lspci` is unavailable, `_find_intel_device_from_sysfs()` falls back to `/sys/class/drm`.

#### GPU usage

Primary path:

- `_read_intel_gpu_top_json()`
- `_extract_busy_values(data)`
- `snap.util_pct = max(busy_values)`

The JSON parser treats these names as utilization-bearing keys:

- `busy`
- `busy%`
- `busy %`
- `sema busy`
- `wait`

Fallback path:

- `_read_intel_gpu_top_text()`
- `_extract_text_util(output)`

That fallback extracts `%` values from lines mentioning engines like:

- `render`
- `video`
- `blitter`
- `compute`
- `copy`
- `3d`

#### Memory usage

Intel memory is modeled as shared/unified host memory, not dedicated VRAM.

The collector does:

- `total_kb = MemTotal`
- `avail_kb = MemAvailable` or `MemFree`
- `used_kb = total_kb - avail_kb`

Then sets:

- `snap.memory.mem_model = "unified"`
- `snap.memory.total_mb = total_kb / 1024`
- `snap.memory.used_mb = used_kb / 1024`
- `snap.memory.host_total_mb = same total`
- `snap.memory.host_used_mb = same used`

#### Temperature and power

The collector now probes Intel DRM sysfs/hwmon for both values.

Temperature path:

- preferred: `/sys/class/drm/card*/device/hwmon/hwmon*/temp*_input`
- fallback: `/sys/class/thermal/thermal_zone*/temp` when the thermal zone type mentions `gpu`, `gt`, or `graphics`

Power path:

- `/sys/class/drm/card*/device/hwmon/hwmon*/power1_average`
- fallback: `/sys/class/drm/card*/device/hwmon/hwmon*/power1_input`

If those interfaces are missing, the collector leaves the values unset and records:

- `snap.gaps["temperature"] = "Intel Linux GPU temperature telemetry was not exposed under DRM hwmon or thermal interfaces."`
- `snap.gaps["power"] = "Intel Linux GPU power telemetry was not exposed under DRM hwmon interfaces."`

### What the dashboard actually shows for a NUC

- Properties -> GPU: `snap.device_name`
- Properties -> PCI location: `formatPciLocation(s)` using `pcie_info`/`bus_id`
- Properties -> Memory type: `Unified (<total> GB)` built from `memory.mem_model` and `memory.total_mb`
- Properties -> Driver name: `INTEL driver` from `vendor="intel"`
- Properties -> Driver version: `--` because `snap.driver_version` is not populated here
- Properties -> Dedicated VRAM present: `False` because `memory.mem_model !== 'dedicated'`
- Overview -> GPU usage chart: `snap.util_pct`
- Overview -> Memory usage chart: percentage derived from `memory.total_mb` and `memory.used_mb`
- Temperature card: DRM `hwmon` or thermal-zone temperature when exposed; otherwise `N/A`
- Power draw card: DRM `hwmon` GPU power when exposed; otherwise `N/A`

---

## 2. NVIDIA Jetson Example

Collector: [collectors/jetson.py](collectors/jetson.py)

### Backend sources used

- GPU identity / driver / PCI metadata:
  - `nvidia-smi`
- GPU utilization:
  - `tegrastats` preferred when available
  - `nvidia-smi` fallback
- Memory:
  - `tegrastats` preferred when available
  - `nvidia-smi` fallback
  - `/proc/meminfo` fallback when Jetson unified memory is only exposed as shared system RAM
- Temperature:
  - `nvidia-smi` first
  - `tegrastats` fills only if `nvidia-smi` did not
- Power:
  - `nvidia-smi` first
  - `tegrastats` fills only if `nvidia-smi` did not

### Metric-by-metric map

| Dashboard metric | Frontend field used | Collector field populated | Backend source | Backend field/token name used | Exact backend key/value used |
| --- | --- | --- | --- | --- | --- |
| GPU name | `s.device_name` | `snap.device_name` | `nvidia-smi` | `name` | `--query-gpu=name` |
| PCI location | `formatPciLocation(s)` reads `s.pcie_info` then `s.bus_id` | `snap.bus_id`, `snap.pcie_info` | `nvidia-smi` | `pci.bus_id` | `--query-gpu=pci.bus_id` |
| Memory type | `essentialsMemoryType(m)` | `snap.memory.mem_model`, `snap.memory.total_mb` | `tegrastats` preferred, else `nvidia-smi`, else `/proc/meminfo` | tegrastats `RAM used/total`; fallback `memory.total`; final fallback `MemTotal` | `mem_model="unified"` plus either tegrastats `RAM used/total` total, fallback `--query-gpu=memory.total`, or fallback `/proc/meminfo MemTotal` |
| Driver name | `s.vendor ? \`${String(s.vendor).toUpperCase()} driver\` : '--'` | `snap.vendor` | collector constant | `vendor` | `vendor="nvidia"` from `GPUSnapshot(...)` |
| Driver version | `s.driver_version` | `snap.driver_version` | `nvidia-smi` | `driver_version` | `--query-gpu=driver_version` |
| Dedicated VRAM present | `m?.mem_model === 'dedicated' ? 'True' : 'False'` | `snap.memory.mem_model` | collector model choice | `mem_model` | `mem_model="unified"` so the displayed value is `False` |
| GPU usage | `s.util_pct` | `snap.util_pct` | `tegrastats` preferred, else `nvidia-smi` | tegrastats `GR3D` or `GR3D_FREQ`; fallback `utilization.gpu` | `GR3D` / `GR3D_FREQ` percentage from tegrastats regex; fallback `--query-gpu=utilization.gpu` |
| Memory usage | `memoryUsagePct(s.memory)` and memory summaries | `snap.memory.total_mb`, `snap.memory.used_mb` | `tegrastats` preferred, else `nvidia-smi`, else `/proc/meminfo` | tegrastats `RAM used/total`; fallback `memory.used`, `memory.total`; final fallback `MemTotal`, `MemAvailable` or `MemFree` | tegrastats `RAM used/total`; fallback `--query-gpu=memory.used,memory.total`; final fallback `/proc/meminfo` where used is `MemTotal - MemAvailable` |
| Temperature | `s.temp_c` | `snap.temp_c` | `nvidia-smi` first, tegrastats second | `temperature.gpu`; fallback tegrastats `GPU@...C` or `GPU0@...C` | `--query-gpu=temperature.gpu`; tegrastats regex `GPU@xxC` or `GPU0@xxC` |
| Power draw | `s.power_w` | `snap.power_w` | `nvidia-smi` first, tegrastats second | `power.draw`; fallback tegrastats `POM_5V_GPU`, `VDD_GPU_SOC`, or `VDD_GPU` | `--query-gpu=power.draw`; tegrastats `POM_5V_GPU`, `VDD_GPU_SOC`, or `VDD_GPU` in mW |

### Jetson precedence details

#### 1. `nvidia-smi` metadata is loaded first

`_load_nvidia_smi_metadata()` queries:

- `index`
- `name`
- `driver_version`
- `pci.bus_id`
- `utilization.gpu`
- `temperature.gpu`
- `power.draw`
- `power.limit`
- `memory.used`
- `memory.total`

Those values are written into:

- `snap.gpu_index`
- `snap.device_name`
- `snap.driver_version`
- `snap.bus_id`
- `snap.pcie_info`
- `snap.util_pct` if not already set
- `snap.temp_c` if not already set
- `snap.power_w` if not already set
- `snap.power_limit_w` if not already set
- `snap.memory` only if current `memory.total_mb <= 0`

That last point matters: `nvidia-smi` is now a fallback memory source for Jetson when `tegrastats` does not produce usable memory totals.

#### 2. `tegrastats` is loaded second

`_load_tegrastats()` then refines the snapshot.

##### Memory

Regex:

- `RAM\s+(\d+)/(\d+)MB`

If matched:

- `used = first number`
- `total = second number`
- `snap.memory = MemoryInfo(mem_model="unified", used_mb=used, total_mb=total)`

This overrides the previous zero/default memory object and effectively takes precedence over the fallback path.

#### 3. `/proc/meminfo` is loaded as the final memory fallback

If memory is still missing after both `nvidia-smi` and `tegrastats`, the collector reads:

- `MemTotal`
- `MemAvailable`
- fallback `MemFree`

Then it computes:

- `total_mb = MemTotal / 1024`
- `used_mb = (MemTotal - MemAvailable) / 1024`

and stores those as unified-memory values:

- `snap.memory.mem_model = "unified"`
- `snap.memory.total_mb = total_mb`
- `snap.memory.used_mb = used_mb`
- `snap.memory.host_total_mb = total_mb`
- `snap.memory.host_used_mb = used_mb`

This is especially useful on Jetson systems where `nvidia-smi` reports memory as `Not Supported` and `tegrastats` RAM parsing is unavailable or in an unexpected format.

##### GPU usage

Regex patterns accept:

- `GR3D_FREQ 35% @[1098]`
- `GR3D_FREQ 35% @1098`
- `GR3D_FREQ 35%`
- `GR3D 35% @[1098]`
- `GR3D 35% @1098`
- `GR3D 35%`

The percentage is assigned to:

- `snap.util_pct`
So for Jetson, `tegrastats` becomes the preferred live utilization source when present.

##### Temperature

Regex:

- `(?:\bGPU|\bGPU0)@(\d+(?:\.\d+)?)C`

This only writes `snap.temp_c` if it is still `None`.

##### Power

Regex checks, in order:

- `POM_5V_GPU`
- `VDD_GPU_SOC`
- `VDD_GPU`

The current value is read from the first capture group in mW, then divided by `1000.0` into watts.

This only writes `snap.power_w` if it is still `None`.

### What the dashboard actually shows for a Jetson

- Properties -> GPU: usually `nvidia-smi name`
- Properties -> PCI location: `nvidia-smi pci.bus_id` when available
- Properties -> Memory type: `Unified (<total> GB)` from `mem_model="unified"` and the current memory total, sourced from `tegrastats`, `nvidia-smi`, or `/proc/meminfo`
- Properties -> Driver name: `NVIDIA driver` from `vendor="nvidia"`
- Properties -> Driver version: `nvidia-smi driver_version`
- Properties -> Dedicated VRAM present: `False` because `memory.mem_model !== 'dedicated'`
- Overview -> GPU usage chart: usually tegrastats `GR3D/GR3D_FREQ`
- Overview -> Memory usage chart: usually tegrastats `RAM used/total`; fallback to `nvidia-smi memory.used/memory.total`; final fallback to `/proc/meminfo`
- Temperature card: `nvidia-smi temperature.gpu` unless missing, then tegrastats `GPU@...C`
- Power draw card: `nvidia-smi power.draw` unless missing, then tegrastats GPU rail power

---

## 3. Linux Device with NVIDIA dGPU Example

Collector: [collectors/nvidia.py](collectors/nvidia.py)

### Backend sources used

- GPU identity:
  - `nvidia-smi`
- PCI location:
  - `nvidia-smi`
- GPU usage:
  - `nvidia-smi`
- Memory:
  - `nvidia-smi`
- Temperature:
  - `nvidia-smi`
- Power:
  - `nvidia-smi`

### Metric-by-metric map

| Dashboard metric | Frontend field used | Collector field populated | Backend source | Backend field/token name used | Exact backend key/value used |
| --- | --- | --- | --- | --- | --- |
| GPU name | `s.device_name` | `snap.device_name` | `nvidia-smi` | `name` | `--query-gpu=name` |
| PCI location | `formatPciLocation(s)` reads `s.pcie_info` then `s.bus_id` | `snap.bus_id`, `snap.pcie_info` | `nvidia-smi` | `pci.bus_id` | `--query-gpu=pci.bus_id` |
| Memory type | `essentialsMemoryType(m)` | `snap.memory.mem_model`, `snap.memory.total_mb` | `nvidia-smi` | `memory.total` plus collector `mem_model="dedicated"` | `mem_model="dedicated"` plus `--query-gpu=memory.total` |
| Driver name | `s.vendor ? \`${String(s.vendor).toUpperCase()} driver\` : '--'` | `snap.vendor` | collector constant | `vendor` | `vendor="nvidia"` in the collector |
| Driver version | `s.driver_version` | `snap.driver_version` | `nvidia-smi` | `driver_version` | `--query-gpu=driver_version` |
| Dedicated VRAM present | `m?.mem_model === 'dedicated' ? 'True' : 'False'` | `snap.memory.mem_model` | collector model choice | `mem_model` | `mem_model="dedicated"` so the displayed value is `True` |
| GPU usage | `s.util_pct` | `snap.util_pct` | `nvidia-smi` | `utilization.gpu` | `--query-gpu=utilization.gpu` |
| Memory usage | `memoryUsagePct(s.memory)` and memory summaries | `snap.memory.used_mb`, `snap.memory.total_mb` | `nvidia-smi` | `memory.used`, `memory.total` | `--query-gpu=memory.used,memory.total` |
| Temperature | `s.temp_c` | `snap.temp_c` | `nvidia-smi` | `temperature.gpu` | `--query-gpu=temperature.gpu` |
| Power draw | `s.power_w` | `snap.power_w` | `nvidia-smi` | `power.draw` | `--query-gpu=power.draw` |

### NVIDIA dGPU implementation details

The collector issues one main query:

```text
nvidia-smi --query-gpu=index,name,driver_version,pci.bus_id,utilization.gpu,temperature.gpu,power.draw,power.limit,clocks.gr,memory.used,memory.total --format=csv,noheader,nounits
```

Per row, the parsed values map directly to the snapshot:

- `idx` -> `snap.gpu_index`
- `name` -> `snap.device_name`
- `driver_version` -> `snap.driver_version`
- `bus_id` -> `snap.bus_id` and `snap.pcie_info`
- `util` -> `snap.util_pct`
- `temp` -> `snap.temp_c`
- `power` -> `snap.power_w`
- `power_limit` -> `snap.power_limit_w`
- `clock` -> `snap.clock_mhz`
- `mem_used` -> `snap.memory.used_mb`
- `mem_total` -> `snap.memory.total_mb`

The memory model is always set as:

- `snap.memory.mem_model = "dedicated"`

So the dashboard treats this as discrete VRAM.

### What the dashboard actually shows for an NVIDIA dGPU

- Properties -> GPU: `nvidia-smi name`
- Properties -> PCI location: `nvidia-smi pci.bus_id`
- Properties -> Memory type: `Dedicated (<total> GB)` from `mem_model="dedicated"` and `memory.total_mb`
- Properties -> Driver name: `NVIDIA driver` from `vendor="nvidia"`
- Properties -> Driver version: `nvidia-smi driver_version`
- Properties -> Dedicated VRAM present: `True` because `memory.mem_model === 'dedicated'`
- Overview -> GPU usage chart: `nvidia-smi utilization.gpu`
- Overview -> Memory usage chart: `memory.used / memory.total` from `nvidia-smi`
- Temperature card: `nvidia-smi temperature.gpu`
- Power draw card: `nvidia-smi power.draw`

---

## Dashboard Field Reader Summary

This section summarizes which frontend code path consumes each metric.

| Dashboard display | Frontend reader | Snapshot field(s) consumed |
| --- | --- | --- |
| Properties -> GPU | `deviceInfoRows()` | `s.device_name` |
| Properties -> PCI location | `deviceInfoRows()` -> `formatPciLocation()` | `s.pcie_info`, fallback `s.bus_id` |
| Properties -> Memory type | `deviceInfoRows()` -> `essentialsMemoryType(m)` | `m.mem_model`, `m.total_mb` |
| Properties -> Driver name | `deviceInfoRows()` | `s.vendor` |
| Properties -> Driver version | `deviceInfoRows()` | `s.driver_version` |
| Properties -> Dedicated VRAM present | `deviceInfoRows()` | `m.mem_model` |
| Top KPI GPU usage | `updateKPI()` | `s.util_pct` |
| Top KPI GPU memory | `updateKPI()` | `s.memory.used_mb`, `s.memory.total_mb` |
| Overview GPU usage chart | `pushOvHist()` | `s.util_pct` |
| Overview memory chart | `pushOvHist()` -> `memoryUsagePct()` | `memory.total_mb` or `memory.host_total_mb`; `memory.used_mb` or fallback used fields |
| Overview memory current text | `updateOverviewMetrics()` | `memoryTotalMb(m)`, `memoryUsedMb(m)`, `memoryFreeMb(m)` |
| Temperature card | `updateThermalPowerCards()` | `s.temp_c` |
| Power card | `updateThermalPowerCards()` | `s.power_w` |
| Memory tab summary | `updateMemoryTab()` | `memoryTotalMb(m)`, `memoryUsedMb(m)`, `memoryFreeMb(m)`, `memoryUsagePct(m)` |

---

## Short Takeaways

- Intel NUC:
  - GPU identity comes from `lspci` or sysfs
  - utilization comes from `intel_gpu_top`
  - memory comes from `/proc/meminfo`
  - temperature and power are currently not populated

- Jetson:
  - identity mostly comes from `nvidia-smi`
  - utilization and unified memory prefer `tegrastats`
  - temperature and power can come from either `nvidia-smi` or `tegrastats`, depending on availability

- NVIDIA dGPU:
  - the core dashboard metrics in this document all come directly from `nvidia-smi`

If you want, I can follow this with a second markdown file that covers the same mapping for the Windows collector as well.

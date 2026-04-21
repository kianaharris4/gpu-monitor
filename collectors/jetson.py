
import re
import subprocess

from schema import GPUSnapshot, MemoryInfo
from collectors.nvidia import NvidiaCollector, _safe_float, _safe_int

class JetsonCollector:
    def detect(self):
        try:
            subprocess.check_output(["which", "tegrastats"], stderr=subprocess.DEVNULL)
            return True
        except Exception:
            try:
                subprocess.check_output(["which", "nvidia-smi"], stderr=subprocess.DEVNULL)
                return True
            except Exception:
                return False

    def collect(self):
        snap = GPUSnapshot(
            device_name="NVIDIA Jetson",
            vendor="nvidia",
            compute_api="Jetson / CUDA",
            memory=MemoryInfo(mem_model="unified", total_mb=0.0, used_mb=0.0),
        )
        errors = []

        self._load_nvidia_smi_metadata(snap, errors)
        self._load_tegrastats(snap, errors)

        if snap.memory and snap.memory.mem_model != "unified":
            snap.memory.mem_model = "unified"

        if snap.util_pct is None:
            snap.gaps["utilization"] = "GPU utilization requires tegrastats or a Jetson-compatible nvidia-smi output."
        if not snap.memory or (snap.memory.total_mb or 0.0) <= 0:
            snap.gaps["memory"] = "Unified memory telemetry requires tegrastats on NVIDIA Jetson."
        if snap.temp_c is None:
            snap.gaps["temperature"] = "Temperature was not reported by tegrastats or nvidia-smi."
        if snap.power_w is None:
            snap.gaps["power"] = "Power draw was not reported by tegrastats or nvidia-smi."

        if errors and not snap.sources:
            snap.gaps["collector"] = "; ".join(errors)

        return [snap]

    def _load_nvidia_smi_metadata(self, snap, errors):
        try:
            result = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,driver_version,pci.bus_id,utilization.gpu,temperature.gpu,power.draw,power.limit",
                    "--format=csv,noheader,nounits",
                ],
                timeout=5,
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", errors="ignore").strip()
        except Exception as exc:
            errors.append(f"nvidia-smi metadata unavailable: {exc}")
            return

        first_row = next((row for row in result.splitlines() if row.strip()), "")
        parts = [part.strip() for part in first_row.split(",")] if first_row else []
        if len(parts) >= 8:
            idx, name, driver_version, bus_id, util, temp, power, power_limit = parts[:8]
            snap.gpu_index = _safe_int(idx)
            if name and name not in ("N/A", "[N/A]"):
                snap.device_name = name
            if driver_version and driver_version not in ("N/A", "[N/A]"):
                snap.driver_version = driver_version
            if bus_id and bus_id not in ("N/A", "[N/A]"):
                snap.bus_id = bus_id
                snap.pcie_info = bus_id
            if snap.util_pct is None:
                snap.util_pct = _safe_float(util)
            if snap.temp_c is None:
                snap.temp_c = _safe_float(temp)
            if snap.power_w is None:
                snap.power_w = _safe_float(power)
            if snap.power_limit_w is None:
                snap.power_limit_w = _safe_float(power_limit)

            snap.sources["gpu"] = "nvidia-smi"
            snap.sources["driver"] = "nvidia-smi"
            snap.sources["telemetry"] = snap.sources.get("telemetry", "nvidia-smi")
            snap.sources["nvidia_index"] = idx

        processes_by_gpu = NvidiaCollector()._load_processes()
        gpu_index = snap.gpu_index if snap.gpu_index is not None else 0
        snap.processes = processes_by_gpu.get(gpu_index, [])
        if snap.processes:
            process_sources = sorted({proc.gpu_pct_source for proc in snap.processes if proc.gpu_pct_source})
            snap.sources["processes"] = " / ".join(process_sources) if process_sources else "nvidia-smi"
        else:
            snap.gaps["processes"] = "nvidia-smi did not report active per-process GPU usage for this Jetson adapter."

    def _load_tegrastats(self, snap, errors):
        try:
            out = subprocess.check_output(
                ["tegrastats", "--interval", "100", "--count", "1"],
                timeout=5,
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", errors="ignore")
        except Exception as exc:
            errors.append(f"tegrastats failed while collecting telemetry: {exc}")
            return

        snap.sources["telemetry"] = "tegrastats" if "telemetry" not in snap.sources else f"{snap.sources['telemetry']} / tegrastats"

        ram = re.search(r"RAM\s+(\d+)/(\d+)MB", out, re.IGNORECASE)
        if ram:
            used, total = map(float, ram.groups())
            snap.memory = MemoryInfo(
                mem_model="unified",
                used_mb=used,
                total_mb=total,
            )

        gpu = re.search(r"GR3D_FREQ\s+(\d+)%@(?:\[(\d+)(?:,\d+)*\]|(\d+))", out, re.IGNORECASE)
        if gpu:
            snap.util_pct = float(gpu.group(1))
            clock_val = gpu.group(2) or gpu.group(3)
            snap.clock_mhz = _safe_float(clock_val)

        temp = re.search(r"(?:\bGPU|\bGPU0)@(\d+(?:\.\d+)?)C", out, re.IGNORECASE)
        if temp and snap.temp_c is None:
            snap.temp_c = _safe_float(temp.group(1))

        for pattern in (
            r"\bPOM_5V_GPU\s+(\d+)mW(?:/(\d+)mW)?",
            r"\bVDD_GPU_SOC\s+(\d+)mW(?:/(\d+)mW)?",
            r"\bVDD_GPU\s+(\d+)mW(?:/(\d+)mW)?",
        ):
            power = re.search(pattern, out, re.IGNORECASE)
            if not power:
                continue
            if snap.power_w is None:
                snap.power_w = _safe_float(power.group(1))
                if snap.power_w is not None:
                    snap.power_w /= 1000.0
            if snap.power_limit_w is None and power.group(2):
                snap.power_limit_w = _safe_float(power.group(2))
                if snap.power_limit_w is not None:
                    snap.power_limit_w /= 1000.0
            break

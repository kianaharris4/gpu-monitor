
import json
import os
import re
import shutil
import subprocess

from schema import GPUSnapshot, MemoryInfo


class IntelCollector:
    capabilities = {
        "utilization": True,
        "memory": False,
        "power": False,
        "temperature": False,
    }

    def detect(self):
        return self._find_intel_device() is not None

    def collect(self):
        snap = GPUSnapshot(vendor="intel", compute_api="Intel")
        device = self._find_intel_device()

        if device:
            snap.device_name = device.get("name") or "Intel GPU"
            snap.bus_id = device.get("bus_id")
            snap.pcie_info = device.get("bus_id")

        snap.memory = MemoryInfo(mem_model="unified", total_mb=0, used_mb=0)
        snap.sources["gpu"] = "lspci" if device and device.get("source") == "lspci" else "sysfs"
        snap.sources["driver"] = "kernel"
        snap.caps.update({
            "utilization": True,
            "memory": False,
            "power": False,
            "temperature": False,
            "mem_clock": False,
        })

        intel_gpu_top = shutil.which("intel_gpu_top")
        if not intel_gpu_top:
            snap.gaps["utilization"] = "Install intel-gpu-tools to enable live Intel GPU utilization on Linux."
            snap.gaps["memory"] = "Intel Linux UMA memory telemetry is not wired up yet."
            snap.gaps["power"] = "Intel Linux power telemetry is not wired up yet."
            snap.gaps["temperature"] = "Intel Linux temperature telemetry is not wired up yet."
            return [snap]

        try:
            result = subprocess.check_output(
                [intel_gpu_top, "-J", "-s", "100", "-o", "-"],
                timeout=2,
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", errors="ignore")

            lines = [line for line in result.splitlines() if line.strip().startswith("{")]
            if not lines:
                raise RuntimeError("intel_gpu_top did not return JSON samples")

            data = json.loads(lines[-1])
            engines = data.get("engines", {})
            busy_values = [
                float(engine.get("busy", 0) or 0)
                for engine in engines.values()
                if isinstance(engine, dict)
            ]
            snap.util_pct = max(busy_values) if busy_values else None
            snap.sources["utilization"] = "intel_gpu_top"
        except Exception as exc:
            snap.gaps["utilization"] = f"intel_gpu_top was detected but could not be read: {exc}"

        snap.gaps["memory"] = "Intel Linux UMA memory telemetry is not wired up yet."
        snap.gaps["power"] = "Intel Linux power telemetry is not wired up yet."
        snap.gaps["temperature"] = "Intel Linux temperature telemetry is not wired up yet."
        return [snap]

    def _find_intel_device(self):
        from_lspci = self._find_intel_device_from_lspci()
        if from_lspci:
            return from_lspci
        return self._find_intel_device_from_sysfs()

    def _find_intel_device_from_lspci(self):
        lspci = shutil.which("lspci")
        if not lspci:
            return None
        try:
            output = subprocess.check_output(
                [lspci],
                timeout=2,
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", errors="ignore")
        except Exception:
            return None

        for line in output.splitlines():
            lower = line.lower()
            if "intel" not in lower:
                continue
            if not any(token in lower for token in ("vga compatible controller", "display controller", "3d controller")):
                continue
            match = re.match(r"^([0-9a-fA-F:.]+)\s+(.+)$", line.strip())
            if not match:
                continue
            return {
                "bus_id": match.group(1),
                "name": match.group(2).strip(),
                "source": "lspci",
            }
        return None

    def _find_intel_device_from_sysfs(self):
        drm_root = "/sys/class/drm"
        if not os.path.isdir(drm_root):
            return None

        for entry in sorted(os.listdir(drm_root)):
            if not entry.startswith("card") or "-" in entry:
                continue
            device_root = os.path.join(drm_root, entry, "device")
            vendor_path = os.path.join(device_root, "vendor")
            if not os.path.isfile(vendor_path):
                continue
            try:
                vendor = open(vendor_path, "r", encoding="utf-8").read().strip().lower()
            except OSError:
                continue
            if vendor != "0x8086":
                continue

            uevent_path = os.path.join(device_root, "uevent")
            driver_name = "Intel GPU"
            if os.path.isfile(uevent_path):
                try:
                    for raw_line in open(uevent_path, "r", encoding="utf-8"):
                        line = raw_line.strip()
                        if line.startswith("PCI_ID="):
                            driver_name = f"Intel GPU ({line.split('=', 1)[1]})"
                            break
                except OSError:
                    pass

            return {
                "bus_id": entry,
                "name": driver_name,
                "source": "sysfs",
            }
        return None

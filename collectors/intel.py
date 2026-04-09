
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
        return self._find_intel_device() is not None or shutil.which("intel_gpu_top") is not None

    def collect(self):
        snap = GPUSnapshot(vendor="intel", compute_api="Intel")
        device = self._find_intel_device()
        host_mem = self._read_host_memory()

        if device:
            snap.device_name = device.get("name") or "Intel GPU"
            snap.bus_id = device.get("bus_id")
            snap.pcie_info = device.get("bus_id")
        else:
            snap.device_name = "Intel GPU"
            snap.gaps["gpu"] = "Fell back to a generic Intel GPU name because lspci/sysfs metadata was unavailable."

        total_mb = host_mem["total_mb"] or 0
        used_mb = host_mem["used_mb"] or 0
        snap.memory = MemoryInfo(
            mem_model="unified",
            total_mb=total_mb,
            used_mb=used_mb,
            host_total_mb=host_mem["total_mb"],
            host_used_mb=host_mem["used_mb"],
        )
        snap.sources["gpu"] = "lspci" if device and device.get("source") == "lspci" else "sysfs"
        snap.sources["driver"] = "kernel"
        if host_mem["source"]:
            snap.sources["memory"] = host_mem["source"]
        snap.caps.update({
            "utilization": True,
            "memory": bool(total_mb),
            "power": False,
            "temperature": False,
            "mem_clock": False,
        })

        intel_gpu_top = shutil.which("intel_gpu_top")
        if not intel_gpu_top:
            snap.gaps["utilization"] = "Install intel-gpu-tools to enable live Intel GPU utilization on Linux."
            if not total_mb:
                snap.gaps["memory"] = "Intel Linux shared memory telemetry could not be derived from /proc/meminfo."
            snap.gaps["power"] = "Intel Linux power telemetry is not wired up yet."
            snap.gaps["temperature"] = "Intel Linux temperature telemetry is not wired up yet."
            return [snap]

        try:
            data = self._read_intel_gpu_top_json(intel_gpu_top)
            busy_values = self._extract_busy_values(data)
            snap.util_pct = max(busy_values) if busy_values else None
            snap.sources["utilization"] = "intel_gpu_top"
            if snap.util_pct is None:
                snap.gaps["utilization"] = "intel_gpu_top returned JSON, but no engine busy values were found."
        except Exception as exc:
            snap.gaps["utilization"] = f"intel_gpu_top was detected but could not be read: {exc}"

        if total_mb:
            snap.gaps["memory"] = "Memory reflects shared system RAM on Intel UMA, not dedicated per-GPU VRAM."
        else:
            snap.gaps["memory"] = "Intel Linux shared memory telemetry could not be derived from /proc/meminfo."
        snap.gaps["power"] = "Intel Linux power telemetry is not wired up yet."
        snap.gaps["temperature"] = "Intel Linux temperature telemetry is not wired up yet."
        return [snap]

    def _read_intel_gpu_top_json(self, intel_gpu_top):
        attempts = [
            [intel_gpu_top, "-J", "-s", "100", "-o", "-"],
            [intel_gpu_top, "-J", "-s", "100"],
            [intel_gpu_top, "-J", "-o", "-"],
            [intel_gpu_top, "-J"],
        ]
        errors = []

        for cmd in attempts:
            try:
                proc = subprocess.run(
                    cmd,
                    timeout=2,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    check=False,
                )
            except Exception as exc:
                errors.append(f"{' '.join(cmd[1:])}: {exc}")
                continue

            output = (proc.stdout or "").strip()
            if not output:
                err = (proc.stderr or "").strip()
                errors.append(f"{' '.join(cmd[1:])}: {err or f'exit {proc.returncode}'}")
                continue

            try:
                parsed = json.loads(output)
            except json.JSONDecodeError:
                lines = [line for line in output.splitlines() if line.strip().startswith("{")]
                if not lines:
                    err = (proc.stderr or "").strip()
                    errors.append(f"{' '.join(cmd[1:])}: no JSON samples{f' ({err})' if err else ''}")
                    continue
                try:
                    parsed = json.loads(lines[-1])
                except json.JSONDecodeError as exc:
                    errors.append(f"{' '.join(cmd[1:])}: invalid JSON ({exc})")
                    continue

            if isinstance(parsed, list):
                parsed = next((item for item in reversed(parsed) if isinstance(item, dict)), None)
            if isinstance(parsed, dict):
                return parsed
            errors.append(f"{' '.join(cmd[1:])}: JSON payload was not an object")

        raise RuntimeError("; ".join(errors) if errors else "intel_gpu_top did not return JSON samples")

    def _extract_busy_values(self, payload):
        busy_values = []

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(value, (dict, list)):
                        walk(value)
                        continue
                    key_norm = str(key).strip().lower()
                    if key_norm in {"busy", "busy%", "busy %", "sema busy", "wait"}:
                        num = self._coerce_pct(value)
                        if num is not None:
                            busy_values.append(num)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return [value for value in busy_values if 0 <= value <= 100]

    def _read_host_memory(self):
        meminfo_path = "/proc/meminfo"
        if not os.path.isfile(meminfo_path):
            return {"total_mb": 0.0, "used_mb": 0.0, "source": None}

        values = {}
        try:
            with open(meminfo_path, "r", encoding="utf-8") as handle:
                for raw_line in handle:
                    if ":" not in raw_line:
                        continue
                    key, rest = raw_line.split(":", 1)
                    match = re.search(r"(\d+)", rest)
                    if match:
                        values[key.strip()] = float(match.group(1))
        except OSError:
            return {"total_mb": 0.0, "used_mb": 0.0, "source": None}

        total_kb = values.get("MemTotal", 0.0)
        avail_kb = values.get("MemAvailable", values.get("MemFree", 0.0))
        used_kb = max(0.0, total_kb - avail_kb)
        return {
            "total_mb": total_kb / 1024 if total_kb else 0.0,
            "used_mb": used_kb / 1024 if total_kb else 0.0,
            "source": "procfs",
        }

    def _coerce_pct(self, value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

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

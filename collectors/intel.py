
import json
import os
import re
import shutil
import subprocess

from schema import GPUSnapshot, MemoryInfo, ProcessInfo


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
            snap.processes = self._extract_processes(data)
            snap.util_pct = max(busy_values) if busy_values else None
            if snap.util_pct is None and snap.processes:
                snap.util_pct = min(100.0, sum(p.gpu_pct or 0.0 for p in snap.processes))
            snap.sources["utilization"] = "intel_gpu_top"
            if snap.processes:
                snap.sources["processes"] = "intel_gpu_top"
            if snap.util_pct is None:
                snap.gaps["utilization"] = "intel_gpu_top returned JSON, but no engine busy values were found."
        except Exception as exc:
            snap.gaps["utilization"] = f"intel_gpu_top was detected but could not be read: {exc}"

        if snap.util_pct is None and not snap.processes:
            try:
                text_metrics = self._read_intel_gpu_top_text(intel_gpu_top)
                if text_metrics["util_pct"] is not None:
                    snap.util_pct = text_metrics["util_pct"]
                    snap.sources["utilization"] = "intel_gpu_top-text"
                if text_metrics["processes"]:
                    snap.processes = text_metrics["processes"]
                    snap.sources["processes"] = "intel_gpu_top-text"
                if snap.util_pct is None and not snap.processes:
                    snap.gaps["utilization"] = "intel_gpu_top text output was readable, but no utilization values were recognized."
            except Exception as exc:
                if snap.util_pct is None:
                    snap.gaps["utilization"] = f"intel_gpu_top text fallback failed: {exc}"

        if total_mb:
            snap.gaps["memory"] = "Memory reflects shared system RAM on Intel UMA, not dedicated per-GPU VRAM."
        else:
            snap.gaps["memory"] = "Intel Linux shared memory telemetry could not be derived from /proc/meminfo."
        snap.gaps["power"] = "Intel Linux power telemetry is not wired up yet."
        snap.gaps["temperature"] = "Intel Linux temperature telemetry is not wired up yet."
        return [snap]

    def _read_intel_gpu_top_json(self, intel_gpu_top):
        attempts = self._intel_gpu_top_attempts(intel_gpu_top, json_mode=True)
        errors = []

        for cmd in attempts:
            try:
                proc = subprocess.run(
                    cmd,
                    timeout=8,
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
                objects = self._extract_json_objects(output)
                if not objects:
                    err = (proc.stderr or "").strip()
                    errors.append(f"{' '.join(cmd[1:])}: no JSON samples{f' ({err})' if err else ''}")
                    continue
                try:
                    parsed = json.loads(objects[-1])
                except json.JSONDecodeError as exc:
                    errors.append(f"{' '.join(cmd[1:])}: invalid JSON ({exc})")
                    continue

            if isinstance(parsed, list):
                parsed = next((item for item in reversed(parsed) if isinstance(item, dict)), None)
            if isinstance(parsed, dict):
                return parsed
            errors.append(f"{' '.join(cmd[1:])}: JSON payload was not an object")

        raise RuntimeError("; ".join(errors) if errors else "intel_gpu_top did not return JSON samples")

    def _extract_json_objects(self, text):
        objects = []
        depth = 0
        start = None
        in_string = False
        escape = False

        for idx, ch in enumerate(text):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                if depth == 0:
                    start = idx
                depth += 1
            elif ch == "}":
                if depth == 0:
                    continue
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(text[start:idx + 1])
                    start = None
        return objects

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

    def _extract_processes(self, payload):
        collected = {}

        def walk(node):
            if isinstance(node, dict):
                pid = self._extract_pid(node)
                name = self._extract_process_name(node)
                if pid is not None and name:
                    gpu_pct = self._extract_node_busy(node)
                    current = collected.setdefault(pid, {
                        "pid": pid,
                        "name": name,
                        "gpu_pct": 0.0,
                    })
                    current["name"] = name
                    if gpu_pct is not None:
                        current["gpu_pct"] = max(current["gpu_pct"], gpu_pct)

                for value in node.values():
                    if isinstance(value, (dict, list)):
                        walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)

        processes = []
        for info in collected.values():
            gpu_pct = info["gpu_pct"]
            if gpu_pct is None or gpu_pct <= 0:
                continue
            processes.append(ProcessInfo(
                pid=info["pid"],
                name=info["name"],
                type="Compute",
                gpu_pct=round(gpu_pct, 1),
                gpu_pct_source="intel_gpu_top",
                mem_mb=None,
            ))

        processes.sort(key=lambda proc: (proc.gpu_pct or 0), reverse=True)
        return processes

    def _read_intel_gpu_top_text(self, intel_gpu_top):
        attempts = self._intel_gpu_top_attempts(intel_gpu_top, json_mode=False)
        errors = []

        for cmd in attempts:
            try:
                proc = subprocess.run(
                    cmd,
                    timeout=5,
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

            output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            if not output:
                errors.append(f"{' '.join(cmd[1:])}: no output")
                continue

            util_pct = self._extract_text_util(output)
            processes = self._extract_text_processes(output)
            if util_pct is not None or processes:
                return {"util_pct": util_pct, "processes": processes}
            errors.append(f"{' '.join(cmd[1:])}: output did not match known intel_gpu_top text patterns")

        raise RuntimeError("; ".join(errors) if errors else "intel_gpu_top text fallback did not produce output")

    def _extract_text_util(self, text):
        matches = []
        for line in text.splitlines():
            lower = line.lower()
            if not any(token in lower for token in ("render", "video", "blitter", "compute", "copy", "3d")):
                continue
            for match in re.finditer(r"(\d+(?:\.\d+)?)\s*%", line):
                try:
                    matches.append(float(match.group(1)))
                except ValueError:
                    pass
        return max(matches) if matches else None

    def _extract_text_processes(self, text):
        processes = []
        seen = set()

        for line in text.splitlines():
            match = re.match(r"^\s*(\d+)\s+([A-Za-z0-9_.:/-][^%]{0,80}?)\s+((?:\d+(?:\.\d+)?\s*%[\s|]*)+)\s*$", line)
            if not match:
                continue
            pid = self._coerce_int(match.group(1))
            name = match.group(2).strip()
            pct_values = [self._coerce_pct(value) for value in re.findall(r"\d+(?:\.\d+)?\s*%", match.group(3))]
            pct_values = [value for value in pct_values if value is not None]
            if pid is None or not name or not pct_values or pid in seen:
                continue
            seen.add(pid)
            processes.append(ProcessInfo(
                pid=pid,
                name=name,
                type="Compute",
                gpu_pct=round(max(pct_values), 1),
                gpu_pct_source="intel_gpu_top-text",
                mem_mb=None,
            ))

        processes.sort(key=lambda proc: (proc.gpu_pct or 0), reverse=True)
        return processes

    def _intel_gpu_top_attempts(self, intel_gpu_top, json_mode):
        base_attempts = (
            [
                [intel_gpu_top, "-J", "-s", "100", "-o", "-"],
                [intel_gpu_top, "-J", "-s", "100"],
                [intel_gpu_top, "-J", "-o", "-"],
                [intel_gpu_top, "-J"],
            ]
            if json_mode else
            [
                [intel_gpu_top, "-s", "100", "-o", "-"],
                [intel_gpu_top, "-s", "100"],
            ]
        )

        attempts = list(base_attempts)
        sudo = shutil.which("sudo")
        if sudo:
            attempts.extend([["sudo", "-n", *cmd] for cmd in base_attempts])
        return attempts

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

    def _extract_pid(self, node):
        for key in ("pid", "PID", "process id", "process-id", "client-id"):
            if key in node:
                return self._coerce_int(node.get(key))
        return None

    def _extract_process_name(self, node):
        for key in ("name", "comm", "command", "process", "client"):
            value = node.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def _extract_node_busy(self, node):
        values = self._extract_busy_values(node)
        if values:
            return max(values)
        for key, value in node.items():
            key_norm = str(key).strip().lower()
            if "busy" in key_norm or "util" in key_norm:
                pct = self._coerce_pct(value)
                if pct is not None:
                    return pct
        return None

    def _coerce_int(self, value):
        if value is None:
            return None
        if isinstance(value, int):
            return value
        match = re.search(r"(\d+)", str(value))
        if not match:
            return None
        try:
            return int(match.group(1))
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

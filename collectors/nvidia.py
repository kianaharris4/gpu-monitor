import subprocess
import re

from schema import GPUSnapshot, MemoryInfo, ProcessInfo


def _safe_float(value):
    if value in (None, "", "[N/A]", "N/A", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


class NvidiaCollector:
    def detect(self):
        try:
            subprocess.check_output(["nvidia-smi"])
            return True
        except:
            return False

    def collect(self):
        snapshots = []

        try:
            result = subprocess.check_output([
                "nvidia-smi",
                "--query-gpu=index,name,driver_version,pci.bus_id,utilization.gpu,temperature.gpu,power.draw,power.limit,clocks.gr,memory.used,memory.total",
                "--format=csv,noheader,nounits"
            ], timeout=5).decode().strip()

            processes_by_gpu = self._load_processes()

            for row in result.split("\n"):
                parts = [p.strip() for p in row.split(",")]

                if len(parts) < 11:
                    continue

                idx, name, driver_version, bus_id, util, temp, power, power_limit, clock, mem_used, mem_total = parts
                gpu_index = _safe_int(idx)

                snap = GPUSnapshot(
                    gpu_index=gpu_index,
                    device_name=name,
                    vendor="nvidia",
                    driver_version=driver_version,
                    compute_api="CUDA / NVML",
                    bus_id=bus_id,
                    pcie_info=bus_id,
                )

                snap.sources["gpu"] = "nvidia-smi"
                snap.sources["telemetry"] = "nvidia-smi"
                snap.sources["driver"] = "nvidia-smi"
                snap.sources["nvidia_index"] = idx
                snap.caps.update({
                    "utilization": True,
                    "memory": True,
                    "temperature": True,
                    "power": True,
                })

                snap.util_pct = _safe_float(util)
                snap.temp_c = _safe_float(temp)
                snap.power_w = _safe_float(power)
                snap.power_limit_w = _safe_float(power_limit)
                snap.clock_mhz = _safe_float(clock)
                snap.processes = processes_by_gpu.get(gpu_index, []) if gpu_index is not None else []
                if snap.processes:
                    process_sources = sorted({proc.gpu_pct_source for proc in snap.processes if proc.gpu_pct_source})
                    snap.sources["processes"] = " / ".join(process_sources) if process_sources else "nvidia-smi"
                else:
                    snap.gaps["processes"] = (
                        "nvidia-smi did not report active per-process GPU usage for this adapter."
                    )

                snap.memory = MemoryInfo(
                    mem_model="dedicated",
                    used_mb=_safe_float(mem_used) or 0.0,
                    total_mb=_safe_float(mem_total) or 0.0,
                )

                if snap.util_pct == 0:
                    snap.gaps["utilization"] = (
                        "NVIDIA is reporting 0% utilization. This can be normal when the GPU is idle "
                        "or when a laptop workload is running on the integrated GPU instead of the NVIDIA adapter."
                    )

                snapshots.append(snap)

        except Exception as e:
            snap = GPUSnapshot(
                device_name="NVIDIA telemetry unavailable",
                vendor="nvidia",
                compute_api="NVIDIA",
                memory=MemoryInfo(mem_model="dedicated", total_mb=0.0, used_mb=0.0),
            )
            snap.caps.update({
                "utilization": False,
                "memory": False,
                "power": False,
                "temperature": False,
            })
            snap.gaps["collector"] = f"nvidia-smi failed while collecting telemetry: {e}"
            snap.gaps["utilization"] = "GPU utilization requires a working nvidia-smi command."
            snap.gaps["memory"] = "GPU memory requires a working nvidia-smi command."
            return [snap]

        return snapshots

    def _load_processes(self):
        display_processes = self._load_display_processes()
        memory_by_pid = self._load_process_memory()
        for procs in display_processes.values():
            for proc in procs:
                if proc.mem_mb is not None:
                    memory_by_pid[proc.pid] = proc.mem_mb
        try:
            result = subprocess.check_output(
                ["nvidia-smi", "pmon", "-c", "1", "-s", "um"],
                timeout=5,
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", errors="ignore")
        except Exception:
            return self._processes_from_memory(memory_by_pid)

        processes_by_gpu = {}
        for raw_line in result.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 7)
            if len(parts) < 8:
                continue
            gpu, pid, proc_type, sm_pct, mem_pct, _enc, _dec, command = parts
            gpu_index = _safe_int(gpu)
            pid_int = _safe_int(pid)
            if gpu_index is None or pid_int is None:
                continue
            mem_mb = memory_by_pid.get(pid_int)
            display_proc = next((proc for proc in display_processes.get(gpu_index, []) if proc.pid == pid_int), None)
            proc = ProcessInfo(
                pid=pid_int,
                name=display_proc.name if display_proc else command,
                type=display_proc.type if display_proc else (proc_type if proc_type not in ("-", "N/A") else "GPU"),
                gpu_pct=_safe_float(sm_pct),
                gpu_pct_source="nvidia-smi pmon",
                mem_mb=mem_mb,
            )
            processes_by_gpu.setdefault(gpu_index, []).append(proc)

        if not processes_by_gpu:
            return display_processes or self._processes_from_memory(memory_by_pid)

        for gpu_index, procs in display_processes.items():
            existing = processes_by_gpu.setdefault(gpu_index, [])
            seen = {proc.pid for proc in existing}
            existing.extend(proc for proc in procs if proc.pid not in seen)
            existing.sort(key=lambda proc: ((proc.gpu_pct or 0.0), (proc.mem_mb or 0.0)), reverse=True)
        return processes_by_gpu

    def _load_display_processes(self):
        try:
            result = subprocess.check_output(
                ["nvidia-smi"],
                timeout=5,
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", errors="ignore")
        except Exception:
            return {}

        processes_by_gpu = {}
        row_pattern = re.compile(
            r"^\s*(?P<gpu>\d+)\s+\S+\s+\S+\s+(?P<pid>\d+)\s+"
            r"(?P<type>[CG+]+)\s+(?P<name>.*?)\s+(?P<mem>\d+)\s*MiB\s*$"
        )
        for raw_line in result.splitlines():
            if "|" not in raw_line or "MiB" not in raw_line:
                continue
            cells = [cell.strip() for cell in raw_line.strip().strip("|").split("|")]
            if not cells:
                continue
            match = row_pattern.match(cells[0])
            if not match:
                continue
            gpu_index = _safe_int(match.group("gpu"))
            pid = _safe_int(match.group("pid"))
            mem_mb = _safe_float(match.group("mem"))
            if gpu_index is None or pid is None:
                continue
            processes_by_gpu.setdefault(gpu_index, []).append(ProcessInfo(
                pid=pid,
                name=match.group("name").strip(),
                type=match.group("type"),
                gpu_pct=None,
                gpu_pct_source="nvidia-smi process table",
                mem_mb=mem_mb,
            ))

        for procs in processes_by_gpu.values():
            procs.sort(key=lambda proc: proc.mem_mb or 0.0, reverse=True)
        return processes_by_gpu

    def _load_process_memory(self):
        try:
            result = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
                    "--format=csv,noheader,nounits",
                ],
                timeout=5,
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", errors="ignore").strip()
        except Exception:
            return {}

        memory_by_pid = {}
        for row in result.splitlines():
            parts = [part.strip() for part in row.split(",")]
            if len(parts) < 4:
                continue
            pid = _safe_int(parts[1])
            mem_mb = _safe_float(parts[3])
            if pid is not None and mem_mb is not None:
                memory_by_pid[pid] = mem_mb
        return memory_by_pid

    def _processes_from_memory(self, memory_by_pid):
        if not memory_by_pid:
            return {}
        processes = [
            ProcessInfo(
                pid=pid,
                name=str(pid),
                type="Compute",
                gpu_pct=None,
                gpu_pct_source="nvidia-smi query-compute-apps",
                mem_mb=mem_mb,
            )
            for pid, mem_mb in memory_by_pid.items()
        ]
        processes.sort(key=lambda proc: proc.mem_mb or 0.0, reverse=True)
        return {0: processes}

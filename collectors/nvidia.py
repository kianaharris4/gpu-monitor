import subprocess
from schema import GPUSnapshot, MemoryInfo

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
                "--query-gpu=index,name,utilization.gpu,temperature.gpu,power.draw,power.limit,clocks.gr,memory.used,memory.total",
                "--format=csv,noheader,nounits"
            ]).decode().strip()

            for row in result.split("\n"):
                parts = [p.strip() for p in row.split(",")]

                if len(parts) < 8:
                    continue

                idx, name, util, temp, power, power_limit, clock, mem_used, mem_total = parts

                snap = GPUSnapshot()

                snap.sources["gpu"] = "nvidia-smi"
                snap.sources["index"] = idx
                snap.sources["name"] = name

                snap.util_pct = float(util)
                snap.temp_c = float(temp)
                snap.power_w = float(power) if power != "[N/A]" else None
                snap.power_limit_w = float(power_limit) if power_limit != "[N/A]" else None
                snap.clock_mhz = float(clock) if clock != "[N/A]" else None

                snap.memory = MemoryInfo(
                    mem_model="dedicated",
                    used_mb=float(mem_used),
                    total_mb=float(mem_total),
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

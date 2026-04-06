
import subprocess, json
from schema import GPUSnapshot, MemoryInfo

class AMDCollector:
    def detect(self):
        try:
            subprocess.check_output(["rocm-smi"])
            return True
        except:
            return False

    def collect(self):
        snap = GPUSnapshot()
        try:
            result = subprocess.check_output(["rocm-smi", "--json"]).decode()
            data = json.loads(result)
            gpu = list(data.values())[0]

            snap.util_pct = gpu.get("GPU use (%)")
            snap.temp_c = gpu.get("Temperature (Sensor edge) (C)")
            snap.power_w = gpu.get("Average Graphics Package Power (W)")

            used = gpu.get("VRAM Total Used Memory (B)", 0)
            total = gpu.get("VRAM Total Memory (B)", 1)

            snap.memory = MemoryInfo(
                mem_model="dedicated",
                used_mb=used / (1024*1024),
                total_mb=total / (1024*1024)
            )
        except Exception as e:
            print(e)

        return [snap]

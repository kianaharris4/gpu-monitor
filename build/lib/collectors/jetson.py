
import subprocess, re
from schema import GPUSnapshot, MemoryInfo

class JetsonCollector:
    def detect(self):
        try:
            subprocess.check_output(["which", "tegrastats"])
            return True
        except:
            return False

    def collect(self):
        snap = GPUSnapshot()
        try:
            out = subprocess.check_output(
                ["tegrastats","--interval","100","--count","1"]
            ).decode()

            ram = re.search(r"RAM (\d+)/(\d+)MB", out)
            if ram:
                used, total = map(float, ram.groups())
                snap.memory = MemoryInfo(
                    mem_model="unified",
                    used_mb=used,
                    total_mb=total
                )

            gpu = re.search(r"GR3D_FREQ (\d+)%@(\d+)", out)
            if gpu:
                snap.util_pct = float(gpu.group(1))
                snap.clock_mhz = float(gpu.group(2))

        except Exception as e:
            print(e)

        return [snap]

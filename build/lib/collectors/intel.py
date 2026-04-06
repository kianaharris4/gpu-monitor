
import subprocess, json
from schema import GPUSnapshot, MemoryInfo

class IntelCollector:

    capabilities = {
        "utilization": True,
        "memory": False,
        "power": False,
        "temperature": True,
    }

    def detect(self):
        try:
            subprocess.check_output(["which", "intel_gpu_top"])
            return True
        except:
            return False

    def collect(self):
        snap = GPUSnapshot()
        try:
            result = subprocess.check_output([
                "intel_gpu_top","-J","-s","100","-o","-"
            ], timeout=1).decode()

            lines = [l for l in result.split("\n") if l.startswith("{")]
            data = json.loads(lines[-1])

            engines = data.get("engines", {})
            busy = sum(e.get("busy",0) for e in engines.values())
            count = len(engines)

            snap.util_pct = busy / count if count else None

            snap.memory = MemoryInfo(mem_model="unified", total_mb=0, used_mb=0)

        except Exception as e:
            print(e)

        return [snap]

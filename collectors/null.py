from schema import GPUSnapshot, MemoryInfo


class NullCollector:
    def __init__(self, reason="No supported GPU detected"):
        self.reason = reason

    def detect(self):
        return True

    def collect(self):
        snap = GPUSnapshot(
            device_name="No supported GPU detected",
            vendor="unknown",
            compute_api="unknown",
            memory=MemoryInfo(mem_model="shared", total_mb=0.0, used_mb=0.0),
        )
        snap.gaps["collector"] = self.reason
        snap.gaps["utilization"] = self.reason
        snap.gaps["memory"] = self.reason
        snap.gaps["power"] = self.reason
        snap.gaps["temperature"] = self.reason
        return [snap]

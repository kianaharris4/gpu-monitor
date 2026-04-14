from schema import GPUSnapshot, MemoryInfo


class NullCollector:
    def __init__(self, reason="No supported GPU detected", device_name="No supported GPU detected", vendor="unknown"):
        self.reason = reason
        self.device_name = device_name
        self.vendor = vendor

    def detect(self):
        return True

    def collect(self):
        snap = GPUSnapshot(
            device_name=self.device_name,
            vendor=self.vendor,
            compute_api="unknown",
            memory=MemoryInfo(mem_model="shared", total_mb=0.0, used_mb=0.0),
        )
        snap.caps.update({
            "utilization": False,
            "memory": False,
            "power": False,
            "temperature": False,
        })
        snap.gaps["collector"] = self.reason
        snap.gaps["utilization"] = self.reason
        snap.gaps["memory"] = self.reason
        snap.gaps["power"] = self.reason
        snap.gaps["temperature"] = self.reason
        return [snap]

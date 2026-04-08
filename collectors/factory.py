
import os

from collectors.windows import WindowsCollector
from collectors.jetson import JetsonCollector
from collectors.nvidia import NvidiaCollector
from collectors.amd import AMDCollector
from collectors.intel import IntelCollector
from collectors.null import NullCollector

def get_collector():
    if os.name == "nt":
        collector = WindowsCollector()
        if collector.detect():
            print(f"[INFO] Using collector: {collector.__class__.__name__}")
            return collector

    collectors = [
        JetsonCollector(),
        NvidiaCollector(),
        AMDCollector(),
        IntelCollector(),
    ]

    for c in collectors:
        if c.detect():
            print(f"[INFO] Using collector: {c.__class__.__name__}")
            return c

    reason = "No supported GPU detected. On Ubuntu Intel systems, install intel-gpu-tools for live utilization and verify /sys/class/drm or lspci can see the Intel adapter."
    print(f"[WARN] {reason}")
    return NullCollector(reason)

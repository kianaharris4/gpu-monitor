
import os
import shutil
import subprocess

from collectors.windows import WindowsCollector
from collectors.jetson import JetsonCollector
from collectors.nvidia import NvidiaCollector
from collectors.amd import AMDCollector
from collectors.intel import IntelCollector
from collectors.null import NullCollector


def _command_exists(command):
    return shutil.which(command) is not None


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.read()
    except OSError:
        return ""


def _is_jetson_platform():
    model = _read_text("/proc/device-tree/model").lower()
    release = _read_text("/etc/nv_tegra_release").lower()
    return "jetson" in model or "nvidia tegra" in model or "tegra" in release


def _lspci_contains(*needles):
    lspci = shutil.which("lspci")
    if not lspci:
        return False
    try:
        output = subprocess.check_output([lspci], timeout=2, stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore").lower()
    except Exception:
        return False
    return any(needle.lower() in output for needle in needles)


def get_collector():
    if os.name == "nt":
        collector = WindowsCollector()
        if collector.detect():
            print(f"[INFO] Using collector: {collector.__class__.__name__}")
            return collector

    if _is_jetson_platform() and not _command_exists("tegrastats"):
        reason = (
            "NVIDIA Jetson platform detected, but tegrastats is not available. "
            "Install or enable NVIDIA Jetson telemetry tools so GPU utilization and unified memory can be collected."
        )
        print(f"[WARN] {reason}")
        return NullCollector(reason, device_name="NVIDIA Jetson telemetry unavailable", vendor="nvidia")

    if _lspci_contains("nvidia") and not _command_exists("nvidia-smi"):
        reason = (
            "NVIDIA GPU detected, but nvidia-smi is not available. "
            "Install the NVIDIA driver utilities or verify the NVIDIA driver is loaded."
        )
        print(f"[WARN] {reason}")
        return NullCollector(reason, device_name="NVIDIA telemetry unavailable", vendor="nvidia")

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

    reason = (
        "No supported GPU telemetry source was detected. Supported sources include nvidia-smi, "
        "tegrastats, rocm-smi, intel_gpu_top, Windows GPU performance counters, or visible GPU metadata in lspci/sysfs."
    )
    print(f"[WARN] {reason}")
    return NullCollector(reason)

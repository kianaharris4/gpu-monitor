"""
schema.py — Unified GPU snapshot dataclass.

All collectors produce a GPUSnapshot each poll cycle.
Fields are None when the driver/API does not expose them — the dashboard
renders these as "N/A" rather than hiding the panel.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, List
import time

capabilities = {
    "utilization": True,
    "memory": True,
    "power": True,
    "temperature": True,
}

@dataclass
class EngineUtilization:
    """Per-engine busy percentage. None = not available for this vendor."""
    graphics_3d:  Optional[float] = None
    compute:      Optional[float] = None
    video_encode: Optional[float] = None
    video_decode: Optional[float] = None
    copy_dma:     Optional[float] = None


@dataclass
class MemoryInfo:
    """GPU-accessible memory. mem_model drives dashboard labelling."""
    mem_model:          str            = "dedicated"
    total_mb:           float          = 0.0
    used_mb:            float          = 0.0
    free_mb:            Optional[float] = None
    process_used_mb:    Optional[float] = None
    driver_reserved_mb: Optional[float] = None
    host_total_mb:      Optional[float] = None
    host_used_mb:       Optional[float] = None
    bandwidth_gbs:      Optional[float] = None
    peak_bandwidth_gbs: Optional[float] = None

    def __post_init__(self):
        if self.free_mb is None and self.total_mb:
            self.free_mb = max(0.0, self.total_mb - self.used_mb)


@dataclass
class ProcessInfo:
    pid:            int
    name:           str
    cmdline:        str            = ""
    type:           str            = "Graphics"
    gpu_pct:        Optional[float] = None
    gpu_pct_source: str            = "unknown"
    mem_mb:         Optional[float] = None


@dataclass
class GPUSnapshot:
    timestamp:     float = field(default_factory=time.time)
    gpu_index:     Optional[int] = None
    device_name:   Optional[str] = None
    vendor:        Optional[str] = None
    driver_version: Optional[str] = None
    compute_api:   Optional[str] = None
    bus_id:        Optional[str] = None
    pcie_info:     Optional[str] = None
    util_pct:      Optional[float] = None
    engine:        EngineUtilization = field(default_factory=EngineUtilization)
    memory:        MemoryInfo = field(default_factory=MemoryInfo)
    temp_c:        Optional[float] = None
    hot_spot_c:    Optional[float] = None
    temp_max_c:    Optional[float] = None
    power_w:       Optional[float] = None
    power_limit_w: Optional[float] = None
    voltage_v:     Optional[float] = None
    fan_pct:       Optional[float] = None
    fan_rpm:       Optional[int]   = None
    clock_mhz:     Optional[float] = None
    mem_clock_mhz: Optional[float] = None
    max_clock_mhz: Optional[float] = None
    bandwidth_gbs: Optional[float] = None
    processes:     List[ProcessInfo] = field(default_factory=list)
    caps:          dict = field(default_factory=dict)
    sources:       dict = field(default_factory=dict)
    gaps:          dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

import json
import os
import re
import subprocess
import tempfile
import time
import ctypes

from schema import EngineUtilization, GPUSnapshot, MemoryInfo


def _safe_float(value):
    if value in (None, "", "[N/A]", "N/A"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_name(name):
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


class WindowsCollector:
    def __init__(self):
        self._cards_cache = None
        self._cards_cache_at = 0.0
        self._perf_cache = None
        self._perf_cache_at = 0.0

    def detect(self):
        return os.name == "nt"

    def collect(self):
        cards = self._load_cards()
        if not cards:
            raise RuntimeError("No Windows GPU adapters found via dxdiag")

        counters = self._load_perf_counters()
        nvidia_rows = self._load_nvidia_rows()
        snapshots = []
        used_luids = set()

        for idx, card in enumerate(cards):
            vendor = self._vendor_name(card)
            snap = GPUSnapshot(
                gpu_index=idx,
                device_name=card.get("name"),
                vendor=vendor,
                driver_version=card.get("driver_version"),
                compute_api="CUDA / NVML" if vendor == "nvidia" else "WDDM",
            )

            snap.sources["gpu"] = "dxdiag"
            snap.sources["driver"] = "dxdiag"
            snap.gaps["per_process_gpu_pct"] = "Per-process Windows GPU attribution is not wired up yet."

            if vendor == "nvidia":
                luid = self._pick_luid_for_discrete(counters, used_luids)
                if luid:
                    used_luids.add(luid)
                self._apply_nvidia_metrics(snap, card, nvidia_rows, counters, luid)
            else:
                luid = self._pick_luid_for_integrated(counters, used_luids)
                if luid:
                    used_luids.add(luid)
                self._apply_windows_counter_metrics(snap, card, counters, luid)

            snapshots.append(snap)

        return snapshots

    def _load_cards(self):
        now = time.time()
        if self._cards_cache and now - self._cards_cache_at < 300:
            return self._cards_cache

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
            dxdiag_path = tmp.name

        try:
            subprocess.run(
                ["dxdiag", "/whql:off", "/t", dxdiag_path],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            with open(dxdiag_path, "r", encoding="utf-16", errors="ignore") as fh:
                text = fh.read()
        except UnicodeError:
            with open(dxdiag_path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        finally:
            try:
                os.unlink(dxdiag_path)
            except OSError:
                pass

        cards = self._parse_dxdiag_cards(text)
        self._cards_cache = cards
        self._cards_cache_at = now
        return cards

    def _parse_dxdiag_cards(self, text):
        section_match = re.search(
            r"Display Devices\s*-+\s*(.*?)(?:\n[A-Za-z][^\n]*\n-+\s*\n|\Z)",
            text,
            re.DOTALL,
        )
        if section_match:
            text = section_match.group(1)

        cards = []
        current = None

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if "Card name:" in line:
                if current:
                    cards.append(current)
                current = {"name": line.split(":", 1)[1].strip()}
                continue
            if not current or ":" not in line:
                continue

            key, value = [part.strip() for part in line.split(":", 1)]
            key = key.lower().replace(" ", "_")
            current[key] = value

        if current:
            cards.append(current)

        deduped = []
        seen = set()
        for card in cards:
            key = (
                card.get("device_key") or "",
                card.get("name") or "",
                card.get("vendor_id") or "",
                card.get("device_id") or "",
            )
            name = (card.get("name") or "").lower()
            if "root port" in name:
                continue
            if key in seen:
                continue
            seen.add(key)
            deduped.append(card)

        return deduped

    def _load_perf_counters(self):
        now = time.time()
        if self._perf_cache and now - self._perf_cache_at < 15:
            return self._perf_cache

        script = r"""
$samples = Get-Counter @('\GPU Engine(*)\Utilization Percentage','\GPU Adapter Memory(*)\Shared Usage','\GPU Adapter Memory(*)\Dedicated Usage') -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty CounterSamples |
  Select-Object Path, InstanceName, CookedValue
$samples | ConvertTo-Json -Compress
"""
        try:
            result = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", script],
                timeout=12,
            ).decode("utf-8", errors="ignore").strip()
        except Exception:
            return self._perf_cache or {"engines": {}, "shared_mb": {}, "dedicated_mb": {}}

        if not result:
            return self._perf_cache or {"engines": {}, "shared_mb": {}, "dedicated_mb": {}}

        parsed = json.loads(result)
        if isinstance(parsed, dict):
            parsed = [parsed]

        engines = {}
        shared_mb = {}
        dedicated_mb = {}

        for row in parsed:
            path = (row.get("Path") or "").lower()
            instance = row.get("InstanceName") or ""
            value = float(row.get("CookedValue") or 0)
            luid_match = re.search(r"(luid_0x[0-9a-f]+_0x[0-9a-f]+)", instance, re.IGNORECASE)
            if not luid_match:
                continue
            luid = luid_match.group(1).lower()

            if "gpu engine" in path:
                engine_match = re.search(r"_eng_(\d+)_engtype_([a-z]*)", instance, re.IGNORECASE)
                if not engine_match:
                    continue
                engine_id = engine_match.group(1)
                engine_type = (engine_match.group(2) or "other").lower()
                per_luid = engines.setdefault(luid, {})
                current = per_luid.get(engine_id)
                if current is None or value > current["value"]:
                    per_luid[engine_id] = {"type": engine_type, "value": value}
            elif "shared usage" in path:
                shared_mb[luid] = value / (1024 * 1024)
            elif "dedicated usage" in path:
                dedicated_mb[luid] = value / (1024 * 1024)

        self._perf_cache = {"engines": engines, "shared_mb": shared_mb, "dedicated_mb": dedicated_mb}
        self._perf_cache_at = now
        return self._perf_cache

    def _load_nvidia_rows(self):
        query = ",".join([
            "index",
            "name",
            "driver_version",
            "pci.bus_id",
            "utilization.gpu",
            "temperature.gpu",
            "power.draw",
            "power.limit",
            "clocks.gr",
            "clocks.mem",
            "clocks.max.gr",
            "memory.used",
            "memory.total",
        ])
        try:
            result = subprocess.check_output(
                ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                timeout=4,
            ).decode("utf-8", errors="ignore").strip()
        except Exception:
            return []

        rows = []
        for row in result.splitlines():
            parts = [part.strip() for part in row.split(",")]
            if len(parts) != 13:
                continue
            rows.append({
                "index": int(parts[0]),
                "name": parts[1],
                "driver_version": parts[2],
                "pci_bus_id": parts[3],
                "util": _safe_float(parts[4]),
                "temp": _safe_float(parts[5]),
                "power": _safe_float(parts[6]),
                "power_limit": _safe_float(parts[7]),
                "clock": _safe_float(parts[8]),
                "mem_clock": _safe_float(parts[9]),
                "max_clock": _safe_float(parts[10]),
                "mem_used": _safe_float(parts[11]),
                "mem_total": _safe_float(parts[12]),
            })
        return rows

    def _vendor_name(self, card):
        vendor_id = (card.get("vendor_id") or "").lower()
        manufacturer = (card.get("manufacturer") or "").lower()
        if "10de" in vendor_id or "nvidia" in manufacturer:
            return "nvidia"
        if "8086" in vendor_id or "intel" in manufacturer:
            return "intel"
        if "1002" in vendor_id or "amd" in manufacturer or "advanced micro devices" in manufacturer:
            return "amd"
        return manufacturer or "unknown"

    def _apply_nvidia_metrics(self, snap, card, nvidia_rows, counters, luid):
        target_name = _normalize_name(card.get("name"))
        match = None
        for row in nvidia_rows:
            if _normalize_name(row["name"]) == target_name:
                match = row
                break
        if match is None and nvidia_rows:
            match = nvidia_rows[0]

        dedicated_mb = self._parse_mb(card.get("dedicated_memory"))
        total_mb = match["mem_total"] if match and match["mem_total"] is not None else dedicated_mb
        used_mb = match["mem_used"] if match and match["mem_used"] is not None else 0.0

        snap.memory = MemoryInfo(
            mem_model="dedicated",
            used_mb=used_mb or 0.0,
            total_mb=total_mb or dedicated_mb or 0.0,
        )
        snap.caps.update({
            "utilization": True,
            "memory": True,
            "temperature": True,
            "power": True,
            "mem_clock": True,
        })
        snap.sources["telemetry"] = "nvidia-smi"
        if luid:
            snap.sources["utilization"] = "windows-performance-counters"
        else:
            snap.sources["utilization"] = "nvidia-smi"

        if not match:
            snap.gaps["telemetry"] = "nvidia-smi is unavailable, so live NVIDIA metrics are missing."
            return

        snap.device_name = match["name"]
        snap.bus_id = match["pci_bus_id"]
        snap.sources["nvidia_index"] = str(match["index"])
        snap.sources["driver_package_version"] = match["driver_version"]
        snap.temp_c = match["temp"]
        snap.power_w = match["power"]
        snap.power_limit_w = match["power_limit"]
        snap.clock_mhz = match["clock"]
        snap.mem_clock_mhz = match["mem_clock"]
        snap.max_clock_mhz = match["max_clock"]

        if luid:
            engine_info = counters["engines"].get(luid, {})
            rollup = self._roll_up_engines(engine_info)
            snap.util_pct = rollup["total"]
            snap.engine = rollup["engine"]
            snap.sources["luid"] = luid
            if rollup["total"] is None:
                snap.gaps["utilization"] = "No active GPU engine counter matched this NVIDIA adapter."
                snap.util_pct = match["util"]
                snap.sources["utilization"] = "nvidia-smi"
        else:
            snap.gaps["utilization"] = "No Windows GPU engine counter matched this NVIDIA adapter; falling back to nvidia-smi utilization."
            snap.util_pct = match["util"]

    def _apply_windows_counter_metrics(self, snap, card, counters, luid):
        system_total_mb = self._system_ram_mb()
        shared_total = self._parse_mb(card.get("shared_memory"))
        dedicated_total = self._parse_mb(card.get("dedicated_memory"))
        display_total = self._parse_mb(card.get("display_memory"))
        used_shared = counters["shared_mb"].get(luid, 0.0) if luid else 0.0
        if shared_total is None and system_total_mb is not None:
            # Windows Task Manager typically reports "Shared GPU memory" as
            # roughly half of physical system RAM for integrated adapters.
            shared_total = system_total_mb / 2.0
        if display_total is None and system_total_mb is not None:
            display_total = system_total_mb

        snap.memory = MemoryInfo(
            mem_model="shared",
            used_mb=used_shared,
            total_mb=shared_total or display_total or 0.0,
            host_total_mb=display_total or 0.0,
            host_used_mb=used_shared,
            driver_reserved_mb=dedicated_total if dedicated_total else None,
        )
        snap.caps.update({
            "utilization": bool(luid),
            "memory": True,
            "temperature": False,
            "power": False,
            "mem_clock": False,
            "per_process_gpu_pct": False,
        })
        snap.sources["telemetry"] = "windows-performance-counters"
        snap.gaps["temperature"] = "Windows performance counters do not expose Intel package temperature here."
        snap.gaps["power"] = "Windows performance counters do not expose Intel GPU power draw here."

        if not luid:
            snap.gaps["utilization"] = "No active GPU engine counter matched this adapter."
            return

        engine_info = counters["engines"].get(luid, {})
        rollup = self._roll_up_engines(engine_info)
        snap.util_pct = rollup["total"]
        snap.engine = rollup["engine"]
        snap.sources["luid"] = luid

    def _pick_luid_for_integrated(self, counters, used_luids):
        candidates = []
        for luid in set(counters["shared_mb"]) | set(counters["engines"]):
            if luid in used_luids:
                continue
            shared = counters["shared_mb"].get(luid, 0.0)
            util = self._roll_up_engines(counters["engines"].get(luid, {}))["total"] or 0.0
            candidates.append((shared, util, luid))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][2]

    def _pick_luid_for_discrete(self, counters, used_luids):
        candidates = []
        for luid in set(counters["dedicated_mb"]) | set(counters["engines"]):
            if luid in used_luids:
                continue
            dedicated = counters["dedicated_mb"].get(luid, 0.0)
            shared = counters["shared_mb"].get(luid, 0.0)
            util = self._roll_up_engines(counters["engines"].get(luid, {}))["total"] or 0.0
            candidates.append((dedicated, util, -shared, luid))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][3]

    def _roll_up_engines(self, engine_info):
        totals = {
            "graphics_3d": 0.0,
            "compute": 0.0,
            "video_encode": 0.0,
            "video_decode": 0.0,
            "copy_dma": 0.0,
        }
        busiest = 0.0

        for engine in engine_info.values():
            value = max(0.0, float(engine["value"]))
            busiest = max(busiest, value)
            engine_type = engine["type"]
            if engine_type in ("3d", "graphics"):
                totals["graphics_3d"] += value
            elif engine_type in ("compute",):
                totals["compute"] += value
            elif engine_type in ("videoencode",):
                totals["video_encode"] += value
            elif engine_type in ("videodecode",):
                totals["video_decode"] += value
            elif engine_type in ("copy",):
                totals["copy_dma"] += value

        for key in totals:
            totals[key] = min(100.0, totals[key]) if totals[key] else None

        return {
            # Task Manager's default GPU percentage on Windows typically follows
            # the busiest engine rather than summing every engine simultaneously.
            "total": min(100.0, busiest) if busiest else None,
            "engine": EngineUtilization(**totals),
        }

    def _parse_mb(self, value):
        if not value:
            return None
        match = re.search(r"([\d,]+)", value)
        if not match:
            return None
        return float(match.group(1).replace(",", ""))

    def _system_ram_mb(self):
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return status.ullTotalPhys / (1024 * 1024)

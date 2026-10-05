"""Optional process/system telemetry; missing sensors remain null, never zero."""
import csv
import io
import platform
import threading
import time

from .common import GIB, command, environment_kind

try:
    import psutil
except ImportError:
    psutil = None


def gpu_snapshot():
    fields = "index,name,driver_version,memory.total,memory.used,utilization.gpu,power.draw,temperature.gpu,clocks.sm"
    raw = command(["nvidia-smi", "--query-gpu=" + fields, "--format=csv,noheader,nounits"], timeout=3)
    if raw is None:
        return []
    rows = []
    for values in csv.reader(io.StringIO(raw)):
        if len(values) != 9:
            continue
        row = dict(zip(["index", "name", "driver_version", "total_mib", "used_mib", "utilization_pct",
                        "power_w", "temperature_c", "sm_clock_mhz"], (v.strip() for v in values)))
        for key in list(row)[3:]:
            try:
                row[key] = float(row[key])
            except ValueError:
                row[key] = None
        rows.append(row)
    return rows


def host_snapshot():
    out = {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
           "processor": platform.processor(), "python": platform.python_version(),
           "environment_kind": environment_kind(), "gpus": gpu_snapshot(),
           "memory_scope": "wsl_guest" if "wsl2" in environment_kind() else "host",
           "psutil_available": psutil is not None}
    if psutil:
        mem = psutil.virtual_memory()
        out.update(ram_total_gib=mem.total / GIB, ram_available_gib=mem.available / GIB,
                   logical_cpus=psutil.cpu_count(), physical_cores=psutil.cpu_count(logical=False))
        try:
            battery = psutil.sensors_battery()
        except (OSError, NotImplementedError, AttributeError):
            battery = None
        out["ac_connected"] = battery.power_plugged if battery else None
    try:
        out["os_release"] = platform.freedesktop_os_release()
    except (OSError, AttributeError):
        pass
    return out


class Sampler:
    def __init__(self, backend_pid=None, interval=1.0):
        self.pid = backend_pid
        self.interval = interval
        self.samples = []
        self.stop_event = threading.Event()
        self.thread = None

    def sample(self):
        row = {"monotonic_s": time.monotonic(), "gpus": gpu_snapshot()}
        if psutil:
            mem, swap = psutil.virtual_memory(), psutil.swap_memory()
            row.update(system_used_gib=(mem.total - mem.available) / GIB, available_gib=mem.available / GIB,
                       swap_used_gib=swap.used / GIB, swap_in_bytes=getattr(swap, "sin", None),
                       swap_out_bytes=getattr(swap, "sout", None), cpu_percent=psutil.cpu_percent())
            disk = psutil.disk_io_counters()
            if disk:
                row.update(system_disk_read_bytes=disk.read_bytes, system_disk_write_bytes=disk.write_bytes)
            if self.pid:
                try:
                    parent = psutil.Process(self.pid)
                    processes = [parent] + parent.children(recursive=True)
                    # RSS sum is an upper bound when processes share pages; not unique physical memory.
                    row["backend_tree_rss_gib"] = sum(p.memory_info().rss for p in processes) / GIB
                except (psutil.Error, ProcessLookupError):
                    row["backend_tree_rss_gib"] = None
        self.samples.append(row)

    def _loop(self):
        while not self.stop_event.wait(self.interval):
            try:
                self.sample()
            except (OSError, RuntimeError) as exc:
                self.samples.append({"monotonic_s": time.monotonic(), "gpus": [], "sensor_error": type(exc).__name__})

    def __enter__(self):
        self.sample()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop_event.set()
        self.thread.join(timeout=5)
        self.sample()

    def summary(self):
        def peak(key):
            values = [s[key] for s in self.samples if s.get(key) is not None]
            return max(values) if values else None
        gpu_used = [g["used_mib"] for s in self.samples for g in s["gpus"] if g["used_mib"] is not None]
        return {"samples": len(self.samples), "interval_s": self.interval,
                "system_used_gib_peak": peak("system_used_gib"), "swap_used_gib_peak": peak("swap_used_gib"),
                "backend_tree_rss_gib_peak": peak("backend_tree_rss_gib"),
                "gpu_used_mib_peak": max(gpu_used) if gpu_used else None,
                "backend_pid_supplied": self.pid is not None,
                "limitations": "Sampled peaks can miss transients; GPU/system counters include other applications; RSS may double count shared pages; WSL excludes Windows host usage."}

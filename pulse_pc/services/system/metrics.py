"""Live system metrics. Values that cannot be read are None (shown as «Недоступно»),
never a guessed number.

`MetricsSampler` is plain Python (testable without Qt); `MetricsService` runs it in a
background thread so slow drives or counters never freeze the window.
"""
import logging
import platform
import socket
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import psutil

logger = logging.getLogger(__name__)


@dataclass
class Disk:
    mount: str
    used: int
    total: int

    @property
    def percent(self):
        return 100.0 * self.used / self.total if self.total else 0.0


@dataclass
class Snapshot:
    time: float
    cpu: Optional[float] = None
    cpu_freq_mhz: Optional[float] = None
    cpu_cores: Optional[int] = None
    cpu_per_core: list = field(default_factory=list)   # load of each logical core, %
    ram_used: Optional[int] = None
    ram_total: Optional[int] = None
    gpu: Optional[float] = None
    gpu_memory_used: Optional[int] = None
    gpu_memory_total: Optional[int] = None
    gpu_name: str = ""
    cpu_name: str = ""
    disks: list = field(default_factory=list)
    net_down: Optional[float] = None    # bytes per second
    net_up: Optional[float] = None
    uptime: Optional[float] = None      # seconds since boot
    processes: Optional[int] = None
    battery: Optional[float] = None
    plugged: Optional[bool] = None

    @property
    def ram(self):
        return 100.0 * self.ram_used / self.ram_total if self.ram_used is not None and self.ram_total else None

    @property
    def system_disk(self):
        return next((d for d in self.disks if d.mount.upper().startswith("C:")), self.disks[0] if self.disks else None)


class GpuCounters:
    """GPU load from the Windows «GPU Engine» performance counters (same source as Task
    Manager): per adapter and engine type the per-process values are summed, the busiest
    engine is the GPU load. Unavailable on old drivers, remote sessions and VMs."""

    def __init__(self):
        self.query = None
        try:
            import win32pdh
            self._pdh = win32pdh
            self.query = win32pdh.OpenQuery()
            self.engine = win32pdh.AddEnglishCounter(self.query, r"\GPU Engine(*)\Utilization Percentage")
            self.memory = win32pdh.AddEnglishCounter(self.query, r"\GPU Adapter Memory(*)\Dedicated Usage")
            win32pdh.CollectQueryData(self.query)
        except Exception as exc:  # noqa: BLE001 - any failure means «no GPU data»
            logger.info("GPU counters unavailable: %s", exc)
            self.query = None

    @property
    def available(self):
        return self.query is not None

    def read(self):
        """(load %, dedicated memory bytes) or (None, None)."""
        if not self.query:
            return None, None
        pdh = self._pdh
        try:
            pdh.CollectQueryData(self.query)
            engines = pdh.GetFormattedCounterArray(self.engine, pdh.PDH_FMT_DOUBLE)
        except Exception:  # noqa: BLE001 - counters vanish when a process exits mid-read
            return None, None
        load = aggregate_engines(engines)
        try:
            memory = pdh.GetFormattedCounterArray(self.memory, pdh.PDH_FMT_LARGE)
            used = max(memory.values()) if memory else None
        except Exception:  # noqa: BLE001
            used = None
        return load, used

    def close(self):
        if self.query:
            try:
                self._pdh.CloseQuery(self.query)
            except Exception:  # noqa: BLE001
                pass
            self.query = None


def aggregate_engines(values):
    """{'pid_1_luid_X_phys_0_eng_0_engtype_3D': 12.5, ...} -> busiest engine load, 0..100."""
    if not values:
        return None
    totals = defaultdict(float)
    for name, value in values.items():
        luid = name.split("_luid_", 1)[-1].split("_eng_", 1)[0]
        engine = name.rsplit("engtype_", 1)[-1]
        totals[(luid, engine)] += value
    return min(100.0, max(totals.values()))


def gpu_adapters():
    """[(name, video memory bytes or None)] of real display adapters, from the registry."""
    import winreg
    key = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    found = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as root:
            for index in range(winreg.QueryInfoKey(root)[0]):
                sub = winreg.EnumKey(root, index)
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as adapter:
                        name = winreg.QueryValueEx(adapter, "DriverDesc")[0]
                        memory = None
                        for value in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                            try:
                                raw = winreg.QueryValueEx(adapter, value)[0]
                            except OSError:
                                continue
                            memory = raw if isinstance(raw, int) else int.from_bytes(raw[:8], "little")
                            break
                        found.append((name, memory))
                except OSError:
                    continue
    except OSError:
        return []
    return [a for a in found if "basic" not in a[0].lower() and "remote" not in a[0].lower()] or found


def main_gpu():
    """The adapter with the most video memory (the discrete card in a laptop), or (\"\", None)."""
    adapters = gpu_adapters()
    return max(adapters, key=lambda a: a[1] or 0) if adapters else ("", None)


def gpu_name():
    return main_gpu()[0]


def cpu_name():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            return " ".join(str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).split())
    except OSError:
        return ""


def read_disks():
    disks = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype or "remote" in part.opts:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        disks.append(Disk(part.mountpoint.rstrip("\\"), usage.used, usage.total))
    return disks


def host_info():
    return {"name": socket.gethostname(), "os": f"{platform.system()} {platform.release()}",
            "addresses": lan_addresses()}


def lan_addresses():
    found = []
    for name, items in psutil.net_if_addrs().items():
        stats = psutil.net_if_stats().get(name)
        if stats and not stats.isup:
            continue
        for item in items:
            if item.family == socket.AF_INET and not item.address.startswith(("127.", "169.254.")):
                found.append(item.address)
    return found


class MetricsSampler:
    def __init__(self, gpu=None, clock=time.monotonic):
        self.clock = clock
        self.gpu = gpu if gpu is not None else GpuCounters()
        self.gpu_name, self.gpu_memory_total = main_gpu()
        self.cpu_name = cpu_name()
        self._net = None
        self._disks, self._disks_at = [], -1e9
        psutil.cpu_percent(None)  # first call primes the counter
        psutil.cpu_percent(None, percpu=True)

    def sample(self):
        now = self.clock()
        snap = Snapshot(time=now, gpu_name=self.gpu_name, gpu_memory_total=self.gpu_memory_total,
                        cpu_name=self.cpu_name)
        snap.cpu = psutil.cpu_percent(None)
        snap.cpu_cores = psutil.cpu_count(logical=True)
        snap.cpu_per_core = psutil.cpu_percent(None, percpu=True)
        try:
            freq = psutil.cpu_freq()
            snap.cpu_freq_mhz = freq.current if freq and freq.current else None
        except (OSError, RuntimeError):
            pass
        memory = psutil.virtual_memory()
        snap.ram_used, snap.ram_total = memory.total - memory.available, memory.total
        snap.gpu, snap.gpu_memory_used = self.gpu.read()
        if now - self._disks_at > 10:   # disk sizes change slowly; avoid waking drives every second
            self._disks, self._disks_at = read_disks(), now
        snap.disks = list(self._disks)
        try:
            counters = psutil.net_io_counters()
        except OSError:
            counters = None
        if counters:
            if self._net:
                elapsed = max(now - self._net[0], 1e-3)
                snap.net_down = max(0, counters.bytes_recv - self._net[1]) / elapsed
                snap.net_up = max(0, counters.bytes_sent - self._net[2]) / elapsed
            self._net = (now, counters.bytes_recv, counters.bytes_sent)
        snap.uptime = max(0.0, time.time() - psutil.boot_time())
        try:
            snap.processes = len(psutil.pids())
        except OSError:
            pass
        try:
            battery = psutil.sensors_battery()
        except (OSError, RuntimeError):
            battery = None
        if battery:
            snap.battery, snap.plugged = battery.percent, battery.power_plugged
        return snap

    def close(self):
        self.gpu.close()


def format_bytes(size, per_second=False):
    if size is None:
        return "—"
    units = ("Б", "КБ", "МБ", "ГБ", "ТБ")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            text = f"{value:.0f} {unit}" if unit == "Б" or value >= 100 else f"{value:.1f} {unit}"
            return text + ("/с" if per_second else "")
        value /= 1024


def format_uptime(seconds):
    if seconds is None:
        return "—"
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days} д {hours} ч"
    return f"{hours} ч {minutes} мин" if hours else f"{minutes} мин"


try:
    from PySide6.QtCore import QObject, Signal
except ImportError:  # the sampler stays usable without Qt
    QObject = None

if QObject is not None:
    class MetricsService(QObject):
        """Samples every `interval` seconds in a daemon thread and emits `updated(Snapshot)`."""

        updated = Signal(object)

        def __init__(self, interval=1.0, sampler_factory=MetricsSampler, parent=None):
            super().__init__(parent)
            self.interval = interval
            self.sampler_factory = sampler_factory
            self.latest = None
            self._stop = threading.Event()
            self._thread = None

        def start(self):
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="PulsePC-metrics", daemon=True)
            self._thread.start()

        def stop(self, timeout=2.0):
            self._stop.set()
            if self._thread:
                self._thread.join(timeout)

        def _run(self):
            # PDH queries belong to the thread that created them.
            sampler = self.sampler_factory()
            try:
                while not self._stop.is_set():
                    try:
                        self.latest = sampler.sample()
                        self.updated.emit(self.latest)
                    except Exception:  # noqa: BLE001 - keep sampling after a transient failure
                        logger.exception("Metrics sample failed")
                    self._stop.wait(self.interval)
            finally:
                sampler.close()

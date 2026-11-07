"""Host metrics from facilities that already exist on this machine.

Sources: ``/proc/stat`` (CPU), ``/proc/meminfo`` (RAM/swap), ``/proc/uptime``,
``/proc/net/dev`` (throughput), ``os.statvfs`` on the mounted ext4 filesystems,
``sensors`` for package temperature and ``nvidia-smi`` for the discrete GPU.

A background sampler keeps the deltas (CPU %, network rate) warm so API responses are
instant and never block on a 1-second sample. Anything that cannot be read is returned as
``None``/``available=false`` with a reason — never as a fabricated number.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings
from ..schemas import (
    DiskUsage,
    NetworkThroughput,
    ServerCpu,
    ServerGpu,
    ServerMemory,
    ServerOverview,
)

FAKE_FS = {
    "proc",
    "sysfs",
    "devtmpfs",
    "devpts",
    "tmpfs",
    "cgroup",
    "cgroup2",
    "overlay",
    "efivarfs",
    "squashfs",
    "ramfs",
    "autofs",
    "tracefs",
    "debugfs",
    "securityfs",
    "pstore",
    "bpf",
    "mqueue",
    "hugetlbfs",
    "fusectl",
    "configfs",
    "binfmt_misc",
    "nsfs",
    "rpc_pipefs",
}
REAL_FS = {"ext4", "ext3", "xfs", "btrfs", "zfs", "f2fs"}


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


@dataclass
class CpuSample:
    total: int = 0
    idle: int = 0
    per_core: list[tuple[int, int]] = field(default_factory=list)


def _read_cpu() -> CpuSample:
    text = _read("/proc/stat") or ""
    sample = CpuSample()
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        name = parts[0]
        values = [int(v) for v in parts[1:] if v.isdigit()]
        if len(values) < 4:
            continue
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        if name == "cpu":
            sample.total, sample.idle = total, idle
        elif name[3:].isdigit():
            sample.per_core.append((total, idle))
    return sample


def _pct(previous: tuple[int, int] | None, current: tuple[int, int]) -> float | None:
    if previous is None:
        return None
    total_delta = current[0] - previous[0]
    idle_delta = current[1] - previous[1]
    if total_delta <= 0:
        return None
    busy = max(0, total_delta - idle_delta)
    return round(100.0 * busy / total_delta, 1)


def _read_memory() -> ServerMemory | None:
    text = _read("/proc/meminfo")
    if not text:
        return None
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key] = int(parts[0]) * 1024
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    used = max(0, total - available)
    swap_total = values.get("SwapTotal", 0)
    swap_free = values.get("SwapFree", 0)
    swap_used = max(0, swap_total - swap_free)
    return ServerMemory(
        total_bytes=total,
        used_bytes=used,
        available_bytes=available,
        percent=round(100.0 * used / total, 1) if total else 0.0,
        swap_total_bytes=swap_total,
        swap_used_bytes=swap_used,
        swap_percent=round(100.0 * swap_used / swap_total, 1) if swap_total else 0.0,
    )


def _read_net(interface: str | None) -> tuple[dict[str, tuple[int, int]], str | None]:
    text = _read("/proc/net/dev") or ""
    result: dict[str, tuple[int, int]] = {}
    chosen = None
    for line in text.splitlines()[2:]:
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        name = name.strip()
        parts = rest.split()
        if len(parts) < 9:
            continue
        rx, tx = int(parts[0]), int(parts[8])
        result[name] = (rx, tx)
        if interface and name == interface:
            chosen = name
    if interface:
        return result, chosen
    candidates = [
        (rx + tx, name)
        for name, (rx, tx) in result.items()
        if name != "lo" and not name.startswith(("docker", "br-", "veth", "virbr"))
    ]
    if candidates:
        chosen = max(candidates)[1]
    return result, chosen


def _read_temperature() -> float | None:
    sensors = shutil.which("sensors")
    if not sensors:
        return None
    try:
        proc = subprocess.run(
            [sensors], capture_output=True, text=True, timeout=4, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in proc.stdout.splitlines():
        if line.startswith("Package id 0:"):
            for token in line.replace("+", " ").replace("°C", " C").split():
                try:
                    value = float(token)
                except ValueError:
                    continue
                if -20 < value < 150:
                    return value
    return None


def _read_gpu() -> ServerGpu:
    nvidia = shutil.which("nvidia-smi")
    if not nvidia:
        return ServerGpu(available=False, error="nvidia-smi not installed")
    try:
        proc = subprocess.run(
            [
                nvidia,
                "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ServerGpu(available=False, error=f"nvidia-smi failed: {exc}")
    if proc.returncode != 0 or not proc.stdout.strip():
        message = (proc.stderr or proc.stdout or "no output").strip().splitlines()
        return ServerGpu(available=False, error=message[0][:200] if message else "no output")
    first = proc.stdout.strip().splitlines()[0]
    parts = [part.strip() for part in first.split(",")]
    if len(parts) < 6:
        return ServerGpu(available=False, error="unexpected nvidia-smi output")
    try:
        return ServerGpu(
            available=True,
            name=parts[0],
            utilization_percent=float(parts[1]),
            temperature_c=float(parts[2]),
            memory_used_bytes=int(float(parts[3])) * 1024 * 1024,
            memory_total_bytes=int(float(parts[4])) * 1024 * 1024,
            power_w=float(parts[5]),
        )
    except ValueError:
        return ServerGpu(available=False, error=f"unparsable nvidia-smi output: {first[:120]}")


def mounted_filesystems() -> list[tuple[str, str]]:
    text = _read("/proc/mounts") or ""
    seen_devices: set[str] = set()
    result: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mount, fstype = parts[0], parts[1].replace("\\040", " "), parts[2]
        if fstype not in REAL_FS or fstype in FAKE_FS:
            continue
        if device in seen_devices:
            continue
        seen_devices.add(device)
        result.append((mount, fstype))
    result.sort(key=lambda item: item[0].count("/"))
    return result


def disk_usage() -> list[DiskUsage]:
    disks: list[DiskUsage] = []
    for mount, fstype in mounted_filesystems():
        try:
            stats = os.statvfs(mount)
        except OSError:
            continue
        total = stats.f_blocks * stats.f_frsize
        free = stats.f_bavail * stats.f_frsize
        used = total - stats.f_bfree * stats.f_frsize
        if total <= 0:
            continue
        disks.append(
            DiskUsage(
                mount=mount,
                filesystem=fstype,
                total_bytes=total,
                used_bytes=used,
                free_bytes=free,
                percent=round(100.0 * used / total, 1),
            )
        )
    return disks


class Sampler:
    """Background sampler for CPU and network deltas."""

    def __init__(self, interval: float = 2.0) -> None:
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.cpu_percent: float | None = None
        self.per_core: list[float] = []
        self.net_rx_rate: float | None = None
        self.net_tx_rate: float | None = None
        self.net_interface: str | None = None
        self.net_totals: tuple[int, int] | None = None
        self.temperature_c: float | None = None
        self._last_cpu: CpuSample | None = None
        self._last_net: tuple[int, int, float] | None = None
        self._temperature_at = 0.0
        self.started = False

    def sample(self) -> None:
        cpu = _read_cpu()
        with self._lock:
            if self._last_cpu is not None:
                self.cpu_percent = _pct((self._last_cpu.total, self._last_cpu.idle), (cpu.total, cpu.idle))
                per_core: list[float] = []
                for previous, current in zip(self._last_cpu.per_core, cpu.per_core):
                    value = _pct(previous, current)
                    if value is not None:
                        per_core.append(value)
                if per_core:
                    self.per_core = per_core
            self._last_cpu = cpu

        nets, interface = _read_net(self.net_interface)
        now = time.monotonic()
        with self._lock:
            if interface and interface in nets:
                rx, tx = nets[interface]
                self.net_interface = interface
                self.net_totals = (rx, tx)
                if self._last_net is not None and self._last_net[2] > 0:
                    elapsed = now - self._last_net[2]
                    if elapsed > 0:
                        self.net_rx_rate = max(0.0, (rx - self._last_net[0]) / elapsed)
                        self.net_tx_rate = max(0.0, (tx - self._last_net[1]) / elapsed)
                self._last_net = (rx, tx, now)

        if now - self._temperature_at > 5:
            temperature = _read_temperature()
            with self._lock:
                self.temperature_c = temperature
            self._temperature_at = now

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.sample()
            except Exception:  # pragma: no cover - sampler must never crash the app
                continue

    def start(self) -> None:
        if self._thread is not None:
            return
        self.sample()
        self._thread = threading.Thread(target=self._run, name="metrics-sampler", daemon=True)
        self._thread.start()
        self.started = True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        self.started = False

    def state(self) -> dict:
        with self._lock:
            return {
                "cpu_percent": self.cpu_percent,
                "per_core": list(self.per_core),
                "net_rx_rate": self.net_rx_rate,
                "net_tx_rate": self.net_tx_rate,
                "net_interface": self.net_interface,
                "net_totals": self.net_totals,
                "temperature_c": self.temperature_c,
            }


_sampler = Sampler()


def get_sampler() -> Sampler:
    return _sampler


def _uptime() -> float | None:
    text = _read("/proc/uptime")
    if not text:
        return None
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        return None


def _cpu_model() -> tuple[str, int]:
    text = _read("/proc/cpuinfo") or ""
    model = ""
    cores = 0
    for line in text.splitlines():
        if line.startswith("model name") and not model:
            model = line.split(":", 1)[1].strip()
        if line.startswith("processor"):
            cores += 1
    return model, cores


_gpu_cache: tuple[float, ServerGpu] | None = None


def gpu_snapshot(max_age: float = 3.0) -> ServerGpu:
    global _gpu_cache
    now = time.monotonic()
    if _gpu_cache is not None and now - _gpu_cache[0] < max_age:
        return _gpu_cache[1]
    value = _read_gpu()
    _gpu_cache = (now, value)
    return value


def overview(settings: Settings) -> ServerOverview:
    state = _sampler.state()
    load: list[float] = []
    try:
        load = [round(value, 2) for value in os.getloadavg()]
    except OSError:
        load = []
    model, cores = _cpu_model()
    memory = _read_memory()
    totals = state.get("net_totals")
    network = None
    if state.get("net_interface") and totals:
        network = NetworkThroughput(
            interface=state["net_interface"],
            rx_bytes_per_second=round(state.get("net_rx_rate") or 0.0, 1),
            tx_bytes_per_second=round(state.get("net_tx_rate") or 0.0, 1),
            rx_bytes_total=totals[0],
            tx_bytes_total=totals[1],
        )
    unavailable: list[str] = []
    gpu = gpu_snapshot()
    if not gpu.available:
        unavailable.append(f"gpu: {gpu.error or 'unavailable'}")
    if memory is None:
        unavailable.append("memory: /proc/meminfo unreadable")
    if state.get("temperature_c") is None:
        unavailable.append("cpu_temperature: sensors output unavailable")
    return ServerOverview(
        generated_at=time.time(),
        uptime_seconds=_uptime(),
        cpu=ServerCpu(
            percent=state.get("cpu_percent"),
            per_core=state.get("per_core") or [],
            load=load,
            temperature_c=state.get("temperature_c"),
            model=model,
            cores=cores,
        ),
        memory=memory,
        gpu=gpu,
        disks=disk_usage(),
        network=network,
        docker=[],
        docker_available=False,
        unavailable=unavailable,
    )

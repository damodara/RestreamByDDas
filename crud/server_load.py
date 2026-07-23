import os
import shutil


def _read_mem_used_percent():
    try:
        with open("/proc/meminfo") as f:
            fields = {}
            for line in f:
                key, value = line.split(":", 1)
                fields[key] = int(value.strip().split()[0])
    except (FileNotFoundError, ValueError, KeyError):
        return None

    total = fields.get("MemTotal")
    available = fields.get("MemAvailable")
    if not total or available is None:
        return None
    return round((total - available) / total * 100, 1)


def _read_disk_used_percent():
    try:
        usage = shutil.disk_usage("/")
    except OSError:
        return None
    if usage.total == 0:
        return None
    return round(usage.used / usage.total * 100, 1)


def get_server_load():
    load1, load5, load15 = os.getloadavg()
    return {
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "mem_used_percent": _read_mem_used_percent(),
        "disk_used_percent": _read_disk_used_percent(),
    }

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


def _level(percent):
    """Категория для цвета CSS-индикатора; unknown — когда метрика недоступна."""
    if percent is None:
        return "unknown"
    if percent >= 85:
        return "danger"
    if percent >= 60:
        return "warn"
    return "ok"


def get_server_load():
    load1, load5, load15 = os.getloadavg()
    cpu_count = os.cpu_count() or 1
    # Load average не процент сам по себе (зависит от числа ядер) — для
    # круговых индикаторов на фронте нормализуем к % загрузки ядер,
    # capped на 100 (кольцо не может быть больше полного круга), сырые
    # load1/5/15 всё равно отдаём как есть для текста рядом.
    load1_percent = min(round(load1 / cpu_count * 100), 100)
    mem_used_percent = _read_mem_used_percent()
    disk_used_percent = _read_disk_used_percent()
    return {
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "cpu_count": cpu_count,
        "load1_percent": load1_percent,
        "load1_level": _level(load1_percent),
        "mem_used_percent": mem_used_percent,
        "mem_level": _level(mem_used_percent),
        "disk_used_percent": disk_used_percent,
        "disk_level": _level(disk_used_percent),
    }

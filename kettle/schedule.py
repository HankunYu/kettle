"""Probe time slots from [schedule].times in config.toml.

A question is due when its last probe is older than the most recent slot.
Deciding per question (instead of "run once at 09:30") makes every driver
idempotent: missed slots are caught up after downtime or sleep, a restart
mid-run resumes where it stopped, and the serve scheduler, a systemd timer
or cron can all run `run` without probing anything twice.
"""

from datetime import datetime, time, timedelta

from .config import ConfigError

DEFAULT_TIMES = ["09:30"]


def parse_times(cfg):
    raw = cfg.get("schedule", {}).get("times", DEFAULT_TIMES)
    if not isinstance(raw, list):
        raise ConfigError("[schedule].times 必须是列表,例如 [\"09:30\", \"21:30\"]")
    times = []
    for value in raw:
        try:
            times.append(time.fromisoformat(str(value)))
        except ValueError:
            raise ConfigError(f"[schedule].times 里的时间格式不对: {value!r}(应为 HH:MM)") from None
    return sorted(set(times))


def _slots_around(times, now):
    # Naive local datetimes become aware in local time, which keeps slots on
    # the wall clock across DST changes.
    for days in (-1, 0, 1):
        day = (now + timedelta(days=days)).date()
        for t in times:
            yield datetime.combine(day, t).astimezone()


def latest_slot(times, now=None):
    """The most recent slot at or before now, or None if there are no times."""
    now = now or datetime.now().astimezone()
    past = [s for s in _slots_around(times, now) if s <= now]
    return max(past, default=None)


def next_slot(times, now=None):
    now = now or datetime.now().astimezone()
    future = [s for s in _slots_around(times, now) if s > now]
    return min(future, default=None)

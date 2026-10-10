"""Background thread in `kettle serve` that probes due questions on schedule."""

import sys
import threading

from . import schedule, service
from .config import load_config, now_iso

TICK_SECONDS = 60


class Scheduler(threading.Thread):
    def __init__(self):
        super().__init__(name="kettle-scheduler", daemon=True)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._current = None
        self._last_tick = None
        self._last_error = None

    def run(self):
        while True:
            self._tick()
            if self._stop_event.wait(TICK_SECONDS):
                return

    def stop(self):
        self._stop_event.set()

    def _tick(self):
        # Config is re-read every tick so schedule edits apply without a restart.
        try:
            cfg = load_config()
            slot = schedule.latest_slot(schedule.parse_times(cfg))
            due = service.due_questions(slot) if slot else []
            for q in due:
                if self._stop_event.is_set():
                    return
                self._set(current=q["id"])
                service.probe_one(cfg, q, slot=slot)
            self._set(last_error=None)
        except Exception as e:
            print(f"[scheduler] tick failed: {e}", file=sys.stderr)
            self._set(last_error=str(e))
        finally:
            self._set(current=None, last_tick=now_iso())

    def _set(self, **fields):
        with self._lock:
            for key, value in fields.items():
                setattr(self, f"_{key}", value)

    def status(self):
        try:
            times = schedule.parse_times(load_config())
            next_run = schedule.next_slot(times)
            config_error = None
        except Exception as e:
            times, next_run, config_error = [], None, str(e)
        with self._lock:
            return {
                "times": [t.strftime("%H:%M") for t in times],
                "next_run": next_run.isoformat(timespec="minutes") if next_run else None,
                "current": self._current,
                "last_tick": self._last_tick,
                "error": config_error or self._last_error,
            }

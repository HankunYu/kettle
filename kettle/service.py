"""Operations shared by the CLI and the web server."""

import sys
from datetime import datetime, timedelta

from . import schedule, store
from .config import now_iso
from .engines import task_settings
from .notify import notify
from .research import run_analyze, run_probe

ERROR_NOTIFY_THRESHOLD = 3  # consecutive probe failures before a warning push


def question_view(q, entry=None):
    """A question merged with its state, as shown by `list` and the API."""
    entry = entry or store.get_state_entry(q["id"])
    return {
        **q,
        "status": entry.get("status", "watching"),
        "last_probe": entry.get("last_probe"),
        "last_result": entry.get("last_result"),
        "last_error": entry.get("last_error"),
        "consecutive_errors": entry.get("consecutive_errors", 0),
        "resolved_at": entry.get("resolved_at"),
        "probing": bool(entry.get("probing_since")),
    }


def list_views():
    state = store.load_state()
    return [question_view(q, state.get(q["id"])) for q in store.load_questions()]


def watching_questions():
    state = store.load_state()
    return [
        q for q in store.load_questions()
        if state.get(q["id"], {}).get("status", "watching") == "watching"
    ]


def _parse_time(iso):
    return datetime.fromisoformat(iso) if iso else None


def _probed_since(entry, slot):
    last = _parse_time(entry.get("last_probe"))
    return last is not None and last >= slot


def due_questions(slot):
    """Watching questions not probed since the given slot."""
    state = store.load_state()
    return [
        q for q in watching_questions()
        if not _probed_since(state.get(q["id"], {}), slot)
    ]


def run_due(cfg):
    """Probe every question that is due for the latest schedule slot."""
    slot = schedule.latest_slot(schedule.parse_times(cfg))
    if slot is None:
        return []
    return [probe_one(cfg, q, slot=slot) for q in due_questions(slot)]


def _claim(qid, slot, stale_after):
    """Mark a question as being probed. Returns a skip reason, or None if claimed.

    With a slot, also re-checks under the lock that the question is still due,
    so concurrent drivers (serve scheduler, timer) never probe it twice.
    """
    skip = []

    def mutate(entry):
        now = datetime.now().astimezone()
        since = _parse_time(entry.get("probing_since"))
        if since and now - since < stale_after:
            skip.append("正在探测中")
        elif slot and (entry.get("status") != "watching" or _probed_since(entry, slot)):
            skip.append("本时段已探测")
        else:
            entry["probing_since"] = now_iso()

    store.update_state(qid, mutate)
    return skip[0] if skip else None


def _release(qid):
    store.update_state(qid, lambda entry: entry.pop("probing_since", None))


def probe_one(cfg, q, do_notify=True, slot=None):
    """Probe a single question, update state, notify if resolved.

    slot: when probing for a schedule slot, skip if it was already probed since.
    Returns an outcome dict: {"id", "result"}, {"id", "error"} or {"id", "skipped"}.
    """
    qid = q["id"]
    # A claim older than two timeouts belongs to a process that died mid-probe.
    stale_after = timedelta(seconds=2 * task_settings(cfg, "probe")["timeout"])
    reason = _claim(qid, slot, stale_after)
    if reason:
        print(f"[{qid}] skipped: {reason}")
        return {"id": qid, "skipped": reason}
    try:
        return _probe_claimed(cfg, q, do_notify)
    finally:
        _release(qid)


def _probe_claimed(cfg, q, do_notify):
    qid = q["id"]
    print(f"[{qid}] probing...")
    try:
        result = run_probe(cfg, q)
    except Exception as e:
        def record_error(entry):
            entry["consecutive_errors"] = entry.get("consecutive_errors", 0) + 1
            entry["last_probe"] = now_iso()
            entry["last_error"] = str(e)

        entry = store.update_state(qid, record_error)
        store.append_log({"time": now_iso(), "id": qid, "error": str(e)})
        print(f"[{qid}] probe failed: {e}", file=sys.stderr)
        if do_notify and entry["consecutive_errors"] == ERROR_NOTIFY_THRESHOLD:
            try:
                notify(cfg, "kettle 探测异常", f"「{q['question']}」已连续 {ERROR_NOTIFY_THRESHOLD} 次探测失败,最近错误:{e}")
            except Exception as ne:
                print(f"[{qid}] error notify failed: {ne}", file=sys.stderr)
        return {"id": qid, "error": str(e)}

    def record_result(entry):
        entry["consecutive_errors"] = 0
        entry.pop("last_error", None)
        entry["last_probe"] = now_iso()
        entry["last_result"] = result

    store.update_state(qid, record_result)
    store.append_log({"time": now_iso(), "id": qid, "result": result})
    print(f"[{qid}] resolved={result['resolved']} confidence={result['confidence']}")
    print(f"[{qid}] {result['summary']}")
    outcome = {"id": qid, "result": result}

    if not result["resolved"]:
        return outcome

    if not do_notify:
        print(f"[{qid}] resolved, but notify disabled; state left as watching")
        return outcome

    sources = result.get("sources", [])
    body = result["summary"]
    if sources:
        body += "\n" + "\n".join(sources[:3])
    try:
        notify(cfg, f"🫖 {q['question']}", body, url=sources[0] if sources else None)
    except Exception as e:
        # Keep status watching so the next run retries the notification.
        print(f"[{qid}] resolved but notify failed, will retry next run: {e}", file=sys.stderr)
        return outcome

    def mark_resolved(entry):
        entry["status"] = "resolved"
        entry["resolved_at"] = now_iso()

    store.update_state(qid, mark_resolved)
    print(f"[{qid}] notified and marked resolved")
    return outcome


def reset(qid):
    if store.get_question(qid) is None:
        raise store.StoreError(f"未找到问题 id: {qid}")

    def to_watching(entry):
        entry["status"] = "watching"
        entry["resolved_at"] = None

    store.update_state(qid, to_watching)


def analyze_and_add(cfg, intent, do_notify=True):
    """Research an intent and, unless it already happened, start monitoring it.

    The analysis doubles as the first probe: its findings seed the state so
    the question shows its current status right away.
    Returns {"added": bool, "analysis": {...}, "question": {...} | None}.
    """
    print(f"[analyze] {intent}")
    analysis = run_analyze(cfg, intent)
    print(f"[analyze] already_resolved={analysis['already_resolved']} id={analysis['id']}")

    if analysis["already_resolved"]:
        if do_notify:
            _notify_quietly(cfg, "🫖 已经发生了,未加入监控", f"{analysis['question']}\n{analysis['summary']}",
                            (analysis["sources"] or [None])[0])
        return {"added": False, "analysis": analysis, "question": None}

    q = store.add_question(
        {
            "id": store.slugify(analysis["id"]) or None,
            "question": analysis["question"],
            "criteria": analysis["criteria"],
            "intent": intent,
            "created_at": now_iso(),
        },
        dedupe=True,
    )
    baseline = {
        "resolved": False,
        "confidence": "medium",
        "summary": analysis["summary"],
        "sources": analysis["sources"],
    }

    def seed(entry):
        entry["last_probe"] = now_iso()
        entry["last_result"] = baseline

    store.update_state(q["id"], seed)
    store.append_log({"time": now_iso(), "id": q["id"], "result": baseline, "via": "analyze"})
    print(f"[analyze] added {q['id']}")

    if do_notify:
        _notify_quietly(cfg, "🫖 开始监控", f"{q['question']}\n现状:{analysis['summary']}")
    return {"added": True, "analysis": analysis, "question": question_view(q)}


def _notify_quietly(cfg, title, body, url=None):
    try:
        notify(cfg, title, body, url=url)
    except Exception as e:
        print(f"notify failed: {e}", file=sys.stderr)

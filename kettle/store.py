"""Persistence for questions.toml, state.json and probes.jsonl.

Both the timer (CLI) and the web server write these files, so every
read-modify-write goes through an flock on a shared lock file. Probes run
outside the lock; only the short load/mutate/save step holds it. Writes are
atomic (tmp file + rename), so plain reads never see a half-written file.
"""

import fcntl
import json
import os
import re
import tomllib
from contextlib import contextmanager

from .config import LOCK_FILE, LOG_FILE, QUESTIONS_FILE, STATE_FILE

QUESTIONS_HEADER = """\
# One [[questions]] block per tracked question.
# id: unique slug; question: what you want to know; criteria: what counts as "resolved".
# This file is rewritten by kettle (CLI / web); comments other than this header are not kept.
"""

# Serialization order for known fields; any other string fields follow.
QUESTION_FIELDS = ("id", "question", "criteria", "intent", "created_at")
EDITABLE_FIELDS = ("question", "criteria")

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class StoreError(Exception):
    pass


@contextmanager
def locked():
    with open(LOCK_FILE, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _atomic_write(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# --- questions.toml ---

def _toml_str(s):
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _dump_questions(questions):
    blocks = []
    for q in questions:
        keys = [k for k in QUESTION_FIELDS if q.get(k)]
        keys += [k for k in q if k not in QUESTION_FIELDS and isinstance(q[k], str)]
        lines = ["[[questions]]"] + [f"{k} = {_toml_str(q[k])}" for k in keys]
        blocks.append("\n".join(lines))
    return QUESTIONS_HEADER + "".join("\n" + b + "\n" for b in blocks)


def load_questions():
    if not QUESTIONS_FILE.exists():
        return []
    with open(QUESTIONS_FILE, "rb") as f:
        return tomllib.load(f).get("questions", [])


def _save_questions(questions):
    _atomic_write(QUESTIONS_FILE, _dump_questions(questions))


def get_question(qid):
    for q in load_questions():
        if q["id"] == qid:
            return q
    return None


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40].rstrip("-")


def _next_auto_id(questions):
    nums = [int(q["id"][1:]) for q in questions if q["id"].startswith("q") and q["id"][1:].isdigit()]
    return f"q{max(nums, default=0) + 1}"


def add_question(q, dedupe=False):
    """Append a question. Returns the stored question (id may be adjusted).

    Without an id, one is generated (q1, q2, ...). With dedupe=True a taken id
    gets a numeric suffix instead of raising.
    """
    q = {k: v for k, v in q.items() if v}
    for key in ("question", "criteria"):
        if not q.get(key, "").strip():
            raise StoreError(f"缺少字段: {key}")
    with locked():
        questions = load_questions()
        taken = {x["id"] for x in questions}
        qid = q.get("id") or _next_auto_id(questions)
        if not ID_PATTERN.match(qid):
            raise StoreError(f"id 只能包含小写字母、数字和连字符: {qid}")
        if qid in taken:
            if not dedupe:
                raise StoreError(f"id 已存在: {qid}")
            n = 2
            while f"{qid}-{n}" in taken:
                n += 1
            qid = f"{qid}-{n}"
        q["id"] = qid
        questions.append(q)
        _save_questions(questions)
    return q


def update_question(qid, fields):
    unknown = set(fields) - set(EDITABLE_FIELDS)
    if unknown:
        raise StoreError(f"不可编辑的字段: {', '.join(sorted(unknown))}")
    with locked():
        questions = load_questions()
        for q in questions:
            if q["id"] == qid:
                for key, value in fields.items():
                    if not str(value).strip():
                        raise StoreError(f"字段不能为空: {key}")
                    q[key] = value
                _save_questions(questions)
                return q
    raise StoreError(f"未找到问题 id: {qid}")


def delete_question(qid):
    """Remove a question and its state. Probe history in probes.jsonl is kept."""
    with locked():
        questions = load_questions()
        remaining = [q for q in questions if q["id"] != qid]
        if len(remaining) == len(questions):
            raise StoreError(f"未找到问题 id: {qid}")
        _save_questions(remaining)
        state = load_state()
        if state.pop(qid, None) is not None:
            _save_state(state)


# --- state.json ---

def new_state_entry():
    return {"status": "watching", "consecutive_errors": 0, "resolved_at": None}


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def _save_state(state):
    _atomic_write(STATE_FILE, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def get_state_entry(qid):
    return load_state().get(qid) or new_state_entry()


def update_state(qid, mutate):
    """Atomically apply mutate(entry) to one question's state; returns the entry."""
    with locked():
        state = load_state()
        entry = state.setdefault(qid, new_state_entry())
        mutate(entry)
        _save_state(state)
        return entry


# --- probes.jsonl ---

def append_log(entry):
    with locked(), open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_history(qid, limit=50):
    """Most recent log entries for a question, newest first."""
    if not LOG_FILE.exists():
        return []
    entries = []
    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("id") == qid:
                entries.append(entry)
    return entries[::-1][:limit]

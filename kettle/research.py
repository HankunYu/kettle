"""Prompts and result parsing for probes and monitor setup analysis.

The actual model call goes through the engine configured for each task.
"""

import json
from datetime import datetime

from .engines import get_engine

PROBE_PROMPT = """\
Today is {date}. You are a fact-checking probe. Determine whether the \
following event has happened yet.

Question: {question}

Resolution criteria (what counts as "yes, it happened"):
{criteria}

Search the web for the latest information. Requirements:
- Search from multiple angles. Before concluding "not resolved", you must run \
at least one recency-focused search (include the current month or year plus \
words like "released" / "new") and try broader name/version variants — news \
often uses different version numbers or wording than the question.
- Where an authoritative community wiki/index exists for the topic, fetch the \
page itself to check for newly added entries instead of relying on search \
snippets, which can be stale.
- Distinguish actual releases/announcements from rumors, questions, or \
work-in-progress reports. If evidence is ambiguous, resolved must be false.
- Weigh source freshness: absence of evidence in weeks-old sources is NOT \
high-confidence evidence of absence. If resolved is false and all supporting \
sources are more than two weeks old, confidence must be "medium" or "low".

Output ONLY a single JSON object, no other text, in exactly this schema:
{{"resolved": true|false, "confidence": "high"|"medium"|"low", \
"summary": "<1-3 sentences in Chinese summarizing what you found>", \
"sources": ["<url>", ...]}}
"""

ANALYZE_PROMPT = """\
Today is {date}. You are setting up a long-running monitor. The user wants \
to be notified when something happens:

Intent: {intent}

Turn this into a precise monitoring question. A separate automated probe (an \
LLM with web search and page fetch, run once a day) will later see ONLY the \
question and criteria you write, so they must be self-contained and \
checkable without any other context.

Research first, searching the web and fetching pages directly:
1. Pin down exactly what the user is waiting for. Resolve ambiguity (product \
names, versions, regions, editions) toward the most likely reading, and state \
your reading explicitly in the question.
2. Establish the current state as of today: has it already happened? What \
are the latest relevant developments, with dates? Look specifically for \
false starts — announcements without release, reverted changes, rumors, \
partial or withdrawn support — that a naive probe could mistake for "it \
happened".
3. Find the authoritative sources where it would show up first and can be \
checked directly: official repos, release pages, changelogs, data files, \
status pages, official announcements. Prefer specific fetchable URLs over \
search snippets.

Then write, in Chinese:
- question: one sentence naming exactly what is being waited for.
- criteria: written for the probe, covering all of:
  (a) concretely what counts as resolved, as verifiable conditions;
  (b) known background as of today, with dates: events that already \
happened and must NOT be judged as resolved;
  (c) the authoritative URLs the probe must fetch, what to check on each, \
and how the conditions combine (e.g. "(1) alone, or (2) and (3) together");
  (d) what does not count (third-party blogs, forums, rumors, unmerged or \
in-progress work, etc., as fits the topic).
- summary: 1-3 sentences on the current state.

Also give:
- id: a short lowercase ASCII slug (a-z, 0-9, hyphens, at most 40 chars).
- already_resolved: true only if the event has clearly already happened \
under your own criteria.
- sources: the URLs your conclusions rest on.

Output ONLY a single JSON object, no other text, in exactly this schema:
{{"id": "<slug>", "question": "<...>", "criteria": "<...>", \
"already_resolved": true|false, "summary": "<...>", "sources": ["<url>", ...]}}
"""


def extract_json(text):
    """Return the last top-level JSON object in model output, tolerating prose."""
    decoder = json.JSONDecoder()
    found = None
    i = text.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            found = obj
        i = text.find("{", end)
    if found is None:
        raise ValueError(f"no JSON object in output: {text[:200]!r}")
    return found


def _require(result, keys):
    for key in keys:
        if key not in result:
            raise ValueError(f"result missing '{key}': {result}")
    result.setdefault("sources", [])
    return result


def run_probe(cfg, q):
    """Probe one question. Returns {resolved, confidence, summary, sources}."""
    prompt = PROBE_PROMPT.format(
        date=datetime.now().strftime("%Y-%m-%d"),
        question=q["question"],
        criteria=q["criteria"],
    )
    result = extract_json(get_engine(cfg, "probe").research(prompt))
    return _require(result, ("resolved", "confidence", "summary"))


def run_analyze(cfg, intent):
    """Research an intent and draft a monitor.

    Returns {id, question, criteria, already_resolved, summary, sources}.
    """
    prompt = ANALYZE_PROMPT.format(
        date=datetime.now().strftime("%Y-%m-%d"),
        intent=intent,
    )
    result = extract_json(get_engine(cfg, "analyze").research(prompt))
    return _require(result, ("id", "question", "criteria", "already_resolved", "summary"))

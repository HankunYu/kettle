"""Command-line entry point: python -m kettle <command>."""

import argparse
import sys

from . import service, store
from .config import ConfigError, load_config_or_exit
from .notify import notify


def cmd_run(args):
    cfg = load_config_or_exit()
    if args.all:
        watching = service.watching_questions()
        if not watching:
            print("没有处于 watching 状态的问题")
        for q in watching:
            service.probe_one(cfg, q)
        return
    try:
        outcomes = service.run_due(cfg)
    except ConfigError as e:
        sys.exit(str(e))
    if not outcomes:
        print("没有到期需要探测的问题")


def _question_or_exit(qid):
    q = store.get_question(qid)
    if q is None:
        sys.exit(f"未找到问题 id: {qid}(用 list 查看)")
    return q


def cmd_probe(args):
    cfg = load_config_or_exit()
    service.probe_one(cfg, _question_or_exit(args.id), do_notify=not args.no_notify)


def cmd_list(args):
    views = service.list_views()
    if not views:
        print("questions.toml 里还没有问题")
        return
    for v in views:
        print(f"[{v['status']:8}] {v['id']}  (last probe: {v['last_probe'] or 'never'})")
        print(f"           {v['question']}")
        if v["last_result"]:
            print(f"           ↳ {v['last_result']['summary']}")


def cmd_add(args):
    try:
        q = store.add_question({"id": args.id, "question": args.question, "criteria": args.criteria})
    except store.StoreError as e:
        sys.exit(str(e))
    print(f"已添加 {q['id']}")


def cmd_analyze(args):
    cfg = load_config_or_exit()
    try:
        outcome = service.analyze_and_add(cfg, args.intent, do_notify=not args.no_notify)
    except Exception as e:
        sys.exit(f"分析失败: {e}")
    analysis = outcome["analysis"]
    if outcome["added"]:
        q = outcome["question"]
        print(f"已添加 {q['id']}: {q['question']}")
        print(f"criteria: {q['criteria']}")
    else:
        print(f"已经发生,未加入监控: {analysis['question']}")
    print(f"现状: {analysis['summary']}")


def cmd_remove(args):
    try:
        store.delete_question(args.id)
    except store.StoreError as e:
        sys.exit(str(e))
    print(f"已删除 {args.id}")


def cmd_reset(args):
    try:
        service.reset(args.id)
    except store.StoreError as e:
        sys.exit(str(e))
    print(f"{args.id} 已重置为 watching")


def cmd_serve(args):
    from .server import serve

    serve(host=args.host, port=args.port)


def cmd_test_notify(args):
    cfg = load_config_or_exit()
    notify(cfg, "🫖 kettle", "测试推送:通知链路正常")
    print("测试推送已发送")


def main():
    parser = argparse.ArgumentParser(prog="kettle", description="kettle - daily question prober")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="probe questions due per [schedule] (safe to call often, e.g. from a timer)")
    p.add_argument("--all", action="store_true", help="probe every watching question now, ignoring the schedule")

    p = sub.add_parser("probe", help="probe one question now")
    p.add_argument("id")
    p.add_argument("--no-notify", action="store_true", help="don't push / don't mark resolved")

    sub.add_parser("list", help="list questions and their status")

    p = sub.add_parser("add", help="add a question manually")
    p.add_argument("question")
    p.add_argument("--criteria", required=True, help="what counts as resolved")
    p.add_argument("--id", help="custom id (default: auto q1/q2/...)")

    p = sub.add_parser("analyze", help="let AI research an intent and start monitoring it")
    p.add_argument("intent", help="what you want to be notified about, in plain words")
    p.add_argument("--no-notify", action="store_true", help="don't push when done")

    p = sub.add_parser("remove", help="delete a question and its state")
    p.add_argument("id")

    p = sub.add_parser("reset", help="set a resolved question back to watching")
    p.add_argument("id")

    p = sub.add_parser("serve", help="run the HTTP API and web UI")
    p.add_argument("--host", help="override [server].host")
    p.add_argument("--port", type=int, help="override [server].port")

    sub.add_parser("test-notify", help="send a test Bark push")

    args = parser.parse_args()
    {
        "run": cmd_run,
        "probe": cmd_probe,
        "list": cmd_list,
        "add": cmd_add,
        "analyze": cmd_analyze,
        "remove": cmd_remove,
        "reset": cmd_reset,
        "serve": cmd_serve,
        "test-notify": cmd_test_notify,
    }[args.command](args)

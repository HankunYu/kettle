"""Bark push notifications."""

import json
import urllib.error
import urllib.request


def notify(cfg, title, body, url=None):
    key = cfg.get("bark_key", "")
    if not key or key == "YOUR_BARK_KEY":
        raise RuntimeError("config.toml 里没有配置 bark_key")
    server = cfg.get("bark_server", "https://api.day.app").rstrip("/")
    payload = {
        "device_key": key,
        "title": title,
        "body": body,
        "group": "kettle",
    }
    if url:
        payload["url"] = url
    req = urllib.request.Request(
        f"{server}/push",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            reply = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Bark push failed: HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from None
    if reply.get("code") != 200:
        raise RuntimeError(f"Bark push failed: {reply}")

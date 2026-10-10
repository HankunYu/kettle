"""Claude via the Messages API with the web search and web fetch server tools."""

from .base import Engine, api_key, post_json

API_VERSION = "2023-06-01"
MAX_TOKENS = 16000


class AnthropicEngine(Engine):
    name = "anthropic"

    def research(self, prompt):
        base = self.options.get("base_url", "https://api.anthropic.com").rstrip("/")
        headers = {"x-api-key": api_key("ANTHROPIC_API_KEY"), "anthropic-version": API_VERSION}
        max_uses = self.settings["max_turns"]
        body = {
            "model": self.require_model(),
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [
                {"type": "web_search_20260318", "name": "web_search", "max_uses": max_uses},
                # Bypass the fetch cache: probes exist to notice fresh changes.
                {"type": "web_fetch_20260318", "name": "web_fetch", "max_uses": max_uses, "use_cache": False},
            ],
        }

        # The server runs the tool loop itself; a long turn may come back as
        # pause_turn, which is resumed by sending the assistant turn so far back.
        user = body["messages"][0]
        content = []
        for _ in range(max_uses):
            resp = post_json(f"{base}/v1/messages", headers, body, self.settings["timeout"])
            content += resp.get("content", [])
            stop = resp.get("stop_reason")
            if stop != "pause_turn":
                break
            body["messages"] = [user, {"role": "assistant", "content": content}]
        else:
            raise RuntimeError(f"anthropic: still paused after {max_uses} continuations")

        if stop != "end_turn":
            raise RuntimeError(f"anthropic: unexpected stop_reason {stop!r}")
        return "".join(b["text"] for b in content if b.get("type") == "text")

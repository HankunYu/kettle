"""Gemini via generateContent with Google Search grounding and URL context."""

from urllib.parse import quote

from .base import Engine, api_key, post_json


class GeminiEngine(Engine):
    name = "gemini"

    def research(self, prompt):
        base = self.options.get("base_url", "https://generativelanguage.googleapis.com").rstrip("/")
        headers = {"x-goog-api-key": api_key("GEMINI_API_KEY")}
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}, {"url_context": {}}],
        }
        url = f"{base}/v1beta/models/{quote(self.require_model(), safe='')}:generateContent"

        resp = post_json(url, headers, body, self.settings["timeout"])
        block = resp.get("promptFeedback", {}).get("blockReason")
        if block:
            raise RuntimeError(f"gemini: prompt blocked ({block})")
        candidates = resp.get("candidates") or []
        if not candidates:
            raise RuntimeError("gemini: no candidates in response")
        cand = candidates[0]
        if cand.get("finishReason") not in (None, "STOP"):
            raise RuntimeError(f"gemini: finishReason {cand.get('finishReason')}")
        return "".join(
            part.get("text", "")
            for part in cand.get("content", {}).get("parts", [])
            if not part.get("thought")
        )

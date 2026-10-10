"""OpenAI via the Responses API with the web_search tool."""

from .base import Engine, api_key, post_json


class OpenAIEngine(Engine):
    name = "openai"

    def research(self, prompt):
        base = self.options.get("base_url", "https://api.openai.com").rstrip("/")
        headers = {"Authorization": f"Bearer {api_key('OPENAI_API_KEY')}"}
        body = {
            "model": self.require_model(),
            "input": prompt,
            "tools": [{"type": "web_search"}],
        }
        if self.options.get("reasoning_effort"):
            body["reasoning"] = {"effort": self.options["reasoning_effort"]}

        resp = post_json(f"{base}/v1/responses", headers, body, self.settings["timeout"])
        if resp.get("status") != "completed":
            raise RuntimeError(f"openai: status {resp.get('status')!r}: {resp.get('incomplete_details') or resp.get('error')}")
        return "".join(
            part.get("text", "")
            for item in resp.get("output", [])
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )

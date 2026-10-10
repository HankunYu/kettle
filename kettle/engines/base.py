"""Engine interface and helpers shared by the engine implementations."""

import json
import os
import urllib.error
import urllib.request

from ..config import ConfigError, load_dotenv


class Engine:
    """A research backend: runs a prompt with web search/fetch, returns the final text.

    Prompting and result parsing live in research.py; engines only deal with
    transport and with collecting the model's final answer text.
    """

    name = ""

    def __init__(self, settings, options):
        # settings: resolved [probe]/[analyze] values (engine, model, max_turns, timeout)
        # options: this engine's [engines.<name>] table
        self.settings = settings
        self.options = options

    @property
    def model(self):
        return self.settings.get("model")

    def require_model(self):
        if not self.model:
            raise ConfigError(f"engine '{self.name}' 需要在 config.toml 里设置 model")
        return self.model

    def research(self, prompt):
        raise NotImplementedError


def api_key(env_name):
    """Read a key from .env first, then the process environment."""
    key = load_dotenv().get(env_name) or os.environ.get(env_name)
    if not key:
        raise ConfigError(f"缺少 {env_name}:写入 .env 或环境变量")
    return key


def post_json(url, headers, body, timeout):
    """POST a JSON body and return the decoded JSON response."""
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(detail).get("error", detail)
            detail = err.get("message", err) if isinstance(err, dict) else err
        except (json.JSONDecodeError, AttributeError):
            pass
        raise RuntimeError(f"HTTP {e.code}: {str(detail)[:500]}") from None

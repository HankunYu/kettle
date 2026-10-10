"""Research engines, selected per task ([probe] / [analyze]) in config.toml."""

from ..config import ConfigError
from .anthropic import AnthropicEngine
from .base import Engine
from .claude_code import ClaudeCodeEngine
from .gemini import GeminiEngine
from .openai import OpenAIEngine

ENGINES = {e.name: e for e in (ClaudeCodeEngine, AnthropicEngine, OpenAIEngine, GeminiEngine)}

TASK_DEFAULTS = {
    "probe": {"engine": "claude-code", "max_turns": 25, "timeout": 900},
    "analyze": {"max_turns": 40},
}

__all__ = ["ENGINES", "Engine", "get_engine", "task_settings"]


def task_settings(cfg, task):
    """Resolve a task's settings. [analyze] inherits unset keys from [probe]."""
    probe = {**TASK_DEFAULTS["probe"], **cfg.get("probe", {})}
    if task == "probe":
        return probe
    return {**probe, **TASK_DEFAULTS[task], **cfg.get(task, {})}


def get_engine(cfg, task):
    settings = task_settings(cfg, task)
    cls = ENGINES.get(settings["engine"])
    if cls is None:
        raise ConfigError(f"未知 engine '{settings['engine']}',可选: {', '.join(ENGINES)}")
    return cls(settings, cfg.get("engines", {}).get(cls.name, {}))

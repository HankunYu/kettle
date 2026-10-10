"""Headless Claude Code CLI (`claude -p`) with WebSearch/WebFetch."""

import json
import os
import subprocess

from ..config import ROOT, load_dotenv
from .base import Engine


class ClaudeCodeEngine(Engine):
    name = "claude-code"

    def research(self, prompt):
        cmd = [
            self.options.get("bin", "claude"),
            "-p", prompt,
            "--output-format", "json",
            "--allowedTools", "WebSearch", "WebFetch",
            "--max-turns", str(self.settings["max_turns"]),
        ]
        if self.model:
            cmd += ["--model", self.model]

        # .env (e.g. ANTHROPIC_API_KEY) goes to the child process only; without
        # it claude falls back to the subscription login.
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.settings["timeout"],
            cwd=ROOT,
            env={**os.environ, **load_dotenv()},
        )

        # stdout carries the real result/error as JSON even on a non-zero exit;
        # stderr may only hold unrelated warnings, so it is the fallback.
        try:
            outer = json.loads(proc.stdout)
        except json.JSONDecodeError:
            outer = None
        if outer is None:
            raise RuntimeError(f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[:500]}")
        if outer.get("is_error") or proc.returncode != 0:
            status = outer.get("api_error_status")
            detail = f" (HTTP {status})" if status else ""
            raise RuntimeError(f"claude error{detail}: {str(outer.get('result', ''))[:500]}")
        return outer.get("result", "")

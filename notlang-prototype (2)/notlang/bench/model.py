"""A minimal Anthropic Messages API client (standard library only)."""
import json
import os
import urllib.error
import urllib.request


class AnthropicModel:
    def __init__(self, model, api_key=None):
        self.model = model
        self.key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.key:
            raise SystemExit("Set ANTHROPIC_API_KEY, or run with --mock for an offline dry run.")

    def ask(self, task, system, messages):
        body = json.dumps({"model": self.model, "max_tokens": 4000,
                           "system": system, "messages": messages}).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"content-type": "application/json", "x-api-key": self.key,
                     "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"API error {e.code}: {e.read().decode()[:500]}")
        return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")

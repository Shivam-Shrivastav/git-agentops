from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(slots=True)
class Settings:
    github_token: str
    openrouter_api_key: str
    github_api_base_url: str = "https://api.github.com"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openrouter/free"
    openrouter_http_referer: str = "http://localhost"
    openrouter_app_name: str = "github-agent-local"
    agent_max_steps: int = 6

    @classmethod
    def from_env(cls) -> "Settings":
        github_token = os.getenv("GITHUB_TOKEN", "").strip()
        if not github_token:
            raise ValueError("Missing GITHUB_TOKEN. Add it to your environment or .env file.")
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not openrouter_api_key:
            raise ValueError("Missing OPENROUTER_API_KEY. Add it to your environment or .env file.")

        return cls(
            github_token=github_token,
            openrouter_api_key=openrouter_api_key,
            github_api_base_url=os.getenv("GITHUB_API_BASE_URL", "https://api.github.com").rstrip("/"),
            openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
            openrouter_model=os.getenv("OPENROUTER_MODEL", "openrouter/free").strip(),
            openrouter_http_referer=os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost").strip(),
            openrouter_app_name=os.getenv("OPENROUTER_APP_NAME", "github-agent-local").strip(),
            agent_max_steps=int(os.getenv("AGENT_MAX_STEPS", "6")),
        )

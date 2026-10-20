"""Load and validate config.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    window_weeks: int
    max_themes: int
    top_themes: int
    max_words: int
    min_reviews: int
    min_words: int
    play_app_id: str
    play_lang: str
    play_country: str
    recipient: str
    doc_mode: str
    doc_title: str
    mail_mode: str = "send_to_self"
    low_reviews_action: str = "publish"
    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    cluster_k: int = 8
    llm_provider: str = "groq"
    label_model: str = "openai/gpt-oss-120b"
    label_sample: int = 15
    writer_model: str = "openai/gpt-oss-120b"
    mcp: Dict[str, Optional[str]] = field(default_factory=dict)
    paths: Dict[str, str] = field(default_factory=dict)

    def path(self, key: str) -> Path:
        return ROOT / self.paths[key]


def _validate(cfg: Config) -> None:
    if not 8 <= cfg.window_weeks <= 12:
        raise ConfigError("window_weeks must be between 8 and 12")
    if not 1 <= cfg.max_themes <= 5:
        raise ConfigError("max_themes must be between 1 and 5")
    if not 1 <= cfg.top_themes <= cfg.max_themes:
        raise ConfigError("top_themes must be between 1 and max_themes")
    if cfg.cluster_k < cfg.max_themes:
        raise ConfigError("cluster_k must be at least max_themes")
    if cfg.llm_provider not in ("groq", "anthropic"):
        raise ConfigError("llm_provider must be 'groq' or 'anthropic'")
    if cfg.label_sample < 1:
        raise ConfigError("label_sample must be positive")
    if cfg.min_words < 0:
        raise ConfigError("min_words must be zero or more")
    if cfg.max_words < 1:
        raise ConfigError("max_words must be positive")
    if cfg.low_reviews_action not in ("publish", "skip"):
        raise ConfigError("low_reviews_action must be 'publish' or 'skip'")
    if cfg.mail_mode not in ("send_to_self", "draft"):
        raise ConfigError("mail_mode must be 'send_to_self' or 'draft'")
    if cfg.doc_mode not in ("single", "weekly"):
        raise ConfigError("doc_mode must be 'single' or 'weekly'")
    if "@" not in cfg.recipient:
        raise ConfigError("recipient must be an email address")


def load_config(path: Optional[Path] = None) -> Config:
    path = Path(path or DEFAULT_CONFIG_PATH)
    try:
        raw: Dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    except FileNotFoundError:
        raise ConfigError("config file not found: %s" % path)

    raw["recipient"] = os.environ.get("PULSE_RECIPIENT", raw.get("recipient", ""))
    try:
        cfg = Config(**raw)
    except TypeError as exc:
        raise ConfigError("invalid config: %s" % exc)
    _validate(cfg)
    return cfg

"""Shared pytest fixtures for trading-incident-investigation-agent tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from trading_incident_agent import AgentConfig, TradingIncidentAgent, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"
CONFIG_PATH = PROJECT_ROOT / "config" / "default.json"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def default_config() -> AgentConfig:
    return load_config(CONFIG_PATH)


@pytest.fixture
def agent(default_config: AgentConfig) -> TradingIncidentAgent:
    return TradingIncidentAgent(config=default_config)

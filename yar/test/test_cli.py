#!/usr/bin/env python3
"""Test that CLI commands work via uv run python -m yar.yar"""

import subprocess
from pathlib import Path


def test_yar_command_available():
    """Test that yar module is available via uv run"""
    result = subprocess.run(
        ["uv", "run", "python", "-m", "yar.yar", "--help"],
        capture_output=True,
        text=True,
        cwd="/yar"
    )
    assert result.returncode == 0
    assert "YAR - Competitive Socket Writing Game" in result.stdout
    assert "Commands:" in result.stdout


def test_yar_server_command():
    """Test that yar server command works"""
    result = subprocess.run(
        ["uv", "run", "python", "-m", "yar.yar", "server", "--help"],
        capture_output=True,
        text=True,
        cwd="/yar"
    )
    assert result.returncode == 0
    assert "Run the game server" in result.stdout
    assert "--debug" in result.stdout
    assert "--game" in result.stdout


def test_yar_client_command():
    """Test that yar client command works"""
    result = subprocess.run(
        ["uv", "run", "python", "-m", "yar.yar", "client", "--help"],
        capture_output=True,
        text=True,
        cwd="/yar"
    )
    assert result.returncode == 0
    assert "Run a test client" in result.stdout
    assert "--player" in result.stdout
    assert "--bandwidth" in result.stdout


def test_yar_ui_command():
    """Test that yar ui command works"""
    result = subprocess.run(
        ["uv", "run", "python", "-m", "yar.yar", "ui", "--help"],
        capture_output=True,
        text=True,
        cwd="/yar"
    )
    assert result.returncode == 0
    assert "Run the TUI visualization" in result.stdout
    assert "--game" in result.stdout
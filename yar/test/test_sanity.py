#!/usr/bin/env python3

import asyncio
import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from tortoise import Tortoise

from yar.models import Config, Game, GamePaths, Player, Score, Socket
from yar.server import YarServer


def test_imports():
    """Test that all modules can be imported"""
    from yar import YarServer, YarTUI, run_client
    from yar.models import BandwidthManager, EventSource
    from yar.yar import cli
    
    # Check that CLI commands exist
    assert hasattr(cli, 'commands')
    assert 'server' in cli.commands
    assert 'client' in cli.commands
    assert 'ui' in cli.commands


def test_game_paths():
    """Test that GamePaths generates correct paths"""
    paths = GamePaths(1)
    assert paths.game == "/yar/games/001"
    assert paths.journal == "/yar/games/001/journal"
    assert paths.sockets == "/yar/games/sockets"
    assert paths.scores == "/yar/games/001/territories"
    
    paths = GamePaths(42)
    assert paths.game == "/yar/games/042"
    paths = GamePaths(999)
    assert paths.game == "/yar/games/999"


@pytest.mark.asyncio
async def test_database_models():
    """Test that database models work correctly"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        
        await Tortoise.init(
            db_url=f"sqlite://{db_path}",
            modules={"models": ["yar.models"]}
        )
        await Tortoise.generate_schemas()
        
        # Create config with defaults
        config = await Config.create()
        assert config.socket_threshold == 100
        assert config.player_bandwidth == 10
        assert config.bandwidth_penalty == 1
        
        # Create game
        game = await Game.create()
        assert game.id == 1
        assert game.foo == 1000
        
        # Create players
        p1 = await Player.create(
            game=game,
            player_id=1,
            command_line="test",
            prompt_path="/tmp/test",
            bandwidth=10,
            compute=5
        )
        assert p1.player_id == 1
        assert p1.score == 0
        
        p2 = await Player.create(
            game=game,
            player_id=2,
            command_line="test",
            prompt_path="/tmp/test",
            bandwidth=10,
            compute=5
        )
        assert p2.player_id == 2
        assert p2.score == 0
        
        # Create score
        score = await Score.create(
            game=game,
            file_path="/tmp/score",
            score=42
        )
        assert score.score == 42
        
        # Create socket
        socket = await Socket.create(
            game=game,
            socket_path="/tmp/socket",
            p1_progress=10,
            p2_progress=20,
            threshold=100
        )
        assert socket.p1_progress == 10
        assert socket.p2_progress == 20
        assert socket.threshold == 100
        
        await Tortoise.close_connections()


def test_cli_help():
    """Test that CLI help works"""
    result = subprocess.run(
        ["python", "-m", "yar.yar", "--help"],
        capture_output=True,
        text=True,
        cwd="/yar"
    )
    assert result.returncode == 0
    assert "YAR - Competitive Socket Writing Game" in result.stdout
    assert "server" in result.stdout
    assert "client" in result.stdout
    assert "ui" in result.stdout


@pytest.mark.asyncio
async def test_server_startup_and_shutdown():
    """Test that server can start and create database"""
    import shutil
    from yar.server import YarServer
    
    # Clean up any existing files
    games_dir = Path("/yar/games")
    if games_dir.exists():
        shutil.rmtree(games_dir)
    
    # Initialize server and database
    server = YarServer()
    await server.init_db()
    
    # Check that database was created
    db_path = games_dir / "yar.sqlite3"
    assert db_path.exists(), "Database not created"
    
    # Check that game directories were created
    assert games_dir.exists()
    
    # Create a game
    game_id, game_dir = await server.setup_game()
    assert game_id > 0
    assert Path(game_dir).exists()
    
    # Verify game was created in database
    game = await Game.get(id=game_id)
    assert game is not None
    
    # Clean up
    await Tortoise.close_connections()

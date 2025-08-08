#!/usr/bin/env python3

import asyncio
import os
import select
import shutil
import socket as psocket
import time
from typing import Dict

import psutil
from tortoise import Tortoise

from .models import (
    BandwidthManager,
    Config,
    Event,
    EventSource,
    Game,
    GamePaths,
    Paths,
    Player,
    Socket,
)


class YarServer:
    def __init__(self):
        self.player_pids = []
        self.paths = Paths()

    async def init_db(self):
        os.makedirs(self.paths.games, exist_ok=True)

        await Tortoise.init(
            db_url="sqlite:///yar/games/yar.sqlite3", modules={"models": ["yar.models"]}
        )
        await Tortoise.generate_schemas()

        if not await Config.exists():
            await Config.create()

    def find_players(self):
        opencode_pids = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if proc.info["name"] == "opencode":
                    opencode_pids.append(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if len(opencode_pids) >= 2:
            self.player_pids = opencode_pids[:2]

    async def setup_game(self, num_sockets: int = 1):
        config = await Config.first()
        game = await Game().create()
        print(f"Created game with ID: {game.id}", flush=True)

        game_paths = GamePaths(game.id)

        os.makedirs(game_paths.game, exist_ok=True)
        os.makedirs(game_paths.journal, exist_ok=True)
        os.makedirs(game_paths.sockets, exist_ok=True)
        os.makedirs(game_paths.scores, exist_ok=True)

        for i in range(1, num_sockets + 1):
            socket_path = os.path.join(game_paths.sockets, f"yar-{i:03d}")
            await Socket.create(
                game=game,
                socket_path=socket_path,
                p1_progress=0,
                p2_progress=0,
                threshold=config.socket_threshold,
            )

        player_prompt_path = os.path.join(self.paths.prompts, "player.md")

        p1_prompt = os.path.join(game_paths.journal, "p1.md")
        p2_prompt = os.path.join(game_paths.journal, "p2.md")

        if os.path.exists(player_prompt_path):
            shutil.copy(player_prompt_path, p1_prompt)
            shutil.copy(player_prompt_path, p2_prompt)

        p1_pid = self.player_pids[0] if len(self.player_pids) >= 1 else None
        p2_pid = self.player_pids[1] if len(self.player_pids) >= 2 else None

        await Player.create(
            game=game,
            player_id=1,
            pid=p1_pid,
            command_line="opencode",
            prompt_path=p1_prompt,
            bandwidth=config.player_bandwidth,
            compute=config.player_compute,
        )

        await Player.create(
            game=game,
            player_id=2,
            pid=p2_pid,
            command_line="opencode",
            prompt_path=p2_prompt,
            bandwidth=config.player_bandwidth,
            compute=config.player_compute,
        )

        return game.id, game_paths.game

    def is_player_byte(self, player, byte_val: int) -> bool:
        return byte_val == player.player_id

    async def run_socket_server(self, game_id: int, game_dir: str, debug: bool = False):
        game = await Game.get(id=game_id)
        config = await Config.first()
        sockets = await Socket.filter(game=game_id).all()
        players = await Player.filter(game=game_id).all()

        game_paths = GamePaths(game_id)
        for idx in range(1, len(sockets) + 1):
            socket_path = os.path.join(game_paths.sockets, f"yar-{idx:03d}")
            if os.path.exists(socket_path):
                os.unlink(socket_path)
                if debug:
                    print(f"Removed existing socket: {socket_path}", flush=True)

        player_by_id = {p.player_id: p for p in players}
        bandwidth_managers: Dict[int, BandwidthManager] = {}
        for p in players:
            bandwidth_managers[p.player_id] = BandwidthManager(
                bytes_available=10240,
                bytes_max=10240,
                refill_rate=p.bandwidth * 1024,
            )

        socket_infos = {}
        socket_files = []
        for idx, socket in enumerate(sockets):
            socket_file = psocket.socket(psocket.AF_UNIX, psocket.SOCK_DGRAM)
            socket_path = os.path.join(game_paths.sockets, f"yar-{idx+1:03d}")
            socket_file.bind(socket_path)
            socket_files.append(socket_file)
            socket_infos[socket_file.fileno()] = (socket_file, socket)
            if debug:
                print(f"Created socket: {socket_path}", flush=True)

        if debug:
            print("Game loop running at 10Hz (Ctrl+C to stop)", flush=True)

        last_time = time.time()
        bandwidth_usage = {p.player_id: 0.0 for p in players}
        bandwidth_window_start = time.time()

        try:
            tick_interval = 0.1
            while True:
                current_time = time.time()
                dt = current_time - last_time
                last_time = current_time

                # Reset bandwidth usage tracking every second
                if current_time - bandwidth_window_start >= 1.0:
                    for player in players:
                        player.current_bandwidth = bandwidth_usage[player.player_id]
                        await player.save(update_fields=["current_bandwidth"])
                    bandwidth_usage = {p.player_id: 0.0 for p in players}
                    bandwidth_window_start = current_time

                for pid, manager in bandwidth_managers.items():
                    manager.bytes_available = min(
                        manager.bytes_max,
                        manager.bytes_available + manager.refill_rate * dt,
                    )

                readable, _, _ = select.select(socket_files, [], [], tick_interval)
                for socket_file in readable:
                    data, _ = socket_file.recvfrom(65536)
                    _, socket = socket_infos[socket_file.fileno()]

                    if debug:
                        print(f"Received {len(data)} bytes on socket", flush=True)
                    
                    for player in players:
                        count = sum(1 for b in data if self.is_player_byte(player, b))
                        if count == 0:
                            continue

                        manager = bandwidth_managers[player.player_id]
                        allowed = int(min(manager.bytes_available, count))
                        manager.bytes_available -= allowed
                        excess = count - allowed
                        
                        # Track bandwidth usage for this second
                        bandwidth_usage[player.player_id] += allowed

                        if player.player_id == 1:
                            socket.p1_progress += allowed
                        else:
                            socket.p2_progress += allowed

                        if excess > 0:
                            penalty = -config.bandwidth_penalty * excess
                            player.score += penalty
                            await player.save(update_fields=["score"])
                            await Event.create(
                                game=game,
                                player=player,
                                source=EventSource.BANDWIDTH_EXCEEDED,
                                delta=penalty,
                                new_score=player.score,
                            )
                            if debug:
                                print(
                                    f"Player {player.player_id} exceeded bandwidth: {excess} excess bytes, penalty: {penalty}",
                                    flush=True
                                )

                        while socket.p1_progress >= socket.threshold and player.player_id == 1:
                            socket.p1_progress -= socket.threshold
                            points = 1
                            player.score += points
                            await player.save(update_fields=["score"])
                            await Event.create(
                                game=game,
                                player=player,
                                source=EventSource.TICK,
                                delta=points,
                                new_score=player.score,
                            )
                            if debug:
                                print(f"Player 1 scored {points} point! Total: {player.score}", flush=True)
                        
                        while socket.p2_progress >= socket.threshold and player.player_id == 2:
                            socket.p2_progress -= socket.threshold
                            points = 1
                            player.score += points
                            await player.save(update_fields=["score"])
                            await Event.create(
                                game=game,
                                player=player,
                                source=EventSource.TICK,
                                delta=points,
                                new_score=player.score,
                            )
                            if debug:
                                print(f"Player 2 scored {points} point! Total: {player.score}", flush=True)

                    await socket.save(update_fields=["p1_progress", "p2_progress"])

        except KeyboardInterrupt:
            print("\nShutting down socket server...", flush=True)
        finally:
            for s in socket_files:
                s.close()
            await Tortoise.close_connections()
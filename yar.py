#!/usr/bin/env python3

import os
import shutil
import socket
import select
import psutil
import asyncio
import click
import random
import string
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict
import time

from tortoise.models import Model
from tortoise import fields, Tortoise


@dataclass
class BandwidthManager:
    bytes_available: float
    bytes_max: int = 10240  # 10KB burst capacity
    refill_rate: int = 0  # bytes per second, set from player.bandwidth


class Paths:
    def __init__(self):
        self.root = "/yar"
        self.asset = os.path.join(self.root, "asset")
        self.prompts = os.path.join(self.asset, "prompts")
        self.games = os.path.join(self.root, "games")
        self.db_file = os.path.join(self.games, "yar.sqlite3")


class GamePaths:
    def __init__(self, game_id: int):
        self.game = os.path.join("/yar/games", f"{game_id:03d}")
        self.journal = os.path.join(self.game, "journal")
        self.sockets = os.path.join(self.game, "sockets")
        self.targets = os.path.join(self.game, "targets")


class EventSource(str, Enum):
    TICK = "Tick"
    BANDWIDTH_EXCEEDED = "BandwidthExceeded"


class Config(Model):
    id = fields.IntField(primary_key=True)
    factory_threshold = fields.IntField(default=100)
    player_bandwidth = fields.IntField(default=10)
    player_compute = fields.IntField(default=5)
    bandwidth_penalty = fields.IntField(default=1)


class Game(Model):
    id = fields.IntField(primary_key=True)
    foo = fields.IntField(default=1000)
    created_at = fields.DatetimeField(auto_now_add=True)
    targets: fields.ReverseRelation["Target"]
    factories: fields.ReverseRelation["Factory"]
    players: fields.ReverseRelation["Player"]


class Target(Model):
    id = fields.IntField(primary_key=True)
    game = fields.ForeignKeyField("models.Game", related_name="targets")
    file_path = fields.CharField(max_length=255)
    score = fields.IntField(default=0)


class Factory(Model):
    id = fields.IntField(primary_key=True)
    game = fields.ForeignKeyField("models.Game", related_name="factories")
    socket_path = fields.CharField(max_length=255)
    p1_progress = fields.IntField(default=0)
    p2_progress = fields.IntField(default=0)
    threshold = fields.IntField()


class Player(Model):
    id = fields.IntField(primary_key=True)
    game = fields.ForeignKeyField("models.Game", related_name="players")
    player_id = fields.IntField()
    pid = fields.IntField(null=True)
    command_line = fields.CharField(max_length=255)
    prompt_path = fields.CharField(max_length=255)
    bandwidth = fields.IntField()
    compute = fields.IntField()
    score = fields.IntField(default=0)


class Event(Model):
    id = fields.IntField(primary_key=True)
    game = fields.ForeignKeyField("models.Game", related_name="events")
    player = fields.ForeignKeyField("models.Player", related_name="events", null=True)
    source = fields.CharEnumField(EventSource)
    delta = fields.IntField()
    new_score = fields.IntField()
    created_at = fields.DatetimeField(auto_now_add=True)


class Yar:
    def __init__(self):
        self.player_pids = []
        self.paths = Paths()

    async def init_db(self):
        os.makedirs(self.paths.games, exist_ok=True)

        await Tortoise.init(
            db_url="sqlite:///yar/games/yar.sqlite3", modules={"models": ["__main__"]}
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

    def generate_hash(self, length=8):
        return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))

    async def setup_game(self):
        config = await Config.first()
        game = await Game().create()
        print(f"Created game with ID: {game.id}")

        game_paths = GamePaths(game.id)

        os.makedirs(game_paths.game, exist_ok=True)
        os.makedirs(game_paths.journal, exist_ok=True)
        os.makedirs(game_paths.sockets, exist_ok=True)
        os.makedirs(game_paths.targets, exist_ok=True)

        for i in range(4):
            target_hash = self.generate_hash()
            target_path = os.path.join(game_paths.targets, f"target-{target_hash}")
            with open(target_path, "w") as f:
                f.write("0")

            target = Target(game_id=game.id, file_path=target_path, score=0)
            await target.save()

        for i in range(4):
            factory_hash = self.generate_hash()
            socket_path = os.path.join(
                game_paths.sockets, f"factory-{factory_hash}.sock"
            )

            try:
                os.unlink(socket_path)
            except OSError:
                pass

            await Factory.create(
                game_id=game.id,
                socket_path=socket_path,
                p1_progress=0,
                p2_progress=0,
                threshold=config.factory_threshold,
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

    def get_player_offset(self, player_id: int):
        return 1 if player_id == 1 else -1

    def is_player_byte(self, player, byte_val: int) -> bool:
        # Player sends their ID as a byte (1 or 2)
        return byte_val == player.player_id

    async def run_socket_server(self, game_id: int, game_dir: str, debug: bool = False):
        game = await Game.get(id=game_id)
        config = await Config.first()
        factories = await Factory.filter(game=game_id).all()
        targets = await Target.filter(game=game_id).all()
        players = await Player.filter(game=game_id).all()
        
        # Create player lookup and bandwidth managers
        player_by_id = {p.player_id: p for p in players}
        bandwidth_managers: Dict[int, BandwidthManager] = {}
        for p in players:
            bandwidth_managers[p.player_id] = BandwidthManager(
                bytes_available=10240,  # Start with full burst capacity
                bytes_max=10240,  # 10KB burst capacity
                refill_rate=p.bandwidth * 1024,  # KB/s to bytes/s
            )
        
        factory_by_sock = {}
        target_cycle = list(targets)
        sockets = []
        for idx, factory in enumerate(factories):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.bind(factory.socket_path)
            sockets.append(sock)
            factory_by_sock[sock.fileno()] = (
                sock,
                factory,
                target_cycle[idx % len(target_cycle)] if target_cycle else None,
            )
            if debug:
                print(f"Created socket: {factory.socket_path}")

        if debug:
            print("Game loop running at 10Hz (Ctrl+C to stop)")

        last_time = time.time()
        last_tick_time = time.time()
        
        try:
            tick_interval = 0.1
            while True:
                current_time = time.time()
                dt = current_time - last_time
                last_time = current_time
                
                # Refill bandwidth managers
                for pid, bw_mgr in bandwidth_managers.items():
                    bw_mgr.bytes_available = min(
                        bw_mgr.bytes_max,
                        bw_mgr.bytes_available + bw_mgr.refill_rate * dt
                    )
                
                # Check for 1-second tick
                if current_time - last_tick_time >= 1.0:
                    # Calculate total target scores
                    total_score = sum(t.score for t in targets)
                    
                    # Update player scores based on target totals
                    for player in players:
                        delta = total_score * self.get_player_offset(player.player_id)
                        
                        if delta != 0:
                            player.score += delta
                            await player.save(update_fields=["score"])
                            await Event.create(
                                game=game,
                                player=player,
                                source=EventSource.TICK,
                                delta=delta,
                                new_score=player.score
                            )
                    
                    last_tick_time = current_time
                
                readable, _, _ = select.select(sockets, [], [], tick_interval)
                for sock in readable:
                    data, _ = sock.recvfrom(65536)
                    _, factory, target = factory_by_sock[sock.fileno()]
                    
                    if debug:
                        print(f"Received {len(data)} bytes on {factory.socket_path}")
                    
                    # Count bytes per player
                    for player in players:
                        count = sum(1 for b in data if self.is_player_byte(player, b))
                        if count == 0:
                            continue
                        
                        bw_mgr = bandwidth_managers[player.player_id]
                        allowed = int(min(bw_mgr.bytes_available, count))
                        bw_mgr.bytes_available -= allowed
                        excess = count - allowed
                        
                        # Add allowed bytes to progress
                        if player.player_id == 1:
                            factory.p1_progress += allowed
                        else:
                            factory.p2_progress += allowed
                        
                        # Apply penalty for excess
                        if excess > 0:
                            penalty = -config.bandwidth_penalty * excess
                            player.score += penalty
                            await player.save(update_fields=["score"])
                            await Event.create(
                                game=game,
                                player=player,
                                source=EventSource.BANDWIDTH_EXCEEDED,
                                delta=penalty,
                                new_score=player.score
                            )
                            if debug:
                                print(f"Player {player.player_id} exceeded bandwidth: {excess} excess bytes, penalty: {penalty}")
                    
                    # Process factory thresholds
                    assert target is not None
                    while factory.p1_progress >= factory.threshold:
                        factory.p1_progress -= factory.threshold
                        target.score += self.get_player_offset(1)
                    while factory.p2_progress >= factory.threshold:
                        factory.p2_progress -= factory.threshold
                        target.score += self.get_player_offset(2)
                    
                    # Write target score to file
                    with open(target.file_path, "w") as f:
                        f.write(str(target.score))
                
                await asyncio.gather(
                    *[
                        factory.save(update_fields=["p1_progress", "p2_progress"])
                        for _, factory, _ in factory_by_sock.values()
                    ]
                )
                await asyncio.gather(
                    *[
                        t.save(update_fields=["score"])
                        for t in target_cycle
                        if t is not None
                    ]
                )
        except KeyboardInterrupt:
            print("\nShutting down socket server...")
        finally:
            for s in sockets:
                s.close()
            await Tortoise.close_connections()


@click.command()
@click.option("--game", type=int, help="Resume existing game by ID")
@click.option("--debug", is_flag=True, default=False, help="Enable debug logs")
def main(game, debug):
    async def run():
        debug_flag = debug
        yar = Yar()
        await yar.init_db()
        yar.find_players()

        if len(yar.player_pids) >= 2:
            if debug:
                print(f"P1 PID: {yar.player_pids[0]}")
                print(f"P2 PID: {yar.player_pids[1]}")
        else:
            print(f"Found {len(yar.player_pids)} opencode processes (need 2)")

        if game:
            game_record = await Game.get_or_none(id=game)
            if game_record:
                if debug:
                    print(f"Resuming game {game:03d}...")
                game_paths = GamePaths(game)
                game_dir = game_paths.game
                game_id = game
            else:
                print(f"Game {game:03d} not found!")
                return
        else:
            if debug:
                print("Setting up a new game...")
            game_id, game_dir = await yar.setup_game()
            if debug:
                print(f"Game {game_id:03d} created!")

        await yar.run_socket_server(game_id, game_dir, debug_flag)

    asyncio.run(run())


if __name__ == "__main__":
    main()

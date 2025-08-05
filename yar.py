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
from typing import List, Optional

from tortoise.models import Model
from tortoise import fields, Tortoise

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

class Config(Model):
  id = fields.IntField(primary_key=True)
  factory_threshold = fields.IntField(default=100)
  player_bandwidth = fields.IntField(default=10)
  player_compute = fields.IntField(default=5)

class Game(Model):
  id = fields.IntField(primary_key=True)
  foo = fields.IntField(default=1000)
  created_at = fields.DatetimeField(auto_now_add=True)
  targets: fields.ReverseRelation['Target']
  factories: fields.ReverseRelation['Factory']
  players: fields.ReverseRelation['Player']

class Target(Model):
  id = fields.IntField(primary_key=True)
  game = fields.ForeignKeyField('models.Game', related_name='targets')
  file_path = fields.CharField(max_length=255)
  score = fields.IntField(default=0)

class Factory(Model):
  id = fields.IntField(primary_key=True)
  game = fields.ForeignKeyField('models.Game', related_name='factories')
  socket_path = fields.CharField(max_length=255)
  p1_progress = fields.IntField(default=0)
  p2_progress = fields.IntField(default=0)
  threshold = fields.IntField()

class Player(Model):
  id = fields.IntField(primary_key=True)
  game = fields.ForeignKeyField('models.Game', related_name='players')
  player_id = fields.IntField()
  pid = fields.IntField(null=True)
  command_line = fields.CharField(max_length=255)
  prompt_path = fields.CharField(max_length=255)
  bandwidth = fields.IntField()
  compute = fields.IntField()

class Yar:
  def __init__(self):
    self.player_pids = []
    self.paths = Paths()
    
  async def init_db(self):
    os.makedirs(self.paths.games, exist_ok=True)
    
    await Tortoise.init(
      db_url = 'sqlite:///yar/games/yar.sqlite3',
      modules = {
        'models': [ '__main__' ]
      }
    )
    await Tortoise.generate_schemas()
    
    if not await Config.exists():
      await Config.create()
  
  def find_players(self):
    opencode_pids = []
    for proc in psutil.process_iter(['pid', 'name']):
      try:
        if proc.info['name'] == 'opencode':
          opencode_pids.append(proc.info['pid'])
      except (psutil.NoSuchProcess, psutil.AccessDenied):
        continue
    
    if len(opencode_pids) >= 2:
      self.player_pids = opencode_pids[:2]
  
  def generate_hash(self, length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
  
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
      with open(target_path, 'w') as f:
        f.write('0')
      
      target = Target(game_id=game.id, file_path=target_path, score=0)
      await target.save()
    
    for i in range(4):
      factory_hash = self.generate_hash()
      socket_path = os.path.join(game_paths.sockets, f"factory-{factory_hash}.sock")
      
      try:
        os.unlink(socket_path)
      except OSError:
        pass
      
      await Factory.create(
        game_id=game.id,
        socket_path=socket_path,
        p1_progress=0,
        p2_progress=0,
        threshold=config.factory_threshold
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
      compute=config.player_compute
    )
    
    await Player.create(
      game=game,
      player_id=2,
      pid=p2_pid,
      command_line="opencode",
      prompt_path=p2_prompt,
      bandwidth=config.player_bandwidth,
      compute=config.player_compute
    )
    
    return game.id, game_paths.game
  
  async def run_socket_server(self, game_id: int, game_dir: str):
    game = await Game.get(id=game_id)
    factories = await Factory.filter(game=game_id).all()
    
    sockets = []
    for factory in factories:
      sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
      sock.bind(factory.socket_path)
      sockets.append((sock, factory))
      print(f"Created socket: {factory.socket_path}")
    
    print("Socket server running... (Press Ctrl+C to stop)")
    
    try:
      while True:
        readable, _, _ = select.select([s[0] for s in sockets], [], [], 1.0)
        
        for sock in readable:
          for s, factory in sockets:
            if s == sock:
              data, _ = sock.recvfrom(1024)
              
              ones = sum(1 for byte in data if byte == 1 or byte == ord('1'))
              zeros = sum(1 for byte in data if byte == 0 or byte == ord('0'))
              
              print(f"Factory {factory.id}: Received {len(data)} bytes - {ones} ones, {zeros} zeros")
              break
               
    except KeyboardInterrupt:
      print("\nShutting down socket server...")
    finally:
      for sock, _ in sockets:
        sock.close()
      await Tortoise.close_connections()

@click.command()
@click.option('--game', type=int, help='Resume existing game by ID')
def main(game):
  async def run():
    yar = Yar()
    await yar.init_db()
    yar.find_players()
    
    if len(yar.player_pids) >= 2:
      print(f"P1 PID: {yar.player_pids[0]}")
      print(f"P2 PID: {yar.player_pids[1]}")
    else:
      print(f"Found {len(yar.player_pids)} opencode processes (need 2)")
    
    if game:
      game_record = await Game.get_or_none(id=game)
      if game_record:
        print(f"Resuming game {game:03d}...")
        game_paths = GamePaths(game)
        game_dir = game_paths.game
        game_id = game
      else:
        print(f"Game {game:03d} not found!")
        return
    else:
      print("Setting up a new game...")
      game_id, game_dir = await yar.setup_game()
      print(f"Game {game_id:03d} created!")
    
    await yar.run_socket_server(game_id, game_dir)
  
  asyncio.run(run())

if __name__ == "__main__":
  main()

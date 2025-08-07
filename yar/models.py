#!/usr/bin/env python3

import os
import random
import string
from dataclasses import dataclass
from enum import Enum

from tortoise import fields
from tortoise.models import Model


@dataclass
class BandwidthManager:
    bytes_available: float
    bytes_max: int = 10240
    refill_rate: int = 0


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
        self.sockets = "/yar/games/sockets"
        self.scores = os.path.join(self.game, "territories")


class EventSource(str, Enum):
    TICK = "Tick"
    BANDWIDTH_EXCEEDED = "BandwidthExceeded"


class Config(Model):
    id = fields.IntField(primary_key=True)
    socket_threshold = fields.IntField(default=100)
    player_bandwidth = fields.IntField(default=10)
    player_compute = fields.IntField(default=5)
    bandwidth_penalty = fields.IntField(default=1)


class Game(Model):
    id = fields.IntField(primary_key=True)
    foo = fields.IntField(default=1000)
    created_at = fields.DatetimeField(auto_now_add=True)
    scores: fields.ReverseRelation["Score"]
    sockets: fields.ReverseRelation["Socket"]
    players: fields.ReverseRelation["Player"]


class Score(Model):
    id = fields.IntField(primary_key=True)
    game = fields.ForeignKeyField("models.Game", related_name="scores")
    file_path = fields.CharField(max_length=255)
    score = fields.IntField(default=0)


class Socket(Model):
    id = fields.IntField(primary_key=True)
    game = fields.ForeignKeyField("models.Game", related_name="sockets")
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


def generate_hash(length=8):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))
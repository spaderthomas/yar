#!/usr/bin/env python3

import asyncio
import socket

import click
from tortoise import Tortoise

from .models import Game, Socket, GamePaths


async def get_latest_game_id():
    game = await Game.all().order_by("-id").first()
    return game.id if game else None


async def resolve_game_id(game_id: int | None):
    if game_id is not None:
        return game_id
    return await get_latest_game_id()


async def init_db():
    await Tortoise.init(
        db_url="sqlite:///yar/games/yar.sqlite3", modules={"models": ["yar.models"]}
    )


async def run_client(game: int | None, player: str, bandwidth: int, debug: bool):
    await init_db()
    gid = await resolve_game_id(game)
    if gid is None:
        click.echo("No games found")
        return

    factories = await Socket.filter(game_id=gid).all()
    if not factories:
        click.echo("No sockets found")
        return

    byte_val = bytes([int(player)])
    socks: list[socket.socket] = []
    game_paths = GamePaths(gid)
    try:
        for idx, f in enumerate(factories):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            socket_path = f"{game_paths.sockets}/yar-{idx+1:03d}"
            s.connect(socket_path)
            if debug:
                click.echo(f"Connected to socket {socket_path}")
            socks.append(s)

        interval = 1.0 / max(1, bandwidth)
        while True:
            for s in socks:
                s.send(byte_val)
            if debug:
                click.echo(f"Sent {byte_val!r} to {len(socks)} sockets")
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        for s in socks:
            s.close()
        await Tortoise.close_connections()
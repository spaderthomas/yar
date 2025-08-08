#!/usr/bin/env python3

import asyncio
import socket as psocket

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

    sockets = await Socket.filter(game_id=gid).all()
    if not sockets:
        click.echo("No sockets found")
        return

    byte_val = bytes([int(player)])
    socks: list[psocket.socket] = []
    game_paths = GamePaths(gid)
    
    click.echo(f"Starting client for Game {gid}, Player {player}")
    click.echo(f"Bandwidth: {bandwidth} bytes/second")
    click.echo(f"Found {len(sockets)} socket(s)")
    
    try:
        for idx in range(1, len(sockets) + 1):
            s = psocket.socket(psocket.AF_UNIX, psocket.SOCK_DGRAM)
            socket_path = f"{game_paths.sockets}/yar-{idx:03d}"
            s.connect(socket_path)
            if debug:
                click.echo(f"Connected to socket {socket_path}")
            socks.append(s)

        # Calculate how to distribute bandwidth across all sockets
        num_sockets = len(socks)
        sends_per_second = min(100, bandwidth / num_sockets)
        bytes_per_send = max(1, bandwidth // (sends_per_second * num_sockets))
        interval = 1.0 / max(1, sends_per_second)
        
        data_to_send = byte_val * bytes_per_send
        
        while True:
            for s in socks:
                s.send(data_to_send)
            if debug:
                total_bytes = bytes_per_send * len(socks)
                click.echo(f"Sent {bytes_per_send} bytes to {len(socks)} sockets ({total_bytes} bytes total)")
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        for s in socks:
            s.close()
        await Tortoise.close_connections()
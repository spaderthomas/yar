#!/usr/bin/env python3

import asyncio
import os
import socket
import time
import click
from tortoise import Tortoise
from yar import Factory, Game


async def get_latest_game_id():
    game = await Game.all().order_by("-id").first()
    return game.id if game else None


async def resolve_game_id(game_id: int | None):
    if game_id is not None:
        return game_id
    return await get_latest_game_id()


async def init_db():
    await Tortoise.init(
        db_url="sqlite:///yar/games/yar.sqlite3", modules={"models": ["yar"]}
    )


async def async_main(game: int | None, player: str, bandwidth: int, debug: bool):
    await init_db()
    gid = await resolve_game_id(game)
    if gid is None:
        click.echo("No games found")
        return

    factories = await Factory.filter(game_id=gid).all()
    if not factories:
        click.echo("No factories found")
        return

    # Player sends their ID as a byte
    byte_val = bytes([int(player)])
    socks: list[socket.socket] = []
    try:
        for f in factories:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            s.connect(f.socket_path)
            if debug:
                click.echo(f"Connected to socket {f.socket_path}")
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


@click.command()
@click.option("--game", type=int, help="Game ID (defaults to latest)")
@click.option(
    "--player",
    type=click.Choice(["1", "2"]),
    default="1",
    show_default=True,
    help="Player ID (1 or 2)",
)
@click.option(
    "--bandwidth",
    type=int,
    default=64,
    show_default=True,
    help="Bytes per second to send",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logs")
def main(game: int | None, player: str, bandwidth: int, debug: bool):
    asyncio.run(async_main(game, player, bandwidth, debug))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

import asyncio

import click

from .models import Game, GamePaths
from .server import YarServer


@click.group()
def cli():
    """YAR - Competitive Socket Writing Game"""
    pass


@cli.command()
@click.option("--game", type=int, help="Resume existing game by ID")
@click.option("--debug", is_flag=True, default=False, help="Enable debug logs")
def server(game, debug):
    """Run the game server"""
    async def run():
        debug_flag = debug
        yar = YarServer()
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


@cli.command()
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
def client(game, player, bandwidth, debug):
    """Run a test client"""
    from .client import run_client
    asyncio.run(run_client(game, player, bandwidth, debug))


@cli.command()
@click.option("--game", type=int, help="Game ID (defaults to latest)")
def ui(game):
    """Run the TUI visualization"""
    from .tui import YarTUI
    app = YarTUI(game_id=game)
    app.run()


def main():
    cli()


if __name__ == "__main__":
    main()
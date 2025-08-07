#!/usr/bin/env python3

import asyncio
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.widgets import Header, Footer, Static, Label, DataTable, RichLog
from textual.widget import Widget
from tortoise import Tortoise

from .models import Event, Game, Player, EventSource


class ScoreDisplay(Widget):
    """Widget to display a player's score"""
    
    score = reactive(0)
    
    DEFAULT_CSS = """
    ScoreDisplay {
        height: 5;
        border: solid $primary;
        padding: 1;
    }
    
    ScoreDisplay .player-label {
        text-style: bold;
        color: $text;
    }
    
    ScoreDisplay .score-value {
        text-style: bold;
        color: $success;
        text-align: center;
    }
    """
    
    def __init__(self, player_id: int, **kwargs):
        super().__init__(**kwargs)
        self.player_id = player_id
        
    def compose(self) -> ComposeResult:
        yield Label(f"Player {self.player_id}", classes="player-label")
        yield Label("0", classes="score-value", id=f"score-{self.player_id}")
        
    def watch_score(self, new_score: int) -> None:
        score_label = self.query_one(f"#score-{self.player_id}", Label)
        score_label.update(str(abs(new_score)))


class EventLog(Widget):
    """Widget to display events for a player"""
    
    DEFAULT_CSS = """
    EventLog {
        border: solid $primary;
        height: 100%;
    }
    
    EventLog > Label {
        padding: 0 1;
        text-style: bold;
    }
    
    EventLog RichLog {
        padding: 0 1;
    }
    """
    
    def __init__(self, player_id: int, **kwargs):
        super().__init__(**kwargs)
        self.player_id = player_id
        
    def compose(self) -> ComposeResult:
        yield Label(f"Player {self.player_id} Events")
        yield RichLog(highlight=True, markup=True, id=f"log-{self.player_id}")
        
    def add_event(self, event: Event) -> None:
        log = self.query_one(f"#log-{self.player_id}", RichLog)
        
        if event.source == EventSource.TICK:
            style = "[green]" if event.delta > 0 else "[dim]"
            icon = "⬆" if event.delta > 0 else "○"
        elif event.source == EventSource.BANDWIDTH_EXCEEDED:
            style = "[red]"
            icon = "⚠"
        else:
            style = "[white]"
            icon = "•"
            
        timestamp = event.created_at.strftime("%H:%M:%S")
        message = f"{style}{timestamp} {icon} {event.source.value}: {event.delta:+d} → {event.new_score}[/]"
        log.write(message)


class YarTUI(App):
    """TUI for visualizing YAR games"""
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    #scores-container {
        height: 7;
        margin: 1;
    }
    
    #events-container {
        margin: 1;
    }
    
    #game-info {
        dock: top;
        height: 3;
        background: $panel;
        padding: 1;
        text-align: center;
        text-style: bold;
    }
    """
    
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
    ]
    
    def __init__(self, game_id: int | None = None, **kwargs):
        super().__init__(**kwargs)
        self.game_id = game_id
        self.db_initialized = False
        self.last_event_id = 0
        
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Connecting to game...", id="game-info")
        
        with Horizontal(id="scores-container"):
            yield ScoreDisplay(1, id="score-display-1")
            yield ScoreDisplay(2, id="score-display-2")
            
        with Horizontal(id="events-container"):
            yield EventLog(1, id="event-log-1")
            yield EventLog(2, id="event-log-2")
            
        yield Footer()
        
    async def on_mount(self) -> None:
        await self.init_db()
        # Update more frequently for live view
        self.set_interval(0.5, self.update_game_state)
        
    async def init_db(self) -> None:
        # Check if running in container or locally
        import os
        if os.path.exists("/yar/games/yar.sqlite3"):
            db_path = "sqlite:///yar/games/yar.sqlite3"
        else:
            db_path = "sqlite:///root/source/yar/games/yar.sqlite3"
            
        await Tortoise.init(
            db_url=db_path, 
            modules={"models": ["yar.models"]}
        )
        self.db_initialized = True
        
        if self.game_id is None:
            game = await Game.all().order_by("-id").first()
            if game:
                self.game_id = game.id
                
        if self.game_id:
            info = self.query_one("#game-info", Static)
            info.update(f"Game #{self.game_id:03d}")
        else:
            info = self.query_one("#game-info", Static)
            info.update("No game found")
            
    async def update_game_state(self) -> None:
        if not self.db_initialized or not self.game_id:
            return
            
        try:
            players = await Player.filter(game_id=self.game_id).all()
            
            for player in players:
                score_display = self.query_one(f"#score-display-{player.player_id}", ScoreDisplay)
                score_display.score = player.score
                
            events = await Event.filter(
                game_id=self.game_id,
                id__gt=self.last_event_id
            ).order_by("id").prefetch_related("player")
            
            for event in events:
                if event.player:
                    event_log = self.query_one(f"#event-log-{event.player.player_id}", EventLog)
                    event_log.add_event(event)
                    self.last_event_id = max(self.last_event_id, event.id)
                    
        except Exception as e:
            self.log.error(f"Error updating game state: {e}")
            
    def action_refresh(self) -> None:
        self.call_later(self.update_game_state)
        
    async def action_quit(self) -> None:
        await Tortoise.close_connections()
        self.exit()


if __name__ == "__main__":
    app = YarTUI()
    app.run()
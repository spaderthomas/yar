#!/usr/bin/env python3

import asyncio
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Container, ScrollableContainer
from textual.reactive import reactive
from textual.widgets import Header, Footer, Static, Label, DataTable, ProgressBar
from textual.widget import Widget
from tortoise import Tortoise

from .models import Paths, GamePaths, Event, Game, Player, EventSource

class Labels:
    def __init__(self, pid: int):
        self.main = f'player{pid}'
        self.score = f'p{pid}-score'
        self.bandwidth = f'p{pid}-bandwidth-label'
        self.bandwidth_bar = f'p{pid}-bandwidth-bar'
        self.bandwidth_max = f'p{pid}-max-bandwidth'

class PlayerOverview(Widget):
    """Widget to display player overview with score and bandwidth"""
    
    player_id: reactive[int] = reactive(0)
    score: reactive[int] = reactive(0)
    bandwidth_usage: reactive[float] = reactive(0.0)
    max_bandwidth: reactive[int] = reactive(10)
    
    DEFAULT_CSS = """
    PlayerOverview {
        height: 8;
        padding: 0 1;
    }
    
    PlayerOverview.player1 {
        border: solid $success;
    }
    
    PlayerOverview.player2 {
        border: solid $warning;
    }
    
    PlayerOverview .player-title {
        text-align: center;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    
    PlayerOverview.player1 .player-title {
        color: $success;
    }
    
    PlayerOverview.player2 .player-title {
        color: $warning;
    }
    
    PlayerOverview .score-label {
        text-style: bold;
        margin-bottom: 1;
    }
    
    PlayerOverview .bandwidth-label {
        text-style: italic;
    }
    
    PlayerOverview ProgressBar {
        height: 1;
        margin-bottom: 1;
    }
    """
    
    def __init__(self, player_id: int, **kwargs):
        super().__init__(**kwargs)
        self.player_id: int = player_id
        self.score: int = 0
        self.bandwidth_usage: float = 0.0
        self.max_bandwidth: int = 10
        self.labels = Labels(player_id)
        self.add_class(self.labels.main)
        
    def compose(self) -> ComposeResult:
        yield Label(f"Player {self.player_id}", classes="player-title")
        yield Label(f"Score: 0", id=self.labels.score, classes="score-label")
        yield Label(f"Bandwidth: 0.0 KB/s", id=self.labels.bandwidth, classes="bandwidth-label")
        yield ProgressBar(total=100, show_eta=False, id=self.labels.bandwidth_bar)
        yield Label(f"Max: {self.max_bandwidth} KB/s", id=self.labels.bandwidth_max, classes="bandwidth-label")
        
    def update_player_data(self, score: int, bandwidth_usage: float, max_bandwidth: int) -> None:
        self.score = score
        self.bandwidth_usage = bandwidth_usage
        self.max_bandwidth = max_bandwidth
        
        score_label = self.query_one(self.labels.score, Label)
        score_label.update(f"Score: {score}")
        
        bandwidth_label = self.query_one(self.labels.bandwidth, Label)
        bandwidth_kb = bandwidth_usage / 1024
        bandwidth_label.update(f"Bandwidth: {bandwidth_kb:.1f} KB/s")
        
        bandwidth_bar = self.query_one(self.labels.bandwidth_bar, ProgressBar)
        bandwidth_bar.total = max_bandwidth * 1024  # Convert KB to bytes
        bandwidth_bar.progress = bandwidth_usage
        
        # Color the bar based on usage
        if bandwidth_usage > max_bandwidth * 1024 * 0.9:  # Over 90%
            bandwidth_bar.styles.bar_color = "red"
        elif bandwidth_usage > max_bandwidth * 1024 * 0.7:  # Over 70%
            bandwidth_bar.styles.bar_color = "yellow"
        else:
            bandwidth_bar.styles.bar_color = "green"
            
        max_label = self.query_one(self.labels.max_bandwidth, Label)
        max_label.update(f"Max: {max_bandwidth} KB/s")


class PlayerEventTable(Widget):
    """Widget to display events for a specific player"""
    
    player_id: reactive[int] = reactive(0)
    auto_scroll: bool = True
    
    DEFAULT_CSS = """
    PlayerEventTable {
        height: 100%;
    }
    
    PlayerEventTable.player1 {
        border: solid $success;
    }
    
    PlayerEventTable.player2 {
        border: solid $warning;
    }
    
    PlayerEventTable > Label {
        padding: 0 1;
        text-style: bold;
        dock: top;
        height: 1;
    }
    
    PlayerEventTable.player1 > Label {
        color: $success;
    }
    
    PlayerEventTable.player2 > Label {
        color: $warning;
    }
    
    PlayerEventTable DataTable {
        height: 100%;
        scrollbar-gutter: stable;
    }
    
    PlayerEventTable DataTable > .datatable--header {
        background: $surface;
        text-style: bold;
    }
    
    PlayerEventTable DataTable > .datatable--odd-row {
        background: $surface 90%;
    }
    
    PlayerEventTable DataTable > .datatable--even-row {
        background: $surface;
    }
    """
    
    def __init__(self, player_id: int, **kwargs):
        super().__init__(**kwargs)
        self.player_id: int = player_id
        self.auto_scroll: bool = True
        self.add_class(f"player{player_id}")
        
    def compose(self) -> ComposeResult:
        yield Label(f"Player {self.player_id} Events")
        yield DataTable(id=f"p{self.player_id}-events-table")
        
    def on_mount(self) -> None:
        table = self.query_one(f"#p{self.player_id}-events-table", DataTable)
        table.add_columns("Time", "Event", "Delta", "Score")
        table.zebra_stripes = True
        table.cursor_type = "none"  # Disable cursor
        table.show_cursor = False
        
    def add_event(self, event: Event) -> None:
        # Only add events for this player
        if event.player and event.player.player_id != self.player_id:
            return
            
        table = self.query_one(f"#p{self.player_id}-events-table", DataTable)
        
        timestamp = event.created_at.strftime("%H:%M:%S")
        
        if event.source == EventSource.TICK:
            event_type = "TICK"
            style = "green" if event.delta > 0 else "dim"
        elif event.source == EventSource.BANDWIDTH_EXCEEDED:
            event_type = "PENALTY"
            style = "red"
        else:
            event_type = event.source.value
            style = "white"
            
        delta_str = f"{event.delta:+d}" if event.delta != 0 else "0"
        
        # Check if this event already exists in the table (by key)
        event_key = str(event.id)
        if event_key in [str(row) for row in table.rows]:
            return  # Skip duplicate events
        
        table.add_row(
            timestamp,
            event_type,
            delta_str,
            str(event.new_score),
            key=event_key
        )
        
        # Keep only last 100 events per player
        # Remove oldest rows if we exceed the limit
        while table.row_count > 100:
            # Get the first row's key before removing it
            first_row = table.rows[0] if table.rows else None
            if first_row:
                table.remove_row(first_row.key)
            
        # Auto-scroll to bottom if enabled
        if self.auto_scroll and table.row_count > 0:
            # Scroll to the bottom without moving cursor
            table.scroll_end(animate=False)
            
    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Toggle auto-scroll when header is clicked"""
        self.auto_scroll = not self.auto_scroll
        self.notify(f"Auto-scroll {'enabled' if self.auto_scroll else 'disabled'}")


class YarTUI(App):
    """TUI for visualizing YAR games"""
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    #game-info {
        dock: top;
        height: 3;
        padding: 1;
        text-align: center;
        text-style: bold;
    }
    
    #main-container {
        layout: horizontal;
        height: 100%;
    }
    
    .player-half {
        width: 50%;
        padding: 0 1;
    }
    
    .player-overview-container {
        height: 10;
        margin-bottom: 1;
    }
    
    .player-events-container {
        height: 1fr;
    }
    """
    
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("q", "quit", "Quit"),
    ]
    
    def __init__(self, game_id: int | None = None, **kwargs):
        super().__init__(**kwargs)
        self.game_id: int | None = game_id
        self.db_initialized: bool = False
        self.last_event_ids: dict[int, int] = {1: 0, 2: 0}
        
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Connecting to game...", id="game-info")
        
        with Horizontal(id="main-container"):
            # Player 1 half
            with Vertical(classes="player-half"):
                with Container(classes="player-overview-container"):
                    yield PlayerOverview(player_id=1, id="p1-overview")
                with Container(classes="player-events-container"):
                    yield PlayerEventTable(player_id=1, id="p1-events")
                    
            # Player 2 half
            with Vertical(classes="player-half"):
                with Container(classes="player-overview-container"):
                    yield PlayerOverview(player_id=2, id="p2-overview")
                with Container(classes="player-events-container"):
                    yield PlayerEventTable(player_id=2, id="p2-events")
                    
        yield Footer()
        
    async def on_mount(self) -> None:
        await self.init_db()
        # Give the UI time to fully render before starting updates
        self.set_timer(0.5, self.start_updates)
        
    def start_updates(self) -> None:
        """Start the periodic game state updates"""
        self.set_interval(0.1, self.update_game_state)
        
    async def update_game_state(self) -> None:
        self.console.print('foobar!')
        if not self.db_initialized or not self.game_id:
            return
            
        try:
            # Get player data
            players = await Player.filter(game_id=self.game_id).all()
            
            for player in players:
                overview = self.query_one(f"#p{player.player_id}-overview", PlayerOverview)
                overview.update_player_data(
                    score=player.score,
                    bandwidth_usage=player.current_bandwidth,
                    max_bandwidth=player.bandwidth
                )
            
            # Get new events for each player
            for player_id in [1, 2]:
                event_table_widget = self.query_one(f"#p{player_id}-events", PlayerEventTable)
                
                # Always check for new events since last update
                # Don't limit the query - get ALL new events
                events = await Event.filter(
                    game_id=self.game_id,
                    player__player_id=player_id,
                    id__gt=self.last_event_ids[player_id]
                ).order_by("id").prefetch_related("player")
                
                # Add all new events
                for event in events:
                    event_table_widget.add_event(event)
                    # Always update the tracking ID
                    if event.id > self.last_event_ids[player_id]:
                        self.last_event_ids[player_id] = event.id
                    
        except Exception as e:
            self.log.error(f"Error updating game state: {e}")
        
    async def init_db(self) -> None:
        paths: Paths = Paths()
        await Tortoise.init(
            db_url=f"sqlite://{paths.db_file}?mode=ro", 
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
            
            # Load initial events for each player
            for player_id in [1, 2]:
                # Get the latest event to establish our tracking baseline
                latest_event = await Event.filter(
                    game_id=self.game_id,
                    player__player_id=player_id
                ).order_by("-id").first()
                
                # Load last 30 events for initial display
                recent_events = await Event.filter(
                    game_id=self.game_id,
                    player__player_id=player_id,
                    id__gt=max(0, latest_event.id - 30) if latest_event else 0
                ).order_by("id").prefetch_related("player")
                
                event_table_widget = self.query_one(f"#p{player_id}-events", PlayerEventTable)
                
                # Add recent events and track the latest ID
                for event in recent_events:
                    event_table_widget.add_event(event)
                    if event.id > self.last_event_ids[player_id]:
                        self.last_event_ids[player_id] = event.id
        else:
            info = self.query_one("#game-info", Static)
            info.update("No game found")
            
    async def action_quit(self) -> None:
        await Tortoise.close_connections()
        self.exit()


if __name__ == "__main__":
    app = YarTUI()
    app.run()

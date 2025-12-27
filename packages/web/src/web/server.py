"""
LLM-MUD Web Server

FastAPI-based web server providing HTMX client access to the MUD.
Serves HTML client, handles commands via HTTP POST, and provides
WebSocket for real-time game events.
"""

import json
import logging
from contextlib import asynccontextmanager
from typing import Dict, Optional, Any

import ray
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form, Request
from fastapi.responses import HTMLResponse

from core import EntityId
from core.events import get_event_bus
from .ansi import ansi_to_html
from .session import WebSession, WebSessionManager
from .templates_config import get_templates, get_static_files
from .routes import auth_router, game_router


logger = logging.getLogger(__name__)

# Global session manager
_session_manager: Optional[WebSessionManager] = None


def get_session_manager() -> WebSessionManager:
    """Get the global session manager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = WebSessionManager()
    return _session_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("LLM-MUD Web Client starting...")

    # Initialize Ray connection if not already connected
    if not ray.is_initialized():
        ray.init(address="auto", namespace="llmmud", ignore_reinit_error=True)

    yield

    # Cleanup
    logger.info("LLM-MUD Web Client shutting down...")


app = FastAPI(
    title="LLM-MUD Web Client",
    description="HTMX-based browser client for playing the MUD",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", get_static_files(), name="static")

# Include routers
app.include_router(auth_router)
app.include_router(game_router)

# Get templates
templates = get_templates()


# =============================================================================
# HTTP Endpoints
# =============================================================================


@app.get("/", response_class=HTMLResponse)
async def get_client(request: Request):
    """Serve the main game client HTML page."""
    # Create or get session
    session_manager = get_session_manager()

    # Check for existing session cookie
    session_id = request.cookies.get("session_id")
    session = None

    if session_id:
        session = session_manager.get_session(session_id)

    if not session:
        session = session_manager.create_session()
        session_id = session.session_id

    # Render template with session ID
    response = templates.TemplateResponse(
        request=request,
        name="game/client.html",
        context={"session_id": session_id},
    )
    response.set_cookie(key="session_id", value=session_id, httponly=True)

    return response


@app.post("/command")
async def send_command(
    command: str = Form(...),
    session_id: str = Form(...),
):
    """Handle a command from the web client."""
    session_manager = get_session_manager()
    session = session_manager.get_session(session_id)

    if not session:
        return HTMLResponse(
            content='<div class="message message-error">Session expired. Please refresh.</div>'
        )

    if not command.strip():
        return HTMLResponse(content="")

    # Record command
    session.add_to_history(command)

    # Echo the command back
    echo_html = f'<div class="message"><span style="color: #888;">&gt; {command}</span></div>'

    # Process command based on session state
    if not session.player_entity_id:
        # Not logged in - handle login commands
        result = await _handle_login_command(session, command)
    else:
        # Logged in - route to command handler
        result = await _route_command(session, command)

    # Convert result to HTML
    result_html = ""
    if result:
        result_html = f'<div class="message">{ansi_to_html(result)}</div>'

    return HTMLResponse(content=echo_html + result_html)


@app.get("/health")
async def health_check():
    """Health check endpoint for load balancers."""
    return {"status": "healthy"}


# =============================================================================
# WebSocket Handler
# =============================================================================


class WebSocketEventHandler:
    """Handles events from the game and forwards to WebSocket."""

    def __init__(self, websocket: WebSocket, session: WebSession):
        self.websocket = websocket
        self.session = session
        self._closed = False

    async def send_message(self, message: Dict[str, Any]) -> bool:
        """Send a message to the WebSocket."""
        if self._closed:
            return False
        try:
            await self.websocket.send_json(message)
            return True
        except Exception:
            self._closed = True
            return False

    async def send_text(self, text: str, channel: str = "main") -> bool:
        """Send a text message."""
        return await self.send_message(
            {"type": "text", "payload": {"text": ansi_to_html(text), "channel": channel}}
        )

    def close(self):
        """Mark the handler as closed."""
        self._closed = True


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time game messages."""
    await websocket.accept()

    session_manager = get_session_manager()
    session = session_manager.get_session(session_id)

    if not session:
        await websocket.send_json({"type": "error", "payload": {"error": "Invalid session"}})
        await websocket.close()
        return

    # Create event handler for this connection
    handler = WebSocketEventHandler(websocket, session)
    session.set_websocket_handler(handler)

    # Send welcome message
    await handler.send_message(
        {
            "type": "system",
            "payload": {
                "text": "Connected to LLM-MUD. Type 'connect &lt;name&gt; &lt;password&gt;' to login.",
                "level": "info",
            },
        }
    )

    # Subscribe to events for this player if logged in
    subscription_id = None
    if session.player_entity_id:
        subscription_id = await _subscribe_to_player_events(session, handler)

    try:
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()

            # Handle WebSocket messages (for pure WebSocket clients)
            try:
                message = json.loads(data)
                if message.get("type") == "command":
                    command = message.get("payload", {}).get("raw", "")
                    if command:
                        result = await _route_command(session, command)
                        if result:
                            await handler.send_text(result)
            except json.JSONDecodeError:
                # Treat as raw command
                if data.strip():
                    result = await _route_command(session, data.strip())
                    if result:
                        await handler.send_text(result)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    finally:
        handler.close()
        session.clear_websocket_handler()

        # Unsubscribe from events
        if subscription_id:
            try:
                bus = get_event_bus()
                await bus.unsubscribe.remote(subscription_id)
            except Exception:
                pass


# =============================================================================
# Command Processing
# =============================================================================


async def _handle_login_command(session: WebSession, command: str) -> str:
    """Handle commands when not logged in."""
    parts = command.split()
    if not parts:
        return ""

    cmd = parts[0].lower()

    if cmd == "connect" and len(parts) >= 3:
        username = parts[1]
        password = parts[2]
        return await _handle_login(session, username, password)

    elif cmd == "create" and len(parts) >= 2:
        name = parts[1]
        return await _handle_create_character(session, name)

    elif cmd == "quit" or cmd == "exit":
        return "Goodbye!"

    elif cmd == "help":
        return (
            "Available commands:\n"
            "  connect <name> <password>  - Login to your character\n"
            "  create <name>              - Create a new character\n"
            "  quit                       - Exit the game"
        )

    else:
        return "You are not logged in. Type 'connect <name> <password>' to login."


async def _handle_login(session: WebSession, username: str, password: str) -> str:
    """Handle login attempt."""
    try:
        # For now, accept any password (demo mode)
        account_id = f"account:{username.lower()}"
        session.account_id = account_id
        session.username = username

        # Try to load existing character
        player_entity = await _load_player_character(username)

        if player_entity:
            session.player_entity_id = player_entity
            session.character_name = username

            # Subscribe to events
            if session.websocket_handler:
                await _subscribe_to_player_events(session, session.websocket_handler)

            # Show the room
            room_text = await _execute_command(session.player_entity_id, "look")
            return f"Welcome back, {username}!\n\n{room_text}"
        else:
            # Create new character
            return await _handle_create_character(session, username)

    except Exception as e:
        logger.error(f"Login error: {e}")
        return f"Login failed: {e}"


async def _handle_create_character(session: WebSession, name: str) -> str:
    """Handle character creation."""
    try:
        from game.world.factory import get_entity_factory

        factory = get_entity_factory()

        # Get starting room
        start_room = await _get_starting_room()

        player_id = await factory.create_player(
            name=name,
            race_name="human",
            class_name="adventurer",
            account_id=session.account_id or f"account:{name.lower()}",
            start_room_id=start_room,
        )

        session.player_entity_id = player_id
        session.character_name = name
        session.account_id = session.account_id or f"account:{name.lower()}"

        # Subscribe to events
        if session.websocket_handler:
            await _subscribe_to_player_events(session, session.websocket_handler)

        # Show the room
        room_text = await _execute_command(player_id, "look")
        return f"Character {name} created! Welcome to the world.\n\n{room_text}"

    except Exception as e:
        logger.error(f"Character creation error: {e}")
        return f"Failed to create character: {e}"


async def _load_player_character(username: str) -> Optional[EntityId]:
    """Load an existing player character."""
    # For now, return None to always create new characters
    # In production, this would query persistence
    return None


async def _get_starting_room() -> Optional[EntityId]:
    """Get the starting room for new players."""
    try:
        from game.world.templates import get_template_registry

        registry = get_template_registry()
        rooms = registry.get_all_rooms()

        if rooms:
            template_id = list(rooms.keys())[0]
            return EntityId(id=template_id, entity_type="room")
    except Exception:
        pass
    return None


async def _route_command(session: WebSession, command: str) -> str:
    """Route a command to the command handler."""
    if not session.player_entity_id:
        return await _handle_login_command(session, command)

    return await _execute_command(session.player_entity_id, command)


async def _execute_command(player_id: EntityId, command: str) -> str:
    """Execute a command via the CommandHandler."""
    try:
        handler = ray.get_actor("command_handler", namespace="llmmud")
        result = await handler.handle_command.remote(player_id, command)
        return result or ""
    except ValueError:
        # Command handler not found - fallback to local processing
        logger.warning("CommandHandler not found, using local fallback")
        return _local_command_fallback(command)
    except Exception as e:
        logger.error(f"Command execution error: {e}")
        return f"Error executing command: {e}"


def _local_command_fallback(command: str) -> str:
    """Fallback command processing when CommandHandler is unavailable."""
    parts = command.lower().split()
    if not parts:
        return ""

    cmd = parts[0]

    if cmd == "help":
        return (
            "Available commands:\n"
            "  look (l)     - Look around\n"
            "  north (n)    - Go north\n"
            "  south (s)    - Go south\n"
            "  east (e)     - Go east\n"
            "  west (w)     - Go west\n"
            "  quit         - Exit the game"
        )
    elif cmd in ("look", "l"):
        return "You are in a featureless void. The command handler is not available."
    else:
        return f"Command handler not available. Unknown command: {cmd}"


# =============================================================================
# Event Subscription
# =============================================================================


async def _subscribe_to_player_events(
    session: WebSession,
    handler: WebSocketEventHandler,
) -> Optional[str]:
    """Subscribe to events relevant to this player."""
    if not session.player_entity_id:
        return None

    try:
        # Create a Ray actor to receive events and forward to WebSocket
        # For simplicity, we'll poll or use a different mechanism
        # The full implementation would create an actor that receives events

        # For now, return None - events will be handled through command responses
        return None

    except Exception as e:
        logger.error(f"Failed to subscribe to events: {e}")
        return None


# =============================================================================
# Factory Function
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    return app

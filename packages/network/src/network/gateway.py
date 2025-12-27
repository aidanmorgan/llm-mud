"""
Gateway Actor

Central actor for handling player connections and routing messages.
Uses WebSockets for real-time communication.
"""

import logging
import uuid
from typing import Dict, Optional, Any, Set
from dataclasses import dataclass

import ray
from ray.actor import ActorHandle
import websockets
from websockets.server import WebSocketServerProtocol

from core import EntityId
from .session import Session, SessionManager, SessionState
from .protocol import (
    Message,
    MessageType,
    parse_client_message,
    create_text,
    create_error,
    create_room,
    SystemMessage,
    PromptMessage,
)

logger = logging.getLogger(__name__)


@dataclass
class ConnectionInfo:
    """Information about a WebSocket connection."""

    connection_id: str
    websocket: WebSocketServerProtocol
    remote_address: str


@ray.remote
class Gateway:
    """
    Main gateway actor for player connections.

    Responsibilities:
    - Accept WebSocket connections
    - Manage session lifecycle
    - Route messages between clients and game systems
    - Handle authentication
    - Deliver game events to connected players
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 4000,
        command_handler_path: Optional[str] = None,
    ):
        self._host = host
        self._port = port
        self._command_handler_path = command_handler_path

        self._session_manager = SessionManager()
        self._connections: Dict[str, ConnectionInfo] = {}
        self._server: Optional[websockets.WebSocketServer] = None
        self._running = False

        # Track connected players by room for efficient message delivery
        self._room_players: Dict[str, Set[str]] = {}  # room_id -> set of session_ids

    async def start(self) -> None:
        """Start the WebSocket server."""
        if self._running:
            return

        self._running = True
        self._server = await websockets.serve(
            self._handle_connection,
            self._host,
            self._port,
            ping_interval=30,
            ping_timeout=10,
        )
        logger.info(f"Gateway listening on ws://{self._host}:{self._port}")

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        logger.info("Gateway stopped")

    async def _handle_connection(self, websocket: WebSocketServerProtocol, path: str) -> None:
        """Handle a new WebSocket connection."""
        connection_id = uuid.uuid4().hex
        remote_address = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"

        conn_info = ConnectionInfo(
            connection_id=connection_id,
            websocket=websocket,
            remote_address=remote_address,
        )
        self._connections[connection_id] = conn_info

        # Create session
        session = self._session_manager.create_session(connection_id)
        logger.info(f"Connection from {remote_address} (session: {session.session_id})")

        # Send welcome message
        await self._send_to_connection(
            connection_id,
            SystemMessage(
                text="Welcome to LLM-MUD! Type 'connect <name> <password>' to login.",
                level="info",
            )
            .to_message()
            .to_json(),
        )

        try:
            async for message in websocket:
                await self._handle_message(session, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self._handle_disconnect(connection_id)

    async def _handle_message(self, session: Session, raw_message: str) -> None:
        """Handle an incoming message from a client."""
        session.mark_activity()

        # Parse message
        message = parse_client_message(raw_message)
        if not message:
            # Assume raw text is a command
            message = Message(type=MessageType.COMMAND, payload={"raw": raw_message.strip()})

        # Route by message type
        if message.type == MessageType.COMMAND:
            await self._handle_command(session, message.payload.get("raw", ""))
        elif message.type == MessageType.LOGIN:
            await self._handle_login(session, message.payload)
        elif message.type == MessageType.LOGOUT:
            await self._handle_logout(session)
        elif message.type == MessageType.PING:
            await self._send_to_session(
                session, Message(type=MessageType.PONG, payload={}).to_json()
            )
        elif message.type == MessageType.CREATE_CHARACTER:
            await self._handle_create_character(session, message.payload)

    async def _handle_command(self, session: Session, raw_command: str) -> None:
        """Handle a player command."""
        if not raw_command:
            return

        # Add to command history
        session.add_to_history(raw_command)

        # If not logged in, handle login commands
        if session.state == SessionState.LOGIN:
            await self._handle_login_command(session, raw_command)
            return

        # If playing, route to command handler
        if session.is_playing:
            await self._route_to_command_handler(session, raw_command)

    async def _handle_login_command(self, session: Session, command: str) -> None:
        """Handle commands during login state."""
        parts = command.split()
        if not parts:
            return

        cmd = parts[0].lower()

        if cmd == "connect" and len(parts) >= 3:
            # connect <name> <password>
            await self._handle_login(
                session,
                {
                    "username": parts[1],
                    "password": parts[2],
                },
            )
        elif cmd == "create" and len(parts) >= 2:
            # create <name>
            await self._handle_create_character(
                session,
                {
                    "name": parts[1],
                },
            )
        elif cmd == "quit" or cmd == "exit":
            if session.connection_id:
                conn = self._connections.get(session.connection_id)
                if conn:
                    await conn.websocket.close()
        else:
            await self._send_to_session(
                session,
                create_text("Commands available: connect <name> <password>, create <name>, quit"),
            )

    async def _handle_login(self, session: Session, payload: Dict[str, Any]) -> None:
        """Handle login attempt."""
        username = payload.get("username", "")
        password = payload.get("password", "")

        if not username or not password:
            await self._send_to_session(session, create_error("Username and password required"))
            return

        # For now, simple authentication (would be replaced with real auth)
        # Accept any password for demo purposes
        account_id = f"account:{username.lower()}"

        # Check if already logged in elsewhere
        existing = self._session_manager.get_by_account(account_id)
        if existing and existing.is_playing:
            await self._send_to_session(
                session, create_error("Account already logged in from another session")
            )
            return

        # Bind account
        self._session_manager.bind_account(session, account_id)
        session.username = username

        # Try to load existing character
        player_entity = await self._load_player_character(username)

        if player_entity:
            # Existing character found
            self._session_manager.bind_player(session, player_entity)
            session.character_name = username
            session.state = SessionState.CONNECTED
            session.mark_connected(session.connection_id)

            await self._send_to_session(session, create_text(f"Welcome back, {username}!"))

            # Enter the game
            await self._enter_game(session)
        else:
            # No character, need to create one
            session.state = SessionState.CREATING_CHARACTER
            await self._send_to_session(
                session,
                create_text(f"No character found for {username}. Creating a new character..."),
            )
            await self._handle_create_character(session, {"name": username})

    async def _handle_create_character(self, session: Session, payload: Dict[str, Any]) -> None:
        """Handle character creation."""
        name = payload.get("name", "")
        race = payload.get("race", "human")
        class_name = payload.get("class_name", "adventurer")

        if not name:
            await self._send_to_session(session, create_error("Name required"))
            return

        # Create the player entity
        player_entity = await self._create_player_character(
            name=name,
            race=race,
            class_name=class_name,
            account_id=session.account_id or "",
        )

        if not player_entity:
            await self._send_to_session(session, create_error("Failed to create character"))
            return

        # Bind player to session
        self._session_manager.bind_player(session, player_entity)
        session.character_name = name
        session.state = SessionState.CONNECTED
        session.mark_connected(session.connection_id)

        await self._send_to_session(
            session, create_text(f"Character {name} created! Welcome to the world.")
        )

        # Enter the game
        await self._enter_game(session)

    async def _load_player_character(self, username: str) -> Optional[EntityId]:
        """Load an existing player character."""
        # For now, return None to always create new character
        # In production, this would query the component engine
        return None

    async def _create_player_character(
        self, name: str, race: str, class_name: str, account_id: str
    ) -> Optional[EntityId]:
        """Create a new player character entity."""
        try:
            from game.world.factory import get_entity_factory

            factory = get_entity_factory()

            # Find starting room (first room in registry, or create default)
            start_room = await self._get_starting_room()

            player_id = await factory.create_player(
                name=name,
                race_name=race,
                class_name=class_name,
                account_id=account_id,
                start_room_id=start_room,
            )

            logger.info(f"Created player character: {name} -> {player_id}")
            return player_id

        except Exception as e:
            logger.error(f"Failed to create player character: {e}")
            return None

    async def _get_starting_room(self) -> Optional[EntityId]:
        """Get the starting room for new players."""
        from game.world.templates import get_template_registry

        registry = get_template_registry()
        rooms = registry.get_all_rooms()

        if rooms:
            # Use first room as starting room
            template_id = list(rooms.keys())[0]
            return EntityId(id=template_id, entity_type="room")

        # No rooms loaded, return None
        return None

    async def _enter_game(self, session: Session) -> None:
        """Player enters the game world."""
        if not session.player_entity_id:
            return

        # Get player's current room and show it
        await self._show_room(session)

        # Send initial prompt
        await self._send_prompt(session)

        # Track player in room
        await self._update_room_tracking(session)

    async def _show_room(self, session: Session) -> None:
        """Show the current room to the player."""
        if not session.player_entity_id:
            return

        try:
            from core.component import get_component_actor

            # Get player's location
            location_actor = get_component_actor("Location")
            location = await location_actor.get.remote(session.player_entity_id)

            if not location or not location.room_id:
                await self._send_to_session(session, create_text("You are nowhere."))
                return

            # Get room data
            room_actor = get_component_actor("Room")
            room = await room_actor.get.remote(location.room_id)

            if not room:
                await self._send_to_session(session, create_text("You are in a featureless void."))
                return

            # Get room identity for name
            identity_actor = get_component_actor("Identity")
            identity = await identity_actor.get.remote(location.room_id)
            room_name = identity.name if identity else "A Room"

            # Get entities in room
            entities_in_room = await self._get_entities_in_room(location.room_id)

            # Get items in room
            items_in_room = await self._get_items_in_room(location.room_id)

            # Build room message
            await self._send_to_session(
                session,
                create_room(
                    name=room_name,
                    description=room.long_description,
                    exits=room.get_available_exits(),
                    entities=[
                        {
                            "name": e["name"],
                            "short_desc": e["short_desc"],
                            "type": e["type"],
                        }
                        for e in entities_in_room
                        if e["id"] != session.player_entity_id
                    ],
                    items=[
                        {"name": i["name"], "short_desc": i["short_desc"]} for i in items_in_room
                    ],
                ),
            )

        except Exception as e:
            logger.error(f"Error showing room: {e}")
            await self._send_to_session(session, create_text("Error: Could not display room."))

    async def _get_entities_in_room(self, room_id: EntityId) -> list:
        """Get all entities in a room."""
        from core.component import get_component_actor

        entities = []
        try:
            location_actor = get_component_actor("Location")
            identity_actor = get_component_actor("Identity")

            all_locations = await location_actor.get_all.remote()
            for entity_id, location in all_locations.items():
                if location.room_id == room_id:
                    identity = await identity_actor.get.remote(entity_id)
                    if identity:
                        entities.append(
                            {
                                "id": entity_id,
                                "name": identity.name,
                                "short_desc": identity.short_description,
                                "type": entity_id.entity_type,
                            }
                        )
        except Exception as e:
            logger.error(f"Error getting entities in room: {e}")

        return entities

    async def _get_items_in_room(self, room_id: EntityId) -> list:
        """Get items on the ground in a room."""
        from core.component import get_component_actor

        items = []
        try:
            location_actor = get_component_actor("Location")
            identity_actor = get_component_actor("Identity")
            item_actor = get_component_actor("Item")

            all_locations = await location_actor.get_all.remote()
            for entity_id, location in all_locations.items():
                if location.room_id == room_id and entity_id.entity_type == "item":
                    # Check it's actually an item
                    item_data = await item_actor.get.remote(entity_id)
                    if item_data:
                        identity = await identity_actor.get.remote(entity_id)
                        if identity:
                            items.append(
                                {
                                    "id": entity_id,
                                    "name": identity.name,
                                    "short_desc": identity.short_description,
                                }
                            )
        except Exception as e:
            logger.error(f"Error getting items in room: {e}")

        return items

    async def _send_prompt(self, session: Session) -> None:
        """Send status prompt to player."""
        if not session.player_entity_id:
            return

        try:
            from core.component import get_component_actor

            stats_actor = get_component_actor("Stats")
            stats = await stats_actor.get.remote(session.player_entity_id)

            if stats:
                combat_actor = get_component_actor("Combat")
                combat = await combat_actor.get.remote(session.player_entity_id)
                combat_target = None
                if combat and combat.target:
                    # Get target name
                    identity_actor = get_component_actor("Identity")
                    target_identity = await identity_actor.get.remote(combat.target)
                    if target_identity:
                        combat_target = target_identity.name

                await self._send_to_session(
                    session,
                    PromptMessage(
                        hp=stats.current_health,
                        max_hp=stats.max_health,
                        mana=stats.current_mana,
                        max_mana=stats.max_mana,
                        position="standing",
                        combat_target=combat_target,
                    )
                    .to_message()
                    .to_json(),
                )

        except Exception as e:
            logger.error(f"Error sending prompt: {e}")

    async def _route_to_command_handler(self, session: Session, command: str) -> None:
        """Route command to the command handler system."""
        if not self._command_handler_path:
            # No command handler configured, process locally
            await self._process_command_locally(session, command)
            return

        try:
            handler = ray.get_actor(self._command_handler_path, namespace=GATEWAY_NAMESPACE)
            result = await handler.handle_command.remote(session.player_entity_id, command)

            # Send result to player
            if result:
                await self._send_to_session(session, create_text(result))

            # Always send updated prompt
            await self._send_prompt(session)

        except Exception as e:
            logger.error(f"Error routing command: {e}")
            await self._send_to_session(session, create_error("Error processing command"))

    async def _process_command_locally(self, session: Session, command: str) -> None:
        """Process a command locally (basic implementation)."""
        parts = command.lower().split()
        if not parts:
            return

        cmd = parts[0]

        if cmd == "look" or cmd == "l":
            await self._show_room(session)
        elif cmd == "quit":
            await self._handle_logout(session)
        elif cmd in (
            "north",
            "south",
            "east",
            "west",
            "up",
            "down",
            "n",
            "s",
            "e",
            "w",
            "u",
            "d",
        ):
            await self._send_to_session(
                session, create_text("Movement system not fully implemented yet.")
            )
        else:
            await self._send_to_session(session, create_text(f"Unknown command: {cmd}"))

        await self._send_prompt(session)

    async def _handle_logout(self, session: Session) -> None:
        """Handle player logout."""
        if session.is_playing:
            await self._send_to_session(session, create_text("Goodbye! Come back soon."))

        # Close connection
        if session.connection_id:
            conn = self._connections.get(session.connection_id)
            if conn:
                await conn.websocket.close()

    async def _handle_disconnect(self, connection_id: str) -> None:
        """Handle connection disconnect."""
        session = self._session_manager.handle_disconnect(connection_id)

        if connection_id in self._connections:
            del self._connections[connection_id]

        if session:
            # Update room tracking if linkdead
            await self._update_room_tracking(session)

        logger.info(f"Connection {connection_id} disconnected")

    async def _update_room_tracking(self, session: Session) -> None:
        """Update room tracking for message delivery."""
        if not session.player_entity_id:
            return

        try:
            from core.component import get_component_actor

            location_actor = get_component_actor("Location")
            location = await location_actor.get.remote(session.player_entity_id)

            if location and location.room_id:
                room_key = f"{location.room_id.id}:{location.room_id.entity_type}"
                if room_key not in self._room_players:
                    self._room_players[room_key] = set()

                if session.is_connected:
                    self._room_players[room_key].add(session.session_id)
                else:
                    self._room_players[room_key].discard(session.session_id)

        except Exception as e:
            logger.error(f"Error updating room tracking: {e}")

    async def _send_to_session(self, session: Session, message: str) -> None:
        """Send message to a session."""
        if session.connection_id and session.is_connected:
            await self._send_to_connection(session.connection_id, message)
        elif session.is_linkdead:
            session.buffer_output(message)

    async def _send_to_connection(self, connection_id: str, message: str) -> None:
        """Send message to a specific connection."""
        conn = self._connections.get(connection_id)
        if conn:
            try:
                await conn.websocket.send(message)
            except websockets.exceptions.ConnectionClosed:
                pass

    # =========================================================================
    # Public API for Game Systems
    # =========================================================================

    async def send_to_player(self, player_entity_id: EntityId, message: str) -> None:
        """Send a message to a specific player."""
        session = self._session_manager.get_by_player(player_entity_id)
        if session:
            await self._send_to_session(session, message)

    async def send_to_room(
        self, room_id: EntityId, message: str, exclude: Optional[EntityId] = None
    ) -> None:
        """Send a message to all players in a room."""
        room_key = f"{room_id.id}:{room_id.entity_type}"
        session_ids = self._room_players.get(room_key, set())

        for session_id in session_ids:
            session = self._session_manager.get_session(session_id)
            if session and session.is_connected:
                if exclude and session.player_entity_id == exclude:
                    continue
                await self._send_to_session(session, message)

    async def broadcast(self, message: str, channel: str = "system") -> None:
        """Broadcast a message to all connected players."""
        for session in self._session_manager.get_all_playing():
            await self._send_to_session(session, create_text(message, channel))

    async def get_stats(self) -> Dict[str, Any]:
        """Get gateway statistics."""
        return {
            "connections": len(self._connections),
            "sessions": self._session_manager.get_stats(),
            "rooms_tracked": len(self._room_players),
        }


# ============================================================================
# Gateway Actor Management
# ============================================================================

GATEWAY_ACTOR_NAME = "gateway"
GATEWAY_NAMESPACE = "llmmud"

_gateway_actor: Optional[ActorHandle] = None


def get_gateway() -> ActorHandle:
    """Get the global gateway actor."""
    global _gateway_actor
    if _gateway_actor is None:
        _gateway_actor = ray.get_actor(GATEWAY_ACTOR_NAME, namespace=GATEWAY_NAMESPACE)
    return _gateway_actor  # type: ignore[return-value]


async def start_gateway(
    host: str = "0.0.0.0", port: int = 4000, command_handler_name: Optional[str] = None
) -> ActorHandle:
    """Start the gateway actor."""
    global _gateway_actor

    gateway = Gateway.options(
        name=GATEWAY_ACTOR_NAME, namespace=GATEWAY_NAMESPACE, lifetime="detached"
    ).remote(
        host=host, port=port, command_handler_path=command_handler_name  # type: ignore[call-arg]
    )

    await gateway.start.remote()
    _gateway_actor = gateway

    return gateway

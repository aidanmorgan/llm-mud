"""Game routes for the main gameplay interface."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Form, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import get_player_store, PlayerStore
from ..auth import verify_token, TokenData
from ..templates_config import get_templates


router = APIRouter()
templates = get_templates()


async def get_store() -> PlayerStore:
    """Dependency to get the player store."""
    store = get_player_store()
    await store.initialize()
    return store


async def get_current_character(request: Request) -> Optional[TokenData]:
    """
    Get the current authenticated character from cookies.

    Returns None if not authenticated or no character selected.
    """
    token = request.cookies.get("session")
    if not token:
        return None
    token_data = verify_token(token)
    if not token_data or not token_data.character_id:
        return None
    return token_data


async def require_character(request: Request) -> TokenData:
    """
    Require character selection.

    Raises HTTPException if not authenticated or no character.
    """
    token_data = await get_current_character(request)
    if not token_data:
        raise HTTPException(status_code=401, detail="No character selected")
    return token_data


@router.get("/game", response_class=HTMLResponse)
async def game_page(
    request: Request,
    store: PlayerStore = Depends(get_store),
):
    """Display the main game interface."""
    token_data = await get_current_character(request)
    if not token_data:
        return RedirectResponse(url="/characters", status_code=303)

    character = await store.get_character(token_data.character_id)
    if not character:
        return RedirectResponse(url="/characters", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="game/play.html",
        context={"character": character},
    )


@router.post("/api/command")
async def process_command(
    request: Request,
    command: str = Form(...),
    store: PlayerStore = Depends(get_store),
):
    """Process a game command."""
    token_data = await get_current_character(request)
    if not token_data:
        return HTMLResponse('<div class="error">Session expired. Please refresh.</div>')

    character = await store.get_character(token_data.character_id)
    if not character:
        return HTMLResponse('<div class="error">Character not found.</div>')

    # Format the command echo
    command_echo = f'\n<span style="color: #888">&gt; {command}</span>\n'

    # Here we would forward the command to the game server
    # For now, return a placeholder response
    if command.lower() == "look":
        response = """
City Square

You stand in the heart of Ravenmoor's city square. A worn cobblestone plaza
spreads before you, surrounded by weathered buildings. A crumbling fountain
sits in the center, its waters long since dried up.

To the north, the castle road leads toward the imposing walls of the keep.
The market district lies to the east, while the tavern's sign creaks to the west.

Exits: [north] [east] [west] [south]
"""
    elif command.lower() == "help":
        response = """
Available Commands:
  Movement: north, south, east, west, up, down
  Info: look, score, inventory, equipment, who, time
  Combat: kill, flee, consider
  Items: get, drop, wear, remove, wield
  Social: say, shout, tell, emote
  Other: help, quit, save

Type 'help <command>' for more information on a specific command.
"""
    elif command.lower() in ("n", "north", "s", "south", "e", "east", "w", "west"):
        response = "You cannot go that way."
    elif command.lower() == "score":
        response = f"""
Character: {character.name}
Level: {character.level}  Race: {character.race_id.title()}  Class: {character.class_id.title()}

  Strength: {character.stats.get('strength', 10):>3}    HP: {character.stats.get('hp', 20)}/{character.stats.get('max_hp', 20)}
  Dexterity: {character.stats.get('dexterity', 10):>3}   Mana: {character.stats.get('mana', 10)}/{character.stats.get('max_mana', 10)}
  Constitution: {character.stats.get('constitution', 10):>3}   Stamina: {character.stats.get('stamina', 100)}/{character.stats.get('max_stamina', 100)}
  Intelligence: {character.stats.get('intelligence', 10):>3}
  Wisdom: {character.stats.get('wisdom', 10):>3}   Experience: {character.experience}
  Charisma: {character.stats.get('charisma', 10):>3}   Gold: {character.gold}
"""
    elif command.lower() in ("inv", "inventory"):
        response = "You are not carrying anything."
    elif command.lower() in ("eq", "equipment"):
        response = "You are not wearing anything."
    elif command.lower() == "who":
        online = await store.get_online_characters()
        if online:
            response = f"Players Online: {len(online)}\n"
            for char_id in online[:10]:
                char = await store.get_character(char_id)
                if char:
                    response += f"  {char.name} (Level {char.level} {char.class_id.title()})\n"
        else:
            response = "No other players online."
    elif command.lower() == "quit":
        response = "Use the 'Logout' link to leave the game safely."
    elif command.lower().startswith("say "):
        msg = command[4:].strip()
        response = f'You say, "{msg}"'
    else:
        response = f"Unknown command: {command}. Type 'help' for commands."

    return HTMLResponse(f'{command_echo}<div class="response">{response}</div>')


@router.websocket("/ws/game")
async def websocket_game(websocket: WebSocket):
    """WebSocket endpoint for real-time game updates."""
    await websocket.accept()

    # Get session from cookies
    token = websocket.cookies.get("session")
    if not token:
        await websocket.close(code=4001)
        return

    token_data = verify_token(token)
    if not token_data or not token_data.character_id:
        await websocket.close(code=4001)
        return

    try:
        while True:
            # Receive messages (commands from client)
            data = await websocket.receive_text()

            # Here we would process commands and send responses
            # For now, just echo
            await websocket.send_text(f'<div>Received: {data}</div>')

    except WebSocketDisconnect:
        # Mark character as offline
        store = get_player_store()
        await store.set_character_offline(token_data.character_id)

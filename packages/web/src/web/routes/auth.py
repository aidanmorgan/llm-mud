"""Authentication routes for registration, login, and character management."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Response, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import get_player_store, PlayerStore
from ..auth import (
    create_access_token,
    verify_token,
    validate_password_strength,
    validate_email,
    validate_character_name,
    TokenData,
)
from ..templates_config import get_templates


router = APIRouter()
templates = get_templates()


# Race and class options for character creation
RACES = [
    {"id": "human", "name": "Human", "description": "Versatile and adaptable. Balanced stats."},
    {"id": "elf", "name": "Elf", "description": "Graceful and long-lived. High dexterity and intelligence."},
    {"id": "dwarf", "name": "Dwarf", "description": "Sturdy and resilient. High constitution and strength."},
    {"id": "halfling", "name": "Halfling", "description": "Small but lucky. High dexterity and charisma."},
    {"id": "orc", "name": "Orc", "description": "Fierce and powerful. High strength, lower intelligence."},
]

CLASSES = [
    {"id": "warrior", "name": "Warrior", "description": "Master of weapons and armor. High health and damage."},
    {"id": "mage", "name": "Mage", "description": "Wielder of arcane magic. Powerful spells but fragile."},
    {"id": "cleric", "name": "Cleric", "description": "Divine healer and protector. Balanced with healing magic."},
    {"id": "rogue", "name": "Rogue", "description": "Stealthy and cunning. High damage from surprise attacks."},
    {"id": "ranger", "name": "Ranger", "description": "Master of bow and nature. Balanced fighter with tracking."},
]


async def get_store() -> PlayerStore:
    """Dependency to get the player store."""
    store = get_player_store()
    await store.initialize()
    return store


async def get_current_account(request: Request) -> Optional[TokenData]:
    """
    Get the current authenticated account from cookies.

    Returns None if not authenticated.
    """
    token = request.cookies.get("session")
    if not token:
        return None
    return verify_token(token)


async def require_auth(request: Request) -> TokenData:
    """
    Require authentication.

    Raises HTTPException if not authenticated.
    """
    token_data = await get_current_account(request)
    if not token_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return token_data


# Registration

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Display registration form."""
    # Check if already logged in
    token_data = await get_current_account(request)
    if token_data:
        return RedirectResponse(url="/characters", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="auth/register.html",
    )


@router.post("/api/register")
async def register(
    email: str = Form(...),
    password: str = Form(...),
    confirm: str = Form(...),
    store: PlayerStore = Depends(get_store),
):
    """Process registration form."""
    # Validate email
    valid, error = validate_email(email)
    if not valid:
        return HTMLResponse(f'<div class="error">{error}</div>')

    # Validate password
    valid, error = validate_password_strength(password)
    if not valid:
        return HTMLResponse(f'<div class="error">{error}</div>')

    # Check passwords match
    if password != confirm:
        return HTMLResponse('<div class="error">Passwords do not match</div>')

    # Check if email exists
    existing = await store.get_account_by_email(email)
    if existing:
        return HTMLResponse('<div class="error">Email already registered</div>')

    # Create account
    try:
        await store.create_account(email, password)
    except ValueError as e:
        return HTMLResponse(f'<div class="error">{str(e)}</div>')

    return HTMLResponse('''
        <div class="success">
            Account created! <a href="/login">Click here to login</a>
        </div>
    ''')


# Login

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Display login form."""
    # Check if already logged in
    token_data = await get_current_account(request)
    if token_data:
        return RedirectResponse(url="/characters", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
    )


@router.post("/api/login")
async def login(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    store: PlayerStore = Depends(get_store),
):
    """Process login form."""
    account = await store.verify_password(email, password)
    if not account:
        return HTMLResponse('<div class="error">Invalid email or password</div>')

    # Update last login
    await store.update_last_login(account.account_id)

    # Create token
    token = create_access_token(
        account_id=account.account_id,
        is_admin=account.is_admin,
    )

    # Set cookie and redirect
    response = HTMLResponse(
        '<script>window.location.href="/characters"</script>'
    )
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        max_age=86400,  # 24 hours
    )
    return response


@router.get("/logout")
async def logout(response: Response):
    """Log out and clear session."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session")
    return response


# Character selection

@router.get("/characters", response_class=HTMLResponse)
async def characters_page(
    request: Request,
    store: PlayerStore = Depends(get_store),
):
    """Display character selection screen."""
    token_data = await get_current_account(request)
    if not token_data:
        return RedirectResponse(url="/login", status_code=303)

    characters = await store.get_characters(token_data.account_id)

    return templates.TemplateResponse(
        request=request,
        name="auth/characters.html",
        context={"characters": characters},
    )


@router.post("/api/select-character")
async def select_character(
    request: Request,
    response: Response,
    character_id: str = Form(...),
    store: PlayerStore = Depends(get_store),
):
    """Select a character to play."""
    token_data = await get_current_account(request)
    if not token_data:
        raise HTTPException(status_code=401)

    # Verify character belongs to account
    character = await store.get_character(character_id)
    if not character or character.account_id != token_data.account_id:
        raise HTTPException(status_code=404, detail="Character not found")

    # Create new token with character
    token = create_access_token(
        account_id=token_data.account_id,
        character_id=character_id,
        is_admin=token_data.is_admin,
    )

    # Mark character as online
    await store.set_character_online(character_id, "web")

    response = HTMLResponse('<script>window.location.href="/game"</script>')
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=86400,
    )
    return response


# Character creation

@router.get("/create-character", response_class=HTMLResponse)
async def create_character_page(request: Request):
    """Display character creation form."""
    token_data = await get_current_account(request)
    if not token_data:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="auth/create_character.html",
        context={
            "races": RACES,
            "classes": CLASSES,
        },
    )


@router.post("/api/create-character")
async def create_character(
    request: Request,
    response: Response,
    name: str = Form(...),
    race_id: str = Form(...),
    class_id: str = Form(...),
    store: PlayerStore = Depends(get_store),
):
    """Process character creation."""
    token_data = await get_current_account(request)
    if not token_data:
        raise HTTPException(status_code=401)

    # Validate name
    valid, error = validate_character_name(name)
    if not valid:
        return HTMLResponse(f'<div class="error">{error}</div>')

    # Check name availability
    if await store.character_name_exists(name):
        return HTMLResponse('<div class="error">That name is already taken</div>')

    # Validate race and class (basic check)
    valid_races = {r["id"] for r in RACES}
    valid_classes = {c["id"] for c in CLASSES}

    if race_id not in valid_races:
        return HTMLResponse('<div class="error">Invalid race</div>')
    if class_id not in valid_classes:
        return HTMLResponse('<div class="error">Invalid class</div>')

    # Create character with starting stats
    starting_stats = _get_starting_stats(race_id, class_id)

    try:
        character = await store.create_character(
            account_id=token_data.account_id,
            name=name,
            race_id=race_id,
            class_id=class_id,
            starting_stats=starting_stats,
        )
    except ValueError as e:
        return HTMLResponse(f'<div class="error">{str(e)}</div>')

    return HTMLResponse(
        f'<script>window.location.href="/characters"</script>'
    )


def _get_starting_stats(race_id: str, class_id: str) -> dict:
    """Calculate starting stats based on race and class."""
    # Base stats
    stats = {
        "strength": 10,
        "dexterity": 10,
        "constitution": 10,
        "intelligence": 10,
        "wisdom": 10,
        "charisma": 10,
        "hp": 20,
        "max_hp": 20,
        "mana": 10,
        "max_mana": 10,
        "stamina": 100,
        "max_stamina": 100,
    }

    # Race modifiers
    race_mods = {
        "human": {},  # Balanced
        "elf": {"dexterity": 2, "intelligence": 2, "constitution": -2},
        "dwarf": {"constitution": 2, "strength": 1, "charisma": -1},
        "halfling": {"dexterity": 2, "charisma": 1, "strength": -2},
        "orc": {"strength": 3, "constitution": 1, "intelligence": -2, "charisma": -1},
    }

    # Class modifiers
    class_mods = {
        "warrior": {"strength": 2, "constitution": 2, "hp": 10, "max_hp": 10},
        "mage": {"intelligence": 3, "wisdom": 1, "mana": 20, "max_mana": 20, "hp": -5, "max_hp": -5},
        "cleric": {"wisdom": 2, "constitution": 1, "mana": 15, "max_mana": 15},
        "rogue": {"dexterity": 3, "charisma": 1},
        "ranger": {"dexterity": 2, "wisdom": 1, "constitution": 1},
    }

    # Apply modifiers
    for stat, mod in race_mods.get(race_id, {}).items():
        stats[stat] = stats.get(stat, 0) + mod

    for stat, mod in class_mods.get(class_id, {}).items():
        stats[stat] = stats.get(stat, 0) + mod

    # Ensure minimums
    stats["hp"] = max(stats["hp"], 10)
    stats["max_hp"] = max(stats["max_hp"], 10)
    stats["mana"] = max(stats["mana"], 0)
    stats["max_mana"] = max(stats["max_mana"], 0)

    return stats

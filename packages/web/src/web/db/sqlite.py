"""SQLite implementation of PlayerStore for local development."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import aiosqlite
import bcrypt

from .protocol import PlayerAccount, PlayerCharacter


class SQLitePlayerStore:
    """
    SQLite implementation of PlayerStore.

    Used for local development and single-server deployments.
    """

    def __init__(self, db_path: Path = Path("data/players.db")):
        self.db_path = db_path
        self._initialized = False

    async def initialize(self) -> None:
        """Create tables if they don't exist."""
        if self._initialized:
            return

        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript('''
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    is_admin BOOLEAN DEFAULT 0,
                    settings TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS characters (
                    character_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    name TEXT UNIQUE NOT NULL COLLATE NOCASE,
                    race_id TEXT NOT NULL,
                    class_id TEXT NOT NULL,
                    level INTEGER DEFAULT 1,
                    experience INTEGER DEFAULT 0,
                    gold INTEGER DEFAULT 0,
                    stats TEXT DEFAULT '{}',
                    inventory TEXT DEFAULT '[]',
                    equipment TEXT DEFAULT '{}',
                    location_id TEXT DEFAULT 'ravenmoor_square',
                    quest_log TEXT DEFAULT '{}',
                    preferences TEXT DEFAULT '{}',
                    skills TEXT DEFAULT '{}',
                    cooldowns TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_played TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    is_deleted BOOLEAN DEFAULT 0,
                    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
                );

                CREATE TABLE IF NOT EXISTS online_characters (
                    character_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (character_id) REFERENCES characters(character_id)
                );

                CREATE INDEX IF NOT EXISTS idx_accounts_email
                    ON accounts(email);
                CREATE INDEX IF NOT EXISTS idx_characters_account
                    ON characters(account_id);
                CREATE INDEX IF NOT EXISTS idx_characters_name
                    ON characters(name);
            ''')
            await db.commit()

        self._initialized = True

    def _hash_password(self, password: str) -> str:
        """Hash a password using bcrypt."""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify a password against its hash."""
        return bcrypt.checkpw(
            password.encode('utf-8'),
            password_hash.encode('utf-8')
        )

    def _row_to_account(self, row: aiosqlite.Row) -> PlayerAccount:
        """Convert a database row to PlayerAccount."""
        return PlayerAccount(
            account_id=row['account_id'],
            email=row['email'],
            password_hash=row['password_hash'],
            created_at=datetime.fromisoformat(row['created_at'])
                if row['created_at'] else datetime.utcnow(),
            last_login=datetime.fromisoformat(row['last_login'])
                if row['last_login'] else None,
            is_active=bool(row['is_active']),
            is_admin=bool(row['is_admin']),
            settings=json.loads(row['settings'] or '{}'),
        )

    def _row_to_character(self, row: aiosqlite.Row) -> PlayerCharacter:
        """Convert a database row to PlayerCharacter."""
        cooldowns_raw = json.loads(row['cooldowns'] or '{}')
        cooldowns = {
            k: datetime.fromisoformat(v) for k, v in cooldowns_raw.items()
        }

        return PlayerCharacter(
            character_id=row['character_id'],
            account_id=row['account_id'],
            name=row['name'],
            race_id=row['race_id'],
            class_id=row['class_id'],
            level=row['level'],
            experience=row['experience'],
            gold=row['gold'],
            stats=json.loads(row['stats'] or '{}'),
            inventory=json.loads(row['inventory'] or '[]'),
            equipment=json.loads(row['equipment'] or '{}'),
            location_id=row['location_id'],
            quest_log=json.loads(row['quest_log'] or '{}'),
            preferences=json.loads(row['preferences'] or '{}'),
            skills=json.loads(row['skills'] or '{}'),
            cooldowns=cooldowns,
            created_at=datetime.fromisoformat(row['created_at'])
                if row['created_at'] else datetime.utcnow(),
            last_played=datetime.fromisoformat(row['last_played'])
                if row['last_played'] else None,
            is_active=bool(row['is_active']),
            is_deleted=bool(row['is_deleted']),
        )

    # Account operations

    async def create_account(self, email: str, password: str) -> PlayerAccount:
        """Create a new account with hashed password."""
        await self.initialize()

        account_id = str(uuid.uuid4())
        password_hash = self._hash_password(password)
        now = datetime.utcnow()

        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    '''
                    INSERT INTO accounts (account_id, email, password_hash, created_at)
                    VALUES (?, ?, ?, ?)
                    ''',
                    (account_id, email.lower(), password_hash, now.isoformat())
                )
                await db.commit()
            except aiosqlite.IntegrityError:
                raise ValueError(f"Email already registered: {email}")

        return PlayerAccount(
            account_id=account_id,
            email=email.lower(),
            password_hash=password_hash,
            created_at=now,
        )

    async def get_account(self, account_id: str) -> Optional[PlayerAccount]:
        """Get account by ID."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM accounts WHERE account_id = ?',
                (account_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return self._row_to_account(row) if row else None

    async def get_account_by_email(self, email: str) -> Optional[PlayerAccount]:
        """Look up account by email."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM accounts WHERE email = ? COLLATE NOCASE',
                (email.lower(),)
            ) as cursor:
                row = await cursor.fetchone()
                return self._row_to_account(row) if row else None

    async def verify_password(
        self, email: str, password: str
    ) -> Optional[PlayerAccount]:
        """Verify credentials and return account if valid."""
        account = await self.get_account_by_email(email)
        if not account:
            return None

        if not account.is_active:
            return None

        if self._verify_password(password, account.password_hash):
            return account

        return None

    async def update_account(self, account: PlayerAccount) -> None:
        """Update account data."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                '''
                UPDATE accounts SET
                    email = ?,
                    is_active = ?,
                    is_admin = ?,
                    settings = ?
                WHERE account_id = ?
                ''',
                (
                    account.email,
                    account.is_active,
                    account.is_admin,
                    json.dumps(account.settings),
                    account.account_id,
                )
            )
            await db.commit()

    async def update_last_login(self, account_id: str) -> None:
        """Update the last login timestamp."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE accounts SET last_login = ? WHERE account_id = ?',
                (datetime.utcnow().isoformat(), account_id)
            )
            await db.commit()

    # Character operations

    async def create_character(
        self,
        account_id: str,
        name: str,
        race_id: str,
        class_id: str,
        starting_stats: Optional[Dict[str, Any]] = None,
        starting_location: str = "ravenmoor_square",
    ) -> PlayerCharacter:
        """Create a new character for an account."""
        await self.initialize()

        character_id = str(uuid.uuid4())
        now = datetime.utcnow()
        stats = starting_stats or {}

        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    '''
                    INSERT INTO characters (
                        character_id, account_id, name, race_id, class_id,
                        stats, location_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        character_id, account_id, name, race_id, class_id,
                        json.dumps(stats), starting_location, now.isoformat()
                    )
                )
                await db.commit()
            except aiosqlite.IntegrityError:
                raise ValueError(f"Character name already taken: {name}")

        return PlayerCharacter(
            character_id=character_id,
            account_id=account_id,
            name=name,
            race_id=race_id,
            class_id=class_id,
            stats=stats,
            location_id=starting_location,
            created_at=now,
        )

    async def get_character(self, character_id: str) -> Optional[PlayerCharacter]:
        """Get a character by ID."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM characters WHERE character_id = ? AND is_deleted = 0',
                (character_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return self._row_to_character(row) if row else None

    async def get_character_by_name(self, name: str) -> Optional[PlayerCharacter]:
        """Get a character by name (case-insensitive)."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM characters WHERE name = ? COLLATE NOCASE AND is_deleted = 0',
                (name,)
            ) as cursor:
                row = await cursor.fetchone()
                return self._row_to_character(row) if row else None

    async def get_characters(self, account_id: str) -> List[PlayerCharacter]:
        """Get all characters for an account."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                '''
                SELECT * FROM characters
                WHERE account_id = ? AND is_deleted = 0
                ORDER BY last_played DESC NULLS LAST, created_at DESC
                ''',
                (account_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_character(row) for row in rows]

    async def save_character(self, character: PlayerCharacter) -> None:
        """Save character state."""
        await self.initialize()

        # Convert cooldowns to ISO format strings
        cooldowns = {
            k: v.isoformat() for k, v in character.cooldowns.items()
        }

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                '''
                UPDATE characters SET
                    level = ?,
                    experience = ?,
                    gold = ?,
                    stats = ?,
                    inventory = ?,
                    equipment = ?,
                    location_id = ?,
                    quest_log = ?,
                    preferences = ?,
                    skills = ?,
                    cooldowns = ?,
                    last_played = ?,
                    is_active = ?
                WHERE character_id = ?
                ''',
                (
                    character.level,
                    character.experience,
                    character.gold,
                    json.dumps(character.stats),
                    json.dumps(character.inventory),
                    json.dumps(character.equipment),
                    character.location_id,
                    json.dumps(character.quest_log),
                    json.dumps(character.preferences),
                    json.dumps(character.skills),
                    json.dumps(cooldowns),
                    datetime.utcnow().isoformat(),
                    character.is_active,
                    character.character_id,
                )
            )
            await db.commit()

    async def delete_character(self, character_id: str, soft: bool = True) -> bool:
        """Delete a character."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            if soft:
                result = await db.execute(
                    'UPDATE characters SET is_deleted = 1 WHERE character_id = ?',
                    (character_id,)
                )
            else:
                result = await db.execute(
                    'DELETE FROM characters WHERE character_id = ?',
                    (character_id,)
                )
            await db.commit()
            return result.rowcount > 0

    async def character_name_exists(self, name: str) -> bool:
        """Check if character name is taken."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT 1 FROM characters WHERE name = ? COLLATE NOCASE AND is_deleted = 0',
                (name,)
            ) as cursor:
                return await cursor.fetchone() is not None

    # Session/online tracking

    async def set_character_online(
        self, character_id: str, session_id: str
    ) -> None:
        """Mark character as online with session."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                '''
                INSERT OR REPLACE INTO online_characters (character_id, session_id, connected_at)
                VALUES (?, ?, ?)
                ''',
                (character_id, session_id, datetime.utcnow().isoformat())
            )
            await db.commit()

    async def set_character_offline(self, character_id: str) -> None:
        """Mark character as offline."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'DELETE FROM online_characters WHERE character_id = ?',
                (character_id,)
            )
            await db.commit()

    async def get_online_characters(self) -> List[str]:
        """Get list of online character IDs."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT character_id FROM online_characters'
            ) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

    async def is_character_online(self, character_id: str) -> bool:
        """Check if character is currently online."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT 1 FROM online_characters WHERE character_id = ?',
                (character_id,)
            ) as cursor:
                return await cursor.fetchone() is not None

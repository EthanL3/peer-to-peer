import aiosqlite

DB_FILE = "messages.db"

CREATE_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_partner TEXT,
    direction TEXT CHECK(direction IN ('sent', 'received')),
    message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_UNSENT_TABLE = """
CREATE TABLE IF NOT EXISTS unsent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    peer TEXT,
    message TEXT
);
"""

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(CREATE_MESSAGES_TABLE)
        await db.execute(CREATE_UNSENT_TABLE)
        await db.commit()

async def save_message(chat_partner, direction, message):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO messages (chat_partner, direction, message) VALUES (?, ?, ?)",
            (chat_partner, direction, message)
        )
        await db.commit()

async def save_unsent(peer, message):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT INTO unsent_messages (peer, message) VALUES (?, ?)", (peer, message))
        await db.commit()

async def get_unsent(peer):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT id, message FROM unsent_messages WHERE peer = ?", (peer,)) as cursor:
            return await cursor.fetchall()

async def delete_unsent(msg_id):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM unsent_messages WHERE id = ?", (msg_id,))
        await db.commit()
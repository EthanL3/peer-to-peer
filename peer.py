import asyncio
import aiosqlite
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from base64 import b64encode, b64decode
import hashlib

connections = {}  # writer -> (ip, listening_port)
connected_peers = set()  # Track established peer addresses
peer_keys = {}  # peer_id -> AES key (in-memory for simplicity)
peer_usernames = {}  # peer_id -> username
my_username = ""

# --- SQLite Setup ---
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

# --- Encryption Helpers ---
def generate_shared_key(ip1, port1, ip2, port2):
    # Deterministic, symmetric key derivation using sorted endpoints
    endpoints = sorted([f"{ip1}:{port1}", f"{ip2}:{port2}"])
    shared_secret = "supersecurepassword"
    raw = (endpoints[0] + endpoints[1] + shared_secret).encode()
    return hashlib.sha256(raw).digest()[:16]  # AES-128

def encrypt(key, plaintext):
    cipher = AES.new(key, AES.MODE_EAX)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode())
    return b64encode(cipher.nonce + tag + ciphertext).decode()

def decrypt(key, encoded):
    raw = b64decode(encoded)
    nonce, tag, ciphertext = raw[:16], raw[16:32], raw[32:]
    cipher = AES.new(key, AES.MODE_EAX, nonce)
    return cipher.decrypt_and_verify(ciphertext, tag).decode()

# --- Networking ---
async def handle_peer(reader, writer):
    addr = writer.get_extra_info('peername')

    # Expect handshake
    intro = await reader.readline()
    try:
        intro_msg = intro.decode().strip()
        parts = intro_msg.split()
        if parts[0] == "HELLO" and len(parts) >= 3:
            peer_listen_port = int(parts[1])
            peer_username = " ".join(parts[2:])
        else:
            raise ValueError("Invalid handshake")
    except Exception as e:
        print(f"[ERROR] Bad handshake from {addr}: {e}")
        writer.close()
        await writer.wait_closed()
        return

    ip = addr[0]
    peer_id = f"{ip}:{peer_listen_port}"
    peer_usernames[peer_id] = peer_username

    if peer_id in connected_peers:
        writer.close()
        await writer.wait_closed()
        return

    connected_peers.add(peer_id)
    connections[writer] = (ip, peer_listen_port)
    print(f"[CONNECTED] {ip}:{peer_listen_port}")

    # Generate key if needed
    my_port = writer.get_extra_info('sockname')[1]
    if peer_id not in peer_keys:
        peer_keys[peer_id] = generate_shared_key(ip, peer_listen_port, "127.0.0.1", my_port)

    # Send back HELLO with our own listening port
    my_port = writer.get_extra_info('sockname')[1]
    writer.write(f"HELLO {my_port} {my_username}\n".encode())
    await writer.drain()

    # Send unsent messages
    unsent = await get_unsent(peer_id)
    for msg_id, raw_msg in unsent:
        encrypted = encrypt(peer_keys[peer_id], raw_msg)
        writer.write((encrypted + '\n').encode())
        await writer.drain()
        await save_message(peer_id, "sent", encrypted)
        await delete_unsent(msg_id)

    try:
        while True:
            data = await reader.readline()
            if not data:
                break
            message = data.decode().strip()
            key = peer_keys.get(peer_id)
            if key:
                try:
                    decrypted = decrypt(key, message)
                    if decrypted == "__EXIT__":
                        print(f"[INFO] Peer {peer_id} left the chat. Closing.")
                        break
                    display_name = peer_usernames.get(peer_id, f"{ip}:{peer_listen_port}")
                    print(f"({display_name}): {decrypted}")

                    await save_message(peer_id, "received", message)
                except Exception as e:
                    print(f"[ERROR] Decryption failed: {e}")
            else:
                print(f"Received from unknown key peer {peer_id}: {message}")
    finally:
        print(f"[DISCONNECTED] {ip}:{peer_listen_port}")
        writer.close()
        await writer.wait_closed()
        del connections[writer]
        connected_peers.discard(peer_id)

async def start_server(port):
    server = await asyncio.start_server(handle_peer, '0.0.0.0', port)
    print(f"[LISTENING] on port {port}")
    async with server:
        await server.serve_forever()

async def connect_to_peer(ip, port, my_listen_port):
    peer_id = f"{ip}:{port}"
    if peer_id in connected_peers:
        print(f"[INFO] Already connected to {peer_id}")
        return
    try:
        reader, writer = await asyncio.open_connection(ip, port)

        # Send your HELLO (port + username)
        writer.write(f"HELLO {my_listen_port} {my_username}\n".encode())
        await writer.drain()

        # Wait for their HELLO (port + username)
        intro = await reader.readline()
        intro_msg = intro.decode().strip()
        parts = intro_msg.split()
        if parts[0] == "HELLO" and len(parts) >= 3:
            peer_listen_port = int(parts[1])
            peer_username = " ".join(parts[2:])
            peer_id = f"{ip}:{peer_listen_port}"
            peer_usernames[peer_id] = peer_username
        else:
            raise ValueError("Invalid handshake received")

        # Save connection
        connections[writer] = (ip, peer_listen_port)
        connected_peers.add(peer_id)

        # Generate shared encryption key
        if peer_id not in peer_keys:
            peer_keys[peer_id] = generate_shared_key(ip, port, "127.0.0.1", my_listen_port)

        print(f"[CONNECTED] {peer_username} ({ip}:{peer_listen_port})")
        view_history = input("Would you like to view chat history with this peer? (y/n): ").strip().lower()
        if view_history == 'y':
            await show_chat_history(peer_id)
        
        asyncio.create_task(read_messages(reader, writer, peer_id))

        # Send any unsent messages
        unsent = await get_unsent(peer_id)
        for msg_id, raw_msg in unsent:
            encrypted = encrypt(peer_keys[peer_id], raw_msg)
            writer.write((encrypted + '\n').encode())
            await writer.drain()
            await save_message(peer_id, "sent", encrypted)
            await delete_unsent(msg_id)

    except Exception as e:
        print(f"[ERROR] Could not connect to {ip}:{port}: {e}")

async def read_messages(reader, writer, peer_id):
    ip, peer_listen_port = connections.get(writer, ("unknown", 0))
    try:
        while True:
            data = await reader.readline()
            if not data:
                break
            message = data.decode().strip()
            key = peer_keys.get(peer_id)
            if key:
                try:
                    decrypted = decrypt(key, message)
                    if decrypted == "__EXIT__":
                        print(f"[INFO] Peer {peer_id} left the chat.")
                        break
                    display_name = peer_usernames.get(peer_id, f"{ip}:{peer_listen_port}")
                    print(f"({display_name}): {decrypted}")

                    await save_message(peer_id, "received", message)
                except Exception as e:
                    print(f"[ERROR] Decryption failed: {e}")
            else:
                print(f"Received from unknown key peer {peer_id}: {message}")
    finally:
        writer.close()
        await writer.wait_closed()
        if writer in connections:
            del connections[writer]
        connected_peers.discard(peer_id)

async def message_loop(my_listen_port):
    loop = asyncio.get_event_loop()
    while True:
        msg = await loop.run_in_executor(None, input, "")
        if msg.startswith("connect"):
            try:
                _, ip, port = msg.split()
                await connect_to_peer(ip, int(port), my_listen_port)
            except:
                print("Usage: connect <ip> <port>")
        elif msg.lower() == "exit":
            for writer in list(connections.keys()):
                ip, port = connections[writer]
                peer_id = f"{ip}:{port}"
                key = peer_keys.get(peer_id)
                if key:
                    exit_msg = encrypt(key, "__EXIT__")
                    writer.write((exit_msg + '\n').encode())
                    await writer.drain()
                writer.close()
                await writer.wait_closed()
                print(f"[INFO] Disconnected from {peer_id}")
            connections.clear()
            connected_peers.clear()
            print("[INFO] Left the chat. You can connect to a new peer.")
        elif msg.lower() == "quit":
            print("Quitting program...")
            for writer in list(connections.keys()):
                ip, port = connections[writer]
                peer_id = f"{ip}:{port}"
                key = peer_keys.get(peer_id)
                if key:
                    exit_msg = encrypt(key, "__EXIT__")
                    writer.write((exit_msg + '\n').encode())
                    await writer.drain()
                writer.close()
                await writer.wait_closed()
            connections.clear()
            connected_peers.clear()
            await asyncio.sleep(0.5)  # brief pause to let sockets close
            exit(0)
        else:
            for writer in list(connections.keys()):
                ip, port = connections[writer]
                peer_id = f"{ip}:{port}"
                key = peer_keys.get(peer_id)
                if key:
                    encrypted = encrypt(key, msg)
                    writer.write((encrypted + '\n').encode())
                    await writer.drain()
                    await save_message(peer_id, "sent", encrypted)
                else:
                    await save_unsent(peer_id, msg)
            if connections:  # Only print if there were active connections
                print(f"(you): {msg}")

async def show_chat_history(peer_id):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("""
            SELECT direction, message, timestamp FROM messages
            WHERE chat_partner = ?
            ORDER BY timestamp ASC
        """, (peer_id,)) as cursor:
            rows = await cursor.fetchall()
            if not rows:
                print("[INFO] No message history with this peer.")
                return
            print(f"\n📜 Chat history with {peer_usernames.get(peer_id, peer_id)}:")
            for direction, encrypted_message, timestamp in rows:
                key = peer_keys.get(peer_id)
                if not key:
                    print(f"[WARNING] No key to decrypt message with {peer_id}")
                    continue
                try:
                    decrypted_message = decrypt(key, encrypted_message)
                except Exception as e:
                    decrypted_message = "[Could not decrypt message]"
                label = "you" if direction == "sent" else peer_usernames.get(peer_id, peer_id)
                print(f"[{timestamp}] ({label}): {decrypted_message}")
            print()

async def main():
    global my_username
    await init_db()
    my_port = int(input("Enter your listening port: "))
    my_username = input("Enter your username: ").strip()
    asyncio.create_task(start_server(my_port))
    await message_loop(my_port)

if __name__ == "__main__":
    asyncio.run(main())
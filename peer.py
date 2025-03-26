import asyncio
import aiosqlite
from datetime import datetime

connections = {}  # writer -> (ip, listening_port)
connected_peers = set()  # Track established peer addresses

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

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(CREATE_MESSAGES_TABLE)
        await db.commit()

async def save_message(chat_partner, direction, message):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO messages (chat_partner, direction, message) VALUES (?, ?, ?)",
            (chat_partner, direction, message)
        )
        await db.commit()

# --- Networking ---
async def handle_peer(reader, writer):
    addr = writer.get_extra_info('peername')

    # Expect handshake
    intro = await reader.readline()
    try:
        intro_msg = intro.decode().strip()
        if intro_msg.startswith("HELLO"):
            peer_listen_port = int(intro_msg.split()[1])
        else:
            raise ValueError("Invalid handshake")
    except Exception as e:
        print(f"[ERROR] Bad handshake from {addr}: {e}")
        writer.close()
        await writer.wait_closed()
        return

    ip = addr[0]
    peer_id = f"{ip}:{peer_listen_port}"

    if peer_id in connected_peers:
        writer.close()
        await writer.wait_closed()
        return

    connected_peers.add(peer_id)
    connections[writer] = (ip, peer_listen_port)
    print(f"[CONNECTED] {ip}:{peer_listen_port}")

    # Send back HELLO with our own listening port
    my_port = writer.get_extra_info('sockname')[1]
    writer.write(f"HELLO {my_port}\n".encode())
    await writer.drain()

    try:
        while True:
            data = await reader.readline()
            if not data:
                break
            message = data.decode().strip()
            print(f"({ip}, {peer_listen_port}, {message})")
            await save_message(f"{ip}:{peer_listen_port}", "received", message)
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
        writer.write(f"HELLO {my_listen_port}\n".encode())
        await writer.drain()

        # Wait for their HELLO
        intro = await reader.readline()
        intro_msg = intro.decode().strip()
        if intro_msg.startswith("HELLO"):
            peer_listen_port = int(intro_msg.split()[1])
            connections[writer] = (ip, peer_listen_port)
            connected_peers.add(peer_id)
            print(f"[CONNECTED] {ip}:{peer_listen_port}")
            asyncio.create_task(read_messages(reader, writer, peer_id))
        else:
            raise ValueError("Invalid handshake")
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
            print(f"({ip}:{peer_listen_port}): {message}")
            await save_message(f"{ip}:{peer_listen_port}", "received", message)
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
                writer.close()
                await writer.wait_closed()
            print("Exiting...")
            break
        else:
            for writer in list(connections.keys()):
                writer.write((msg + '\n').encode())
                await writer.drain()
                ip, port = connections[writer]
                await save_message(f"{ip}:{port}", "sent", msg)

async def main():
    await init_db()
    my_port = int(input("Enter your listening port: "))
    asyncio.create_task(start_server(my_port))
    await message_loop(my_port)

if __name__ == "__main__":
    asyncio.run(main())
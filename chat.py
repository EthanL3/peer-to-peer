from db import save_message, save_unsent, DB_FILE
from config import connections, connected_peers, peer_keys, peer_usernames
from crypto import encrypt, decrypt
import asyncio
import aiosqlite

async def message_loop(my_listen_port, connect_to_peer_func):
    loop = asyncio.get_event_loop()
    while True:
        msg = await loop.run_in_executor(None, input, "")
        if msg.startswith("connect"):
            try:
                _, ip, port = msg.split()
                await connect_to_peer_func(ip, int(port), my_listen_port)
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
    from db import get_unsent, delete_unsent
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
                except Exception:
                    decrypted_message = "[Could not decrypt message]"
                label = "you" if direction == "sent" else peer_usernames.get(peer_id, peer_id)
                print(f"[{timestamp}] ({label}): {decrypted_message}")
            print()
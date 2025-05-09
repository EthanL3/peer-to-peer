import asyncio
from db import save_message, save_unsent, get_unsent, delete_unsent
from crypto import encrypt, decrypt, generate_shared_key
from chat import show_chat_history
from config import connections, connected_peers, peer_keys, peer_usernames, my_username

async def handle_peer(reader, writer):
    addr = writer.get_extra_info('peername')

    # Expect handshake
    intro = await reader.readline()
    if not intro:
        print(f"[ERROR] Empty handshake from {addr}, closing connection.")
        writer.close()
        await writer.wait_closed()
        return

    try:
        intro_msg = intro.decode().strip()
        parts = intro_msg.split()
        if parts[0] == "HELLO" and len(parts) >= 3:
            peer_listen_port = int(parts[1])
            peer_username = " ".join(parts[2:])
        else:
            raise ValueError("Invalid handshake format")
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

async def start_server(port):
    server = await asyncio.start_server(handle_peer, '0.0.0.0', port)
    print(f"[LISTENING] on port {port}")
    async with server:
        await server.serve_forever()

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
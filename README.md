# P2P Chat System with SQLite

This project is a peer-to-peer (P2P) chat application written in Python using `asyncio` for networking and `aiosqlite` for secure, local message storage.

Each peer runs as both a server (listens for connections) and a client (can connect to other peers). All messages are stored locally in an encrypted SQLite database. There is no central server.

---

## Features

- 🔄 Full duplex P2P communication
- 📥 Store **both sent and received messages**
- 🔐 Local SQLite database using `aiosqlite`
- 🧠 Handshake protocol to identify peer's listening port
- 🔁 Avoid duplicate connections with peer tracking

---

## How It Works

1. Each peer starts by listening on a given port.
2. Peers connect to each other using the `connect <ip> <port>` command.
3. Upon connection, peers exchange a `HELLO <port>` handshake.
4. Messages typed into the console are sent to all connected peers.
5. Messages are printed on screen and saved to the local database.

---

## Requirements

- Python 3.7+
- `aiosqlite`

Install dependencies:
```bash
pip install -r requirements.txt
```

---

## Usage

Run two instances of the script in separate terminals:

### Peer 1
```bash
python peer.py
Enter your listening port: 5001
```

### Peer 2
```bash
python peer.py
Enter your listening port: 5002
```

Then from either:
```bash
connect 127.0.0.1 5002
```
And send messages!

---

## Commands

- `connect <ip> <port>`: Connect to a peer.
- `exit`: Gracefully close connections and exit.

---

## Database Schema

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_partner TEXT,
    direction TEXT CHECK(direction IN ('sent', 'received')),
    message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
```
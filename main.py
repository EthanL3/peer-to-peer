import asyncio
from db import init_db
from network import start_server, connect_to_peer
from chat import message_loop
import config

async def main():
    await init_db()
    my_port = int(input("Enter your listening port: "))
    config.my_username = input("Enter your username: ").strip()
    asyncio.create_task(start_server(my_port))
    await message_loop(my_port, connect_to_peer)

if __name__ == "__main__":
    asyncio.run(main())
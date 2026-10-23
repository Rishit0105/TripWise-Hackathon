import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    url = "http://127.0.0.1:8001/mcp"

    async with streamablehttp_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()

            print("\nMCP CONNECTION SUCCESSFUL")
            print("Available TripWise tools:")

            for tool in result.tools:
                print(f"- {tool.name}: {tool.description}")

if __name__ == "__main__":
    asyncio.run(main())

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    url = "http://127.0.0.1:8001/mcp"

    print(f"Connecting to {url}...")

    async with streamablehttp_client(url) as (
        read_stream,
        write_stream,
        get_session_id,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            result = await session.initialize()

            print("\nMCP connection initialized.")
            print("Server:", result.serverInfo.name)
            print("Protocol version:", result.protocolVersion)

            response = await session.list_tools()

            print("\nAvailable TripWise tools:")
            for tool in response.tools:
                print(f"- {tool.name}: {tool.description}")

            print(f"\nTotal tools discovered: {len(response.tools)}")


if __name__ == "__main__":
    asyncio.run(main())

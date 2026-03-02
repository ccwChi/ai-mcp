import asyncio
import os
import sys
from importlib import import_module
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# We want to connect to our own MCP server.
# The server is run via `python -m ai_mcp.server`, so we use the same command structure.
server_parameters = StdioServerParameters(
    command="python",
    args=["-m", "ai_mcp.server"],
    env=None,  # Uses the current environment variables, so it can see .env changes
)


async def chat_loop(session: ClientSession):
    """
    A simple REPL (Read-Eval-Print Loop) to interact with the AI tools.
    """
    print("\n" + "=" * 50)
    print("Welcome to your local AI terminal!")
    print("This terminal will process your questions and automatically use:")
    print("  1. Gemini 2.5 Pro (If it's about LeetCode/Algorithms)")
    print("  2. Local Ollama (For everything else)")
    print("Type 'exit' or 'quit' to close.")
    print("=" * 50 + "\n")

    while True:
        try:
            # Read user input
            user_input = input("\nYou: ").strip()

            if user_input.lower() in ["exit", "quit"]:
                print("Goodbye!")
                break

            if not user_input:
                continue

            print("Thinking...")

            # We call the 'ask_ai' tool that we defined in server.py
            # Since MCP handles tool execution on the server side, we just ask the server to run the tool.
            result = await session.call_tool("ask_ai", arguments={"prompt": user_input})

            # The result from a tool call is typically a list of content blocks.
            # In our simple server setup, we return text, so we assume the first block is TextContent.
            if result.content and len(result.content) > 0:
                # The text is stored in the 'text' attribute of the TextContent block
                print(f"\nAI: {result.content[0].text}")
            else:
                print("\nAI: (No response returned)")

        except KeyboardInterrupt:
            # Allow user to use Ctrl+C to exit gracefully
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\n[Error] {e}")


async def main():
    """
    Connects to the local MCP server over standard I/O streams and starts the chat loop.
    """
    # Use an AsyncExitStack so we can easily clean up context managers even on exceptions
    async with AsyncExitStack() as stack:
        print("Starting local MCP client, please wait...")

        try:
            # Start the subprocess running the MCP server
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(server_parameters)
            )

            # Create an MCP session over those streams
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )

            # Initialize the connection (runs the MCP handshake)
            await session.initialize()

            # We are connected! Start interacting.
            await chat_loop(session)

        except Exception as e:
            print(f"Failed to connect or talk to the local MCP server: {e}")
            sys.exit(1)


if __name__ == "__main__":
    # We must run the async main function in an asyncio event loop
    asyncio.run(main())

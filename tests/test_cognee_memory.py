import asyncio
import os
import sys

# Add project root to path
script_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(script_dir)
sys.path.insert(0, root_dir)

from openalgo.utils.memory_utils import CogneeManager


async def test_cognee():
    print("Initializing Cognee Manager...")
    manager = CogneeManager()

    if not manager.enabled:
        print("Cognee is not enabled (library missing). Skipping test.")
        return

    print("Adding a memory...")
    await manager.add_memory("I bought NIFTY at 22000 because RSI was 25 (Oversold).")

    print("Searching memory...")
    results = await manager.search_memory("NIFTY RSI")
    print(f"Search Results: {results}")

    print("Getting context...")
    context = await manager.get_trading_context("NIFTY", {"RSI": 28})
    print(f"Context: {context}")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(test_cognee())

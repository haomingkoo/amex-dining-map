#!/usr/bin/env python3
"""
Extract AMEX restaurants using browser-use (simplified, no langchain conflicts).
"""

import asyncio
import json
import re
import sys
from pathlib import Path

# Use anthropic client directly, avoid langchain version conflicts
try:
    from browser_use import Agent
    from anthropic import Anthropic
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Installing dependencies...")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "browser-use", "anthropic", "-q"])
    from browser_use import Agent
    from anthropic import Anthropic

DATA_DIR = Path(__file__).parent.parent / "data"
REBUILT_DIR = DATA_DIR / "rebuilt"
REBUILT_DIR.mkdir(exist_ok=True)


async def extract_with_browser_use():
    """Extract using browser-use with direct Anthropic client."""
    print("\n" + "="*80)
    print("PHASE 2: Extract AMEX Global Dining with Browser-Use")
    print("="*80)
    print("Let Claude control the browser autonomously...\n")

    try:
        # Initialize agent with minimal dependencies
        agent = Agent(
            task="""
            1. Go to https://www.americanexpress.com/en-sg/benefits/platinum/dining/
            2. Wait for page to load
            3. Look for restaurant listings or cards
            4. Extract restaurant information: name, address, cuisine, location/city
            5. If there's a country selector or filter, try to access multiple countries
            6. Extract as many restaurants as possible
            7. Return ALL data as a single JSON array with fields: name, address, cuisine, city, country
            8. Do NOT include any text outside the JSON array
            """,
            llm_model="claude-3-5-sonnet-20241022",
            max_actions=200,
            use_vision=True,
            # Disable langchain dependency
            skip_verbose=True,
        )

        print("🚀 Browser automation started...\n")
        result = await agent.run()

        print(f"\n📝 Result received\n")
        print(f"Raw output (first 500 chars):\n{str(result)[:500]}\n")

        # Try to extract JSON
        json_match = re.search(r'\[.*\]', str(result), re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            restaurants = json.loads(json_str)

            # Save results
            output_file = REBUILT_DIR / "global-restaurants-REBUILT.json"
            with open(output_file, "w") as f:
                json.dump(restaurants, f, indent=2)

            print(f"✅ Extracted {len(restaurants)} restaurants")
            print(f"💾 Saved to: {output_file}\n")

            # Show samples
            if restaurants:
                print("📍 Sample restaurants:")
                for r in restaurants[:5]:
                    print(f"  - {r.get('name')} ({r.get('city')}, {r.get('country')})")
                    if r.get('address'):
                        print(f"    {r.get('address')}")
                print()

            return restaurants
        else:
            print("⚠️ No JSON array found in response")
            print(f"Full output:\n{result}")
            return None

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    restaurants = await extract_with_browser_use()

    if restaurants:
        print("="*80)
        print("✅ EXTRACTION SUCCESSFUL")
        print("="*80)
        print(f"Total: {len(restaurants)} restaurants")
        print(f"File: data/rebuilt/global-restaurants-REBUILT.json")
        return True
    else:
        print("="*80)
        print("❌ EXTRACTION FAILED")
        print("="*80)
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

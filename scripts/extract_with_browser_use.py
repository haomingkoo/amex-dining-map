#!/usr/bin/env python3
"""
Use browser-use to extract AMEX Global Dining data.

Browser-use lets Claude control a browser intelligently to extract data
without needing exact CSS selectors.

Usage:
  python3 scripts/extract_with_browser_use.py
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

from browser_use import Agent
from langchain_anthropic import ChatAnthropic

DATA_DIR = Path(__file__).parent.parent / "data"
REBUILT_DIR = DATA_DIR / "rebuilt"
REBUILT_DIR.mkdir(exist_ok=True)


async def extract_amex_dining():
    """Use browser-use to extract AMEX dining data."""
    print("\n" + "="*80)
    print("PHASE 2: Extract Global Dining with Browser-Use")
    print("="*80)
    print("Using Claude to intelligently interact with AMEX page...")
    print()

    # Initialize Claude
    llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")

    # Create agent
    agent = Agent(
        task="""
        1. Go to https://www.americanexpress.com/en-sg/benefits/platinum/dining/
        2. Wait for the page to load completely
        3. Look for all restaurant listings (they appear as cards/items)
        4. For EACH restaurant, extract:
           - Restaurant name
           - City/location
           - Address
           - Cuisine type (if shown)
           - Any other relevant information
        5. If there's a country selector or filter, try different countries (Hong Kong, Japan, etc.)
        6. Extract restaurants from as many countries as possible
        7. Return all extracted data as a JSON list with fields: name, city, address, cuisine, country

        Be thorough - extract every restaurant you can find.
        Return ONLY valid JSON, no other text.
        """,
        llm=llm,
        use_vision=True,
    )

    print("🚀 Starting extraction with Claude + browser automation...\n")

    try:
        # Run agent
        result = await agent.run()

        print("\n✅ Extraction complete!")
        print(f"\nAgent response:\n{result}")

        # Parse result
        if result and isinstance(result, str):
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\[.*\]', result, re.DOTALL)
            if json_match:
                try:
                    restaurants = json.loads(json_match.group(0))
                    print(f"\n📊 Extracted {len(restaurants)} restaurants")

                    # Save results
                    output_file = REBUILT_DIR / "global-restaurants-REBUILT.json"
                    with open(output_file, "w") as f:
                        json.dump(restaurants, f, indent=2)

                    print(f"💾 Saved to: {output_file}")

                    # Print sample
                    if restaurants:
                        print(f"\n📍 Sample restaurants:")
                        for r in restaurants[:3]:
                            print(f"  - {r.get('name')} ({r.get('city')}, {r.get('country')})")
                            print(f"    {r.get('address')}")
                            print(f"    Cuisine: {r.get('cuisine')}")
                            print()

                    return restaurants

                except json.JSONDecodeError:
                    print("⚠️ Could not parse JSON from response")
                    return None
        else:
            print(f"⚠️ Unexpected response type: {type(result)}")
            return None

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    """Run extraction."""
    restaurants = await extract_amex_dining()

    if restaurants:
        print("\n" + "="*80)
        print("✅ Extraction successful!")
        print("="*80)
        print(f"Total restaurants: {len(restaurants)}")
        return True
    else:
        print("\n" + "="*80)
        print("❌ Extraction failed")
        print("="*80)
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

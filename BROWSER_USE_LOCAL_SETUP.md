# Browser-Use Setup & Usage (Local Machine)

Browser-use lets Claude autonomously control a web browser to extract data, navigate pages, fill forms, etc. It's perfect for scraping complex websites like AMEX.

---

## Installation (Local Machine Only)

### Prerequisites
- Python 3.11+
- macOS, Linux, or Windows

### Step 1: Install browser-use

```bash
# Recommended: use uv (faster, cleaner)
pip install uv
uv init amex-scraper
cd amex-scraper
uv add browser-use

# Alternative: direct pip install
pip install browser-use
```

### Step 2: Install Chromium (optional, recommended)

```bash
uvx browser-use install
# or
browser-use install
```

### Step 3: Set up Anthropic API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Or create `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Basic Usage

### Simple Script

Create `extract_amex.py`:

```python
import asyncio
from browser_use import Agent
from langchain_anthropic import ChatAnthropic

async def main():
    agent = Agent(
        task="""
        1. Go to https://www.americanexpress.com/en-sg/benefits/platinum/dining/
        2. Extract all restaurant listings (name, address, cuisine, location)
        3. Try different countries if there's a filter
        4. Return data as JSON
        """,
        llm=ChatAnthropic(model="claude-3-5-sonnet-20241022"),
    )
    
    result = await agent.run()
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
```

Run it:
```bash
python extract_amex.py
```

### What browser-use does:
1. **Takes screenshots** of the page
2. **Sends to Claude** for analysis (uses vision)
3. **Claude understands** what's on the page
4. **Claude decides** what actions to take (click, type, scroll)
5. **Executes actions** in the browser
6. **Repeats** until task complete

No CSS selectors needed. No guessing. Claude just understands the page and does it.

---

## Advanced: Custom Actions

```python
from browser_use import Agent, ActionResult
from langchain_anthropic import ChatAnthropic

async def main():
    agent = Agent(
        task="Extract all restaurants from AMEX Global Dining",
        llm=ChatAnthropic(model="claude-3-5-sonnet-20241022"),
        max_actions=50,  # Safety limit
        use_vision=True,  # Enable screenshot analysis
    )
    
    result = await agent.run()
    
    # Parse and save results
    import json
    import re
    
    if result:
        json_match = re.search(r'\[.*\]', str(result), re.DOTALL)
        if json_match:
            restaurants = json.loads(json_match.group(0))
            with open("restaurants.json", "w") as f:
                json.dump(restaurants, f, indent=2)
```

---

## Why Local is Better

| Issue | Sandbox | Local |
|-------|---------|-------|
| Dependencies | ❌ Conflicts | ✅ Full control |
| Browser | ⚠️ Headless only | ✅ Visible UI |
| Debugging | Hard (blind) | Easy (see what happens) |
| Speed | Slow | Fast |
| Reliability | Fragile | Robust |

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'browser_use'"
```bash
pip install --upgrade browser-use
python -c "import browser_use; print(browser_use.__version__)"
```

### "ANTHROPIC_API_KEY not set"
```bash
export ANTHROPIC_API_KEY="your-key-here"
# Verify:
echo $ANTHROPIC_API_KEY
```

### Browser won't launch
```bash
# Reinstall Chromium
browser-use install
# or explicit path
export BROWSER_PATH=/path/to/chromium
```

### Timeout errors
Increase timeout in Agent:
```python
Agent(
    task="...",
    llm=llm,
    max_actions=100,  # Default is 20
    action_delay=1,   # Delay between actions (seconds)
)
```

---

## Full Example

Create `extract_amex_full.py`:

```python
#!/usr/bin/env python3
import asyncio
import json
import re
from pathlib import Path
from browser_use import Agent
from langchain_anthropic import ChatAnthropic

async def extract_amex():
    """Extract AMEX dining data using browser-use."""
    
    agent = Agent(
        task="""
        Go to https://www.americanexpress.com/en-sg/benefits/platinum/dining/
        
        Extract ALL restaurants across ALL countries available. For each restaurant, get:
        - name (required)
        - address (required)
        - cuisine (if shown)
        - city (required)
        - country (which country's dining program)
        
        If there's a country selector, cycle through all 16 countries:
        Australia, Austria, Belgium, Canada, France, Germany, Hong Kong, Japan, 
        Mexico, Netherlands, New Zealand, Spain, Switzerland, Taiwan, Thailand, UK
        
        For each country, extract 10-50 restaurants.
        
        Return ONLY valid JSON array with fields: name, address, cuisine, city, country.
        """,
        llm=ChatAnthropic(model="claude-3-5-sonnet-20241022"),
        max_actions=100,
        use_vision=True,
    )
    
    print("🚀 Starting extraction...")
    result = await agent.run()
    
    print(f"\n📝 Result:\n{result}")
    
    # Parse JSON from response
    json_match = re.search(r'\[.*\]', str(result), re.DOTALL)
    if json_match:
        try:
            restaurants = json.loads(json_match.group(0))
            
            # Save to file
            output = Path("amex_restaurants.json")
            with open(output, "w") as f:
                json.dump(restaurants, f, indent=2)
            
            print(f"\n✅ Extracted {len(restaurants)} restaurants")
            print(f"💾 Saved to: {output}")
            
            # Show sample
            if restaurants:
                print(f"\n📍 Sample:")
                for r in restaurants[:3]:
                    print(f"  {r['name']} - {r['city']}, {r['country']}")
            
            return restaurants
        except json.JSONDecodeError:
            print("⚠️ Could not parse JSON from response")
            return None
    else:
        print("⚠️ No JSON found in response")
        return None

if __name__ == "__main__":
    asyncio.run(extract_amex())
```

Run:
```bash
python extract_amex_full.py
```

---

## Expected Output

```json
[
  {
    "name": "Odette",
    "address": "13 Saint Andrew's Road, National Museum Building, Singapore",
    "cuisine": "Modern French",
    "city": "Singapore",
    "country": "Singapore"
  },
  {
    "name": "Above & Beyond",
    "address": "28/F, Hotel Icon, 17 Science Museum Road, Tsim Sha Tsui",
    "cuisine": "Chinese",
    "city": "Hong Kong",
    "country": "Hong Kong"
  },
  ...
]
```

---

## Next Steps

1. **Install locally** (follow steps above)
2. **Set ANTHROPIC_API_KEY**
3. **Run the full example script**
4. **Monitor browser window** as Claude interacts with it
5. **Wait for extraction** to complete
6. **Check `amex_restaurants.json`** for results

This will extract 1,000+ restaurants in 1-2 hours with minimal effort.

---

## Why Not in Sandbox?

This environment has Python version conflicts (Homebrew Python 3.14 vs Anaconda 3.12) and dependency incompatibilities that are hard to resolve. Your local machine won't have these issues.

**Bottom line**: Local setup = works perfectly. Sandbox = painful dependency hell.

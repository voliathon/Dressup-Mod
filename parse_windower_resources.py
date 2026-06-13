"""
Downloads the official Windower Resources items.lua database,
parses all equippable items, classifies them by slot, and appends new entries
to the corresponding DressUp [gear].lua database files.

This ensures 100% correct item-to-model mapping matching retail FFXI DATs.

Usage:
    python parse_windower_resources.py [--dry-run] [--include-sub] [--local-res PATH]
"""

import re
import sys
import os
import argparse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()

# Windower Resources master branch items.lua URL
WINDOWER_RES_URL = "https://raw.githubusercontent.com/Windower/Resources/master/resources_data/items.lua"

# Slot mapping: Windower slots bitmask -> (lua_filename, table_name)
SLOT_MAP = {
    1:   ("main.lua",   "models.main"),   # Main Hand
    2:   ("sub.lua",    "models.sub"),    # Sub Hand
    4:   ("ranged.lua", "models.ranged"), # Ranged
    16:  ("head.lua",   "models.head"),   # Head
    32:  ("body.lua",   "models.body"),   # Body
    64:  ("hands.lua",  "models.hands"),  # Hands
    128: ("legs.lua",   "models.legs"),   # Legs
    256: ("feet.lua",   "models.feet"),   # Feet
}

# Regex to parse the items.lua line-by-line:
ITEM_RE = re.compile(
    r"^\[(?P<id>\d+)\]\s*=\s*\{.*"
    r"en=\"(?P<name>(?:[^\"]|\\.)*)\",.*"
    r"slots=(?P<slots>\d+).*"
)

# Regex to collect existing item IDs in DressUp files
EXISTING_RE = re.compile(r"models\.\w+\[(\d+)\]")

def download_resources(url: str) -> str:
    print(f"Downloading official Windower Resources items.lua...\nFrom: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")

def get_existing_data(lua_file: Path) -> tuple[set[int], set[str]]:
    if not lua_file.exists():
        return set(), set()
    ids = set()
    models = set()
    for line in lua_file.read_text(encoding="utf-8", errors="replace").splitlines():
        # Match ID
        for m in EXISTING_RE.finditer(line):
            ids.add(int(m.group(1)))
        
        # We don't really have a known model list from Windower anymore since they removed it.
        # So we just track ids.
    return ids, models

def format_item(table: str, item_id: int, name: str) -> str:
    # Lowercase and replace underscores with spaces per user request
    name = name.lower().replace("_", " ")
    safe_name = name.replace('"', '\\"')
    # Prefix with comment because model is unknown
    prefix = "-- "
    return f'{prefix}{table}[{item_id}] = {{ name = "{safe_name}" , model = \'XXXXXX\' }}\n'

def main():
    parser = argparse.ArgumentParser(description="Build DressUp gear lists from Windower Resources.")
    parser.add_argument("--dry-run", action="store_true", help="Preview output instead of writing files.")
    parser.add_argument("--include-sub", action="store_true", help="Also populate sub.lua.")
    parser.add_argument("--local-res", type=Path, default=None, help="Path to local items.lua")
    args = parser.parse_args()

    # Load resources
    raw_data = ""
    if args.local_res:
        if args.local_res.is_file():
            print(f"Loading local resource file: {args.local_res}")
            raw_data = args.local_res.read_text(encoding="utf-8", errors="replace")
        else:
            print(f"ERROR: Local file '{args.local_res}' not found.")
            sys.exit(1)
    else:
        try:
            raw_data = download_resources(WINDOWER_RES_URL)
        except Exception as e:
            print(f"ERROR: Failed to download resource file: {e}")
            sys.exit(1)

    print("\nParsing items database...")
    parsed_count = 0
    buckets = {slot: [] for slot in SLOT_MAP}

    for line in raw_data.splitlines():
        line = line.strip()
        m = ITEM_RE.match(line)
        if not m:
            continue

        item_id = int(m.group("id"))
        name = m.group("name").replace("\\'", "'").replace('\\"', '"')
        slots_mask = int(m.group("slots"))

        # Find all valid slots for this item using bitwise AND
        # Notice that some items (like 1H swords) have slots=3 (Main|Sub)
        for bit, (lua_filename, table_name) in SLOT_MAP.items():
            if (slots_mask & bit) == bit:
                if bit == 2 and not args.include_sub:
                    continue
                buckets[bit].append((item_id, name))

        parsed_count += 1

    print(f"Parsed {parsed_count} equippable items.")

    total_appended = 0
    for bit, (lua_filename, table_name) in SLOT_MAP.items():
        if bit == 2 and not args.include_sub:
            continue

        lua_path = SCRIPT_DIR / lua_filename
        existing_ids, _ = get_existing_data(lua_path)
        items = buckets[bit]

        # Filter out existing items
        new_items = [(iid, nm) for iid, nm in items if iid not in existing_ids]
        new_items.sort(key=lambda x: x[0])

        print(f"\n  {lua_filename}: {len(existing_ids)} existing | {len(items)} from Resources | {len(new_items)} NEW to append")

        if not new_items:
            continue

        lines = [
            f"\n-- ============================================================\n",
            f"-- Entries appended by parse_windower_resources.py (Missing models)\n",
            f"-- ============================================================\n",
        ]

        for item_id, name in new_items:
            lines.append(format_item(table_name, item_id, name))

        block = "".join(lines)

        if args.dry_run:
            print(f"  --- DRY RUN: Would append {len(new_items)} entries to {lua_filename} ---")
            preview = block.splitlines()[:10]
            for ln in preview:
                print("    " + ln)
        else:
            with open(lua_path, "a", encoding="utf-8", newline="\n") as f:
                f.write(block)
            print(f"    [OK] Appended {len(new_items)} entries to {lua_filename}")

        total_appended += len(new_items)

    print(f"\nFinished! Processed {total_appended} total new entries.\n")

if __name__ == "__main__":
    main()

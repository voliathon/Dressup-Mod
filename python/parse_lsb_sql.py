#!/usr/bin/env python3
"""
parse_lsb_sql.py  —  DressUp Lua Populator
============================================
Downloads item_basic.sql and item_equipment.sql from LandSandBoat/server,
parses every INSERT row, classifies each item by its slot bitmask, then
APPENDS new itemid→modelid entries into the corresponding DressUp .lua files.

Slot bitmask reference (item_equipment.slot column):
  Bit 0  (0x0001) = Main       → main.lua   (weapons)
  Bit 1  (0x0002) = Sub        → sub.lua    (offhand – skipped by default)
  Bit 2  (0x0004) = Range      → ranged.lua
  Bit 3  (0x0008) = Ammo/Throw → (skipped)
  Bit 4  (0x0010) = Head       → head.lua
  Bit 5  (0x0020) = Body       → body.lua
  Bit 6  (0x0040) = Hands      → hands.lua
  Bit 7  (0x0080) = Legs       → legs.lua
  Bit 8  (0x0100) = Feet       → feet.lua
  Bits 9-15      = Ring/Earring/Neck/Waist/Back → (skipped)

Usage:
    python parse_lsb_sql.py [--dry-run] [--include-sub] [--sql-dir PATH]

    --dry-run      Print what would be written without touching the .lua files.
    --include-sub  Also process sub.lua (offhand weapons).
    --sql-dir PATH Use locally downloaded SQL files instead of fetching from GitHub.
                   Expects files named item_basic.sql and item_equipment.sql in PATH.
"""

import re
import sys
import os
import argparse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent.resolve()

LSB_BASE_URL = "https://raw.githubusercontent.com/LandSandBoat/server/base/sql/"
SQL_BASIC     = "item_basic.sql"
SQL_EQUIP     = "item_equipment.sql"

# Slot bitmask → (lua_file, table_name, use_enl_field)
# use_enl_field: head/body/hands/legs/feet/ranged use "enl" (lowercase name); main does not.
SLOT_MAP = {
    0x0001: ("main.lua",   "models.main",   False),  # Main hand (weapons)
    0x0002: ("sub.lua",    "models.sub",    False),  # Sub / offhand
    0x0004: ("ranged.lua", "models.ranged", True),
    0x0010: ("head.lua",   "models.head",   True),
    0x0020: ("body.lua",   "models.body",   True),
    0x0040: ("hands.lua",  "models.hands",  True),
    0x0080: ("legs.lua",   "models.legs",   True),
    0x0100: ("feet.lua",   "models.feet",   True),
}

# ---------------------------------------------------------------------------
# SQL fetch / load helpers
# ---------------------------------------------------------------------------

def fetch_sql(url: str) -> str:
    print(f"  Fetching {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def load_or_fetch(sql_dir: Path | None, filename: str) -> str:
    if sql_dir:
        path = sql_dir / filename
        print(f"  Loading {path} ...")
        return path.read_text(encoding="utf-8", errors="replace")
    return fetch_sql(LSB_BASE_URL + filename)


# ---------------------------------------------------------------------------
# SQL INSERT parser
# ---------------------------------------------------------------------------

# Matches: INSERT INTO `table` ... VALUES (v1, v2, ...);
# or multi-row:          VALUES (v1, ...), (v2, ...), ...;
INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+`?[\w]+`?\s*.*?VALUES\s*(.*?);",
    re.IGNORECASE | re.DOTALL,
)
ROW_RE = re.compile(r"\(([^)]+)\)")
STR_RE  = re.compile(r"'((?:[^'\\]|\\.)*)'")


def _unquote(token: str) -> str:
    token = token.strip()
    m = STR_RE.fullmatch(token)
    if m:
        return m.group(1).replace("\\'", "'").replace("\\\\", "\\")
    return token


def parse_inserts(sql: str, columns: list[str]) -> list[dict]:
    """Return list of dicts, one per INSERT row, keyed by column name."""
    results = []
    for m in INSERT_RE.finditer(sql):
        values_block = m.group(1)
        for row_m in ROW_RE.finditer(values_block):
            raw_vals = row_m.group(1)
            # Split on commas that are NOT inside quotes
            vals = []
            depth = 0
            buf = []
            in_str = False
            esc = False
            for ch in raw_vals:
                if esc:
                    buf.append(ch); esc = False; continue
                if ch == "\\":
                    esc = True; buf.append(ch); continue
                if ch == "'" and not in_str:
                    in_str = True; buf.append(ch); continue
                if ch == "'" and in_str:
                    in_str = False; buf.append(ch); continue
                if in_str:
                    buf.append(ch); continue
                if ch == "(":
                    depth += 1; buf.append(ch); continue
                if ch == ")":
                    depth -= 1; buf.append(ch); continue
                if ch == "," and depth == 0:
                    vals.append("".join(buf).strip()); buf = []; continue
                buf.append(ch)
            if buf:
                vals.append("".join(buf).strip())

            if len(vals) < len(columns):
                continue  # malformed row, skip

            row = {}
            for i, col in enumerate(columns):
                row[col] = _unquote(vals[i]) if i < len(vals) else ""
            results.append(row)
    return results


def extract_columns(sql: str, table: str) -> list[str]:
    """Extract column order from CREATE TABLE statement."""
    pattern = re.compile(
        r"CREATE\s+TABLE\s+`?" + re.escape(table) + r"`?\s*\((.+?)\)\s*ENGINE",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(sql)
    if not m:
        return []
    body = m.group(1)
    cols = []
    for line in body.splitlines():
        line = line.strip().lstrip("`")
        col_m = re.match(r"`?([\w]+)`?\s+", line)
        if col_m and not line.upper().startswith(("PRIMARY", "KEY", "UNIQUE", "INDEX", "CONSTRAINT")):
            cols.append(col_m.group(1).lower())
    return cols


# ---------------------------------------------------------------------------
# DressUp Lua reader — collect existing itemids already in each file
# ---------------------------------------------------------------------------

EXISTING_RE = re.compile(r"models\.\w+\[(\d+)\]")


def read_existing_data(lua_path: Path) -> tuple[set[int], set[int]]:
    if not lua_path.exists():
        return set(), set()
    ids = set()
    models = set()
    for line in lua_path.read_text(encoding="utf-8", errors="replace").splitlines():
        for m in EXISTING_RE.finditer(line):
            ids.add(int(m.group(1)))
            
        if line.strip().startswith("models."):
            m_mod = re.search(r'model\s*=\s*(\d+)', line)
            if m_mod:
                models.add(int(m_mod.group(1)))
    return ids, models


# ---------------------------------------------------------------------------
# Lua entry formatter
# ---------------------------------------------------------------------------

def fmt_main(table: str, itemid: int, name: str, modelid: int, is_duplicate: bool) -> str:
    safe_name = name.replace('"', '\\"')
    prefix = "-- " if is_duplicate else ""
    return f'{prefix}{table}[{itemid}] = {{ name = "{safe_name}" , model = {modelid}}}\n'


def fmt_slot(table: str, itemid: int, name: str, modelid: int, is_duplicate: bool) -> str:
    safe_name = name.replace('"', '\\"')
    prefix = "-- " if is_duplicate else ""
    return (
        f'{prefix}{table}[{itemid}] = '
        f'{{ name = "{safe_name}" , model = {modelid}}} \n'
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Populate DressUp .lua files from LandSandBoat SQL.")
    parser.add_argument("--dry-run",     action="store_true", help="Print new entries without writing files.")
    parser.add_argument("--include-sub", action="store_true", help="Also generate sub.lua entries.")
    parser.add_argument("--sql-dir",     type=Path, default=None,
                        help="Path to a folder with pre-downloaded item_basic.sql and item_equipment.sql.")
    args = parser.parse_args()

    sql_dir: Path | None = args.sql_dir
    if sql_dir and not sql_dir.is_dir():
        print(f"ERROR: --sql-dir '{sql_dir}' is not a directory.")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # 1. Fetch / load SQL
    # -----------------------------------------------------------------------
    print("\n[1/4] Loading SQL files...")
    sql_basic = load_or_fetch(sql_dir, SQL_BASIC)
    sql_equip = load_or_fetch(sql_dir, SQL_EQUIP)

    # -----------------------------------------------------------------------
    # 2. Parse item_basic → itemid→name map
    # -----------------------------------------------------------------------
    print("\n[2/4] Parsing item_basic...")
    basic_cols = extract_columns(sql_basic, "item_basic")
    if not basic_cols:
        # Fallback: assume positional order used in LSB
        basic_cols = ["itemid", "subid", "modelid", "stackable", "flags", "auc", "type"]
    basic_rows = parse_inserts(sql_basic, basic_cols)

    name_map: dict[int, str] = {}   # itemid → item name (from item_basic description or ID)
    # item_basic doesn't always store the name — we'll supplement from item_equipment comments
    # For now, build a fallback name from itemid.
    for row in basic_rows:
        try:
            iid = int(row.get("itemid", 0))
            # Some LSB builds have a 'name' column, others do not
            nm = row.get("name") or row.get("english") or f"Item_{iid}"
            name_map[iid] = nm
        except ValueError:
            pass

    print(f"  -> {len(name_map)} items in item_basic")

    # -----------------------------------------------------------------------
    # 3. Parse item_equipment → slot+model mappings
    # -----------------------------------------------------------------------
    print("\n[3/4] Parsing item_equipment...")
    equip_cols = extract_columns(sql_equip, "item_equipment")
    if not equip_cols:
        equip_cols = ["itemid", "name", "level", "ilevel", "jobs", "mid", "shieldsize", "scripttype", "slot", "rslot", "rslotlook", "su_level"]
    equip_rows = parse_inserts(sql_equip, equip_cols)
    print(f"  -> {len(equip_rows)} rows in item_equipment")

    # Also harvest names from inline SQL comments like:  -- Sword of Light
    comment_name_re = re.compile(r"\((\d+),\s*\d+,.*?--\s*(.+?)$", re.MULTILINE)
    for m in comment_name_re.finditer(sql_equip):
        iid = int(m.group(1))
        if iid not in name_map or name_map[iid].startswith("Item_"):
            name_map[iid] = m.group(2).strip()

    # If the SQL provides a name column directly in item_equipment, update the name_map
    for row in equip_rows:
        try:
            iid = int(row.get("itemid", 0))
            if "name" in row and row["name"]:
                # Clean up the name e.g. 'hexed_haubert_-1' -> 'hexed haubert -1'
                clean_name = row["name"].replace("_", " ")
                if iid not in name_map or name_map[iid].startswith("Item_"):
                    name_map[iid] = clean_name
        except ValueError:
            pass

    # -----------------------------------------------------------------------
    # 4. Classify, diff against existing, write
    # -----------------------------------------------------------------------
    print("\n[4/4] Classifying and writing...")

    # bucket: slot_bit -> list of (itemid, name, modelid)
    buckets: dict[int, list[tuple[int, str, int]]] = {bit: [] for bit in SLOT_MAP}

    for row in equip_rows:
        try:
            itemid  = int(row.get("itemid", 0))
            modelid_str = row.get("modelid") or row.get("mid") or "0"
            modelid = int(modelid_str)
            slot    = int(row.get("slot", 0))
        except (ValueError, TypeError):
            continue

        if modelid == 0:
            continue  # no visual model

        name = name_map.get(itemid, f"Item_{itemid}")

        for bit, (lua_file, table_name, use_enl) in SLOT_MAP.items():
            if slot & bit:
                # Skip sub unless requested
                if bit == 0x0002 and not args.include_sub:
                    continue
                buckets[bit].append((itemid, name, modelid))

    total_new = 0
    for bit, (lua_file, table_name, use_enl) in SLOT_MAP.items():
        if bit == 0x0002 and not args.include_sub:
            continue

        lua_path = SCRIPT_DIR / lua_file
        existing_ids, existing_models = read_existing_data(lua_path)
        entries  = buckets[bit]

        new_entries = [(iid, nm, mid) for iid, nm, mid in entries if iid not in existing_ids]
        new_entries.sort(key=lambda x: x[0])  # sort by itemid

        slot_name = {
            0x0001: "main", 0x0002: "sub", 0x0004: "ranged",
            0x0010: "head", 0x0020: "body", 0x0040: "hands",
            0x0080: "legs", 0x0100: "feet",
        }[bit]

        print(f"\n  {lua_file}: {len(existing_ids)} existing | "
              f"{len(entries)} from SQL | {len(new_entries)} NEW to append")

        if not new_entries:
            print("    (nothing new to add)")
            continue

        # Build block to append
        lines = [
            f"\n-- ============================================================\n",
            f"-- Entries appended by parse_lsb_sql.py from LandSandBoat/server\n",
            f"-- ============================================================\n",
        ]

        for itemid, name, modelid in new_entries:
            is_dup = modelid in existing_models
            if not is_dup:
                existing_models.add(modelid)

            if use_enl:
                lines.append(fmt_slot(table_name, itemid, name, modelid, is_dup))
            else:
                lines.append(fmt_main(table_name, itemid, name, modelid, is_dup))

        block = "".join(lines)

        if args.dry_run:
            print(f"\n  --- DRY RUN: would append to {lua_file} ---")
            # Print first 20 lines as preview
            preview = block.splitlines()[:20]
            for ln in preview:
                print("    " + ln)
            if len(block.splitlines()) > 20:
                print(f"    ... ({len(new_entries) - 20} more entries)")
        else:
            with open(lua_path, "a", encoding="utf-8", newline="\n") as f:
                f.write(block)
            print(f"    [OK] Appended {len(new_entries)} entries to {lua_file}")

        total_new += len(new_entries)

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Done. {total_new} total new entries processed.\n")


if __name__ == "__main__":
    main()

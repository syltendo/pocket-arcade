#!/usr/bin/env python3
"""Join dataset v0 with MAME metadata -> site data file.

Inputs:
- data/games-v0.json   (collector output: cores + instance-JSON game lists)
- raw/mame.xml         (local MAME 0.264 -listxml: year, manufacturer, players,
                        orientation, cloneof, driver status)
- raw/catver.ini       (progetto-SNAPS categories: genre per set)

Output: site/games.json — one record per (game, core) plus a "ports" list on
each record naming every platform/core that runs the same MAME set.
"""
import json, re
import xml.etree.ElementTree as ET

ROOT = "/home/hatch/workspace/pocket-arcade-db"

# ---- our setnames -------------------------------------------------------
data = json.load(open(f"{ROOT}/data/games-v0.json"))
wanted = set()
for core in data:
    for g in core["games"]:
        s = g.get("setname") or g.get("setname_hint")
        if s:
            wanted.add(s.lower())
print(f"setnames wanted: {len(wanted)}")

# ---- MAME xml (streamed, only wanted machines kept) ---------------------
meta = {}
for _ev, el in ET.iterparse(f"{ROOT}/raw/mame.xml", events=("end",)):
    if el.tag != "machine":
        continue
    name = el.get("name", "").lower()
    if name in wanted:
        disp = el.find("display")
        inp = el.find("input")
        drv = el.find("driver")
        meta[name] = {
            "year": (el.findtext("year") or "").strip(),
            "manufacturer": (el.findtext("manufacturer") or "").strip(),
            "cloneof": el.get("cloneof"),
            "vertical": bool(disp is not None and disp.get("rotate") in ("90", "270")),
            "players": int(inp.get("players", "0")) if inp is not None else 0,
            "buttons": int(inp.get("buttons", "0")) if inp is not None else 0,
            "status": drv.get("status", "") if drv is not None else "",
        }
    el.clear()
print(f"mame matches: {len(meta)}")

# ---- catver genres ------------------------------------------------------
genre = {}
section = None
for line in open(f"{ROOT}/raw/catver.ini", encoding="utf-8", errors="replace"):
    line = line.strip()
    if line.startswith("["):
        section = line.strip("[]").lower()
        continue
    if section == "category" and "=" in line:
        k, v = line.split("=", 1)
        genre[k.strip().lower()] = v.strip()
print(f"catver entries: {len(genre)}")

# ---- build records ------------------------------------------------------
def core_label(core_id):
    return core_id.split(".", 1)[1] if "." in core_id else core_id

records = []
by_set = {}
for core in data:
    author = core["core_id"].split(".", 1)[0]
    label = core_label(core["core_id"])
    board = core["platforms"][0] if core["platforms"] else label
    for g in core["games"]:
        s = (g.get("setname") or g.get("setname_hint") or "").lower() or None
        m = meta.get(s) if s else None
        cat = genre.get(s, "") if s else ""
        rec = {
            "title": g["title"],
            "set": s,
            "core": label,
            "core_id": core["core_id"],
            "author": author,
            "board": board,
            "alt": g["set_type"] == "alternative",
            "patreon": bool(core["requires_license"]),
            "repo": core["repo"],
            "year": (m or {}).get("year") or None,
            "manufacturer": (m or {}).get("manufacturer") or None,
            "players": (m or {}).get("players") or None,
            "buttons": (m or {}).get("buttons") or None,
            "vertical": (m or {}).get("vertical") if m else None,
            "cloneof": (m or {}).get("cloneof") if m else None,
            "genre": cat or None,
            "genre_top": cat.split(" / ")[0] if cat else None,
        }
        records.append(rec)
        if s:
            by_set.setdefault(s, []).append(rec)

# ports: every platform/core running the same set
for rec in records:
    if rec["set"]:
        ports = {(r["board"], r["core"]) for r in by_set[rec["set"]]}
        rec["ports"] = sorted(f"{b} · {c}" for b, c in ports)
    else:
        rec["ports"] = [f"{rec['board']} · {rec['core']}"]

json.dump(records, open(f"{ROOT}/site/games.json", "w"), ensure_ascii=False, separators=(",", ":"))
n = len(records)
print(f"records: {n}")
print(f"  with year: {sum(1 for r in records if r['year'])}")
print(f"  with manufacturer: {sum(1 for r in records if r['manufacturer'])}")
print(f"  with genre: {sum(1 for r in records if r['genre'])}")
print(f"  with players: {sum(1 for r in records if r['players'])}")
print(f"  vertical known: {sum(1 for r in records if r['vertical'] is not None)} (vertical: {sum(1 for r in records if r['vertical'])})")
print(f"  multi-port games: {sum(1 for r in records if len(r['ports']) > 1)}")

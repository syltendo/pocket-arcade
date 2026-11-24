#!/usr/bin/env python3
"""Fetch one in-game screenshot per game from libretro-thumbnails.

Source: github.com/libretro-thumbnails/MAME, folder Named_Snaps — the
progettoSNAPS MAME snap collection, whose files are named by the game's full
MAME description (with &*/:`<>?\\"| replaced by _), NOT by set name.

For each game in site/games.json, try in order: the parent set, then its
versions (main sets first); for each, the full description and the base
title. First hit wins and is saved as site/snaps/<parent set>.png (or the
first version's set for title-keyed games). The file name is recorded in
games.json as "snap" (null when nothing was found). Existing files are
kept, so reruns only fetch what's missing.

Fallback (Syl, 2026-11-23): Arcade Database (adb.arcadeitalia.net) serves
an in-game screenshot per MAME set — including sets newer than 0.264 and
HBMAME sets that libretro-thumbnails doesn't carry. When the libretro pass
finds nothing, try each candidate set there before giving up.

Pipeline: collect.py -> join.py -> fetch_snaps.py
"""
import json, os, re, sys
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = "https://raw.githubusercontent.com/libretro-thumbnails/MAME/master/Named_Snaps/"
ADB = "https://adb.arcadeitalia.net/media/mame.current/ingames/"
UA = {"User-Agent": "PocketArcadeDB-snaps/0.1"}


def base_title(t):
    while True:
        t2 = re.sub(r"\s*\([^)]*\)\s*$", "", t).strip()
        if t2 == t:
            return t
        t = t2


def libname(t):
    return re.sub(r'[&*/:`<>?\\"|]', "_", t) + ".png"


def main():
    games = json.load(open(f"{ROOT}/site/games.json"))
    wanted = set()
    for g in games:
        if g.get("set"):
            wanted.add(g["set"])
        for v in g["versions"]:
            if v.get("set"):
                wanted.add(v["set"])
    desc = {}
    for _ev, el in ET.iterparse(f"{ROOT}/raw/mame.xml", events=("end",)):
        if el.tag == "machine":
            if el.get("name") in wanted:
                desc[el.get("name")] = (el.findtext("description") or "").strip()
            el.clear()
    print(f"descriptions: {len(desc)} for {len(wanted)} sets")
    os.makedirs(f"{ROOT}/site/snaps", exist_ok=True)

    def candidates(g):
        sets = []
        if g.get("set"):
            sets.append(g["set"])
        for v in sorted(g["versions"], key=lambda v: v["alt"]):
            if v.get("set") and v["set"] not in sets:
                sets.append(v["set"])
        names = []
        for s in sets:
            if desc.get(s):
                names += [libname(desc[s]), libname(base_title(desc[s]))]
        for v in g["versions"]:
            if v.get("mtitle"):
                names.append(libname(v["mtitle"]))
        return sets, list(dict.fromkeys(names))

    def fetch(g):
        sets, names = candidates(g)
        key = g.get("set") or (sets[0] if sets else None)
        if not key:
            return None
        out = f"{ROOT}/site/snaps/{key}.png"
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return f"{key}.png"
        for name in names:
            url = BASE + urllib.parse.quote(name)
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
                if data[:8] == b"\x89PNG\r\n\x1a\n":
                    with open(out, "wb") as f:
                        f.write(data)
                    return f"{key}.png"
            except Exception:
                continue
        for s in sets:  # Arcade Database fallback, keyed by set name
            try:
                req = urllib.request.Request(ADB + s + ".png", headers=UA)
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
                if data[:8] == b"\x89PNG\r\n\x1a\n":
                    with open(out, "wb") as f:
                        f.write(data)
                    return f"{key}.png"
            except Exception:
                continue
        return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(fetch, games))
    got = 0
    for g, snap in zip(games, results):
        g["snap"] = snap
        got += bool(snap)
    json.dump(games, open(f"{ROOT}/site/games.json", "w"),
              ensure_ascii=False, separators=(",", ":"))
    total_kb = sum(os.path.getsize(f"{ROOT}/site/snaps/{f}")
                   for f in os.listdir(f"{ROOT}/site/snaps")) // 1024
    print(f"screenshots: {got}/{len(games)} games covered, snaps dir = {total_kb} KB")


if __name__ == "__main__":
    sys.exit(main())

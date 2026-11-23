#!/usr/bin/env python3
"""Dataset v0 collector for the Pocket Arcade Database.

Sources:
- openFPGA Library API v3 (cores.json + platforms.json, cached in raw/)
- Each arcade core's latest release zip -> instance JSONs = playable games
- Jotego jtbin game_list.md -> set names for Jotego cores

Output: data/games-v0.json + printed stats. No ROMs, metadata only.
"""
import io, json, re, sys, zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen

ROOT = "/home/hatch/workspace/pocket-arcade-db"
MAX_ZIP = 60 * 1024 * 1024  # skip absurdly large zips, log them
DENY = ("how to add", "no disc", "bios")

def fetch(url, timeout=60):
    req = Request(url, headers={"User-Agent": "pocket-arcade-db/0.1"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()

platforms = {p["id"]: p for p in json.load(open(f"{ROOT}/raw/platforms.json"))["data"]}
cores = json.load(open(f"{ROOT}/raw/cores.json"))["data"]

arcade = []
for c in cores:
    if not c["releases"]:
        continue
    rel = c["releases"][0]
    pids = rel["core"]["metadata"].get("platform_ids", [])
    plats = [platforms[p] for p in pids if p in platforms]
    if any(p["category"] == "Arcade" for p in plats):
        arcade.append((c, rel, plats))
print(f"arcade cores: {len(arcade)}", flush=True)

def games_from_zip(c, rel, plats):
    url = rel["download_url"]
    out = {"core_id": c["id"], "repo": f"{c['repository']['owner']}/{c['repository']['name']}",
           "version": rel["core"]["metadata"].get("version"),
           "requires_license": rel.get("requires_license", False),
           "platforms": [p["name"] for p in plats], "games": [], "error": None}
    try:
        blob = fetch(url)
        if len(blob) > MAX_ZIP:
            out["error"] = f"zip too large ({len(blob)//1048576} MB)"
            return out
        z = zipfile.ZipFile(io.BytesIO(blob))
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    for name in z.namelist():
        if not name.lower().endswith(".json"):
            continue
        parts = name.split("/")
        # instance JSONs live under Assets/<platform>/<Author.Core>/...
        if len(parts) < 4 or parts[0] != "Assets":
            continue
        fname = parts[-1][:-5]
        if any(d in fname.lower() for d in DENY) or fname.startswith("!"):
            continue
        sub = parts[3:-1]
        set_type = "alternative" if any(s.startswith("_") for s in sub) else "main"
        setname = None
        try:
            doc = json.loads(z.read(name))
            for slot in doc.get("instance", {}).get("data_slots", []):
                fn = slot.get("filename", "")
                if "." in fn:
                    setname = fn.rsplit(".", 1)[0]
                    break
        except Exception:
            pass
        out["games"].append({"title": fname, "set_type": set_type, "setname_hint": setname})
    return out

results = []
with ThreadPoolExecutor(max_workers=8) as ex:
    for r in ex.map(lambda a: games_from_zip(*a), arcade):
        results.append(r)
        print(f"  {r['core_id']}: {len(r['games'])} games" + (f" ERROR {r['error']}" if r["error"] else ""), flush=True)

# cores with no instance JSONs: single-game / direct-load cores -> one entry
for r in results:
    if not r["games"] and not r["error"]:
        title = r["platforms"][0] if r["platforms"] else r["core_id"]
        r["games"] = [{"title": title, "set_type": "main", "setname_hint": None, "core_only": True}]

# Jotego set names from game_list.md
try:
    md = fetch("https://raw.githubusercontent.com/jotego/jtbin/master/game_list.md").decode("utf-8", "replace")
    jt = {}
    for line in md.splitlines():
        m = re.match(r"\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", line)
        if m and m.group(1).strip().lower() not in ("core", "---"):
            jt[(m.group(1).strip().lower(), m.group(2).strip().lower())] = m.group(3).strip()
    matched = 0
    for r in results:
        if not r["core_id"].startswith("jotego."):
            continue
        short = r["core_id"].split(".", 1)[1].lower().removeprefix("jt")
        for g in r["games"]:
            key = (short, re.sub(r"\s*\([^)]*\)\s*$", "", g["title"]).strip().lower())
            # game_list titles often lack the (Region date) suffix; try full title too
            s = jt.get((short, g["title"].lower())) or jt.get(key)
            if s:
                g["setname"] = s
                matched += 1
    print(f"jotego setname matches: {matched}")
except Exception as e:
    print(f"game_list fetch failed: {e}")

total = sum(len(r["games"]) for r in results)
json.dump(results, open(f"{ROOT}/data/games-v0.json", "w"), indent=1, ensure_ascii=False)
errs = [r for r in results if r["error"]]
print(f"\nTOTAL: {len(results)} cores, {total} game entries, {len(errs)} errors")
for r in errs:
    print("  ERR", r["core_id"], r["error"])

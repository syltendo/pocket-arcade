#!/usr/bin/env python3
"""Join dataset v0 with MAME metadata -> site data file (grouped).

One entry per GAME: all versions (parent set + clones/alternates, across all
cores) are merged into a single record whose "versions" list names each set,
and "platforms" lists every Pocket platform/core combination running it.

Inputs : data/games-v0.json, raw/mame.xml (MAME 0.264 -listxml), raw/catver.ini
Output : site/games.json
"""
import json, os, re
import xml.etree.ElementTree as ET

ROOT = "/home/hatch/workspace/pocket-arcade-db"

data = json.load(open(f"{ROOT}/data/games-v0.json"))
wanted = set()
for core in data:
    for g in core["games"]:
        s = g.get("setname") or g.get("setname_hint")
        if s:
            wanted.add(s.lower())
print(f"setnames wanted: {len(wanted)}")

# pass 1: cloneof map for every machine (cheap), so clone chains resolve to the root parent
cloneof = {}
for _ev, el in ET.iterparse(f"{ROOT}/raw/mame.xml", events=("end",)):
    if el.tag == "machine":
        cloneof[el.get("name", "").lower()] = (el.get("cloneof") or "").lower() or None
    el.clear()

def root(s):
    seen = set()
    while cloneof.get(s) and cloneof[s] not in seen:
        seen.add(s)
        s = cloneof[s]
    return s

def base_title(desc):
    t = desc
    while True:
        t2 = re.sub(r"\s*\([^)]*\)\s*$", "", t).strip()
        if t2 == t:
            return t
        t = t2

REGION_WORDS = ["Hong Kong", "Japan", "USA", "Europe", "World", "Asia", "Korea",
                "Brazil", "Australia", "Canada", "China", "Taiwan", "Germany",
                "France", "Spain", "Italy", "UK", "US"]

def parse_region(desc):
    """Region = earliest region keyword inside any (…) group of a MAME description."""
    best = None
    for grp in re.findall(r"\(([^)]*)\)", desc):
        for w in REGION_WORDS:
            m = re.search(rf"\b{re.escape(w)}\b", grp)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), w)
    if not best:
        return None
    return "USA" if best[1] == "US" else best[1]

def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", base_title(t).lower()).strip()

def suffix(desc):
    m = re.search(r"\(([^)]*)\)\s*$", desc)
    return m.group(1) if m else ""

full = wanted | {root(s) for s in wanted}
meta = {}
for _ev, el in ET.iterparse(f"{ROOT}/raw/mame.xml", events=("end",)):
    if el.tag != "machine":
        continue
    name = el.get("name", "").lower()
    if name in full:
        disp = el.find("display")
        inp = el.find("input")
        desc = (el.findtext("description") or "").strip()
        meta[name] = {
            "desc": desc,
            "region": parse_region(desc),
            "year": (el.findtext("year") or "").strip(),
            "manufacturer": (el.findtext("manufacturer") or "").strip(),
            "cloneof": el.get("cloneof"),
            "vertical": bool(disp is not None and disp.get("rotate") in ("90", "270")),
            "players": int(inp.get("players", "0")) if inp is not None else 0,
            "buttons": int(inp.get("buttons", "0")) if inp is not None else 0,
        }
    el.clear()
print(f"mame machines kept: {len(meta)}")

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

# ---- nplayers: curated player counts + simultaneous play -----------------
npl = {}
section = None
for line in open(f"{ROOT}/raw/nplayers.ini", encoding="utf-8", errors="replace"):
    line = line.strip()
    if line.startswith("["):
        section = line.strip("[]").lower()
        continue
    if section == "nplayers" and "=" in line:
        k, v = line.split("=", 1)
        m = re.match(r"(\d+)P", v.strip())
        if m:
            npl[k.strip().lower()] = (int(m.group(1)), "sim" in v)
print(f"nplayers entries: {len(npl)}")


# ---- genre taxonomy (Syl, 2026-11-23) -------------------------------------
# catver categories are remapped to Syl's own genre list (the one he uses for
# his Pocket library folders). A game can carry SEVERAL genres when its catver
# category is genuinely hybrid. Machine-type categories (Arcade, Game Console,
# Medal Game...) are never genres: those games are mapped by gameplay or fall
# to "Other". Adventure / RPG exist in the taxonomy but no catver arcade entry
# maps to them yet (they will appear when no-genre games are hand-classified).
SET_GENRE_OVERRIDES = {
    "sfzch": ["Vs. Fighting"],        # catver: Game Console / Home Videogame
    "wofch": ["Beat 'em Up"],         # catver: Game Console / Home Videogame
    "3wonders": ["Action", "Platformer", "Shoot 'em Up", "Puzzle"],  # compilation
}

def map_genres(cat, setname=None):
    if setname in SET_GENRE_OVERRIDES:
        return SET_GENRE_OVERRIDES[setname]
    if not cat:
        return []
    c = re.sub(r"\s*\*[^*]*\*", "", cat).strip()  # drop "* Mature *" etc.
    if c.startswith("Fighter / Versus"):
        return ["Vs. Fighting"]
    if c in ("Fighter / 2D", "Fighter / Misc.", "Fighter / Vertical"):
        return ["Vs. Fighting"]
    if c == "Fighter / 2.5D" or c == "Platform / Fighter Scrolling":
        return ["Beat 'em Up"]
    if c in ("Platform / Shooter Scrolling", "Platform / Shooter"):
        return ["Run 'n' Gun", "Platformer"]
    if c == "Shooter / Walking":
        return ["Run 'n' Gun"]
    if c.startswith("Shooter / Driving"):
        return ["Shoot 'em Up", "Racing"]
    if c.startswith("Shooter"):
        return ["Shoot 'em Up"]
    if c.startswith("Platform / Run"):
        return ["Platformer"]
    if c.startswith("Platform"):
        return ["Action", "Platformer"]
    if c == "Maze / Shooter Large" or c == "Maze / Shooter Small":
        return ["Maze", "Shoot 'em Up"]
    if c == "Maze / Driving":
        return ["Maze", "Racing"]
    if c == "Maze / Fighter":
        return ["Maze", "Action"]
    if c.startswith("Maze"):
        return ["Maze"]
    if c == "Puzzle / Maze":
        return ["Puzzle", "Maze"]
    if c.startswith("Puzzle"):
        return ["Puzzle"]
    if c.startswith("Driving"):
        return ["Racing"]
    if c.startswith("Sports"):
        return ["Sports"]
    if c.startswith("Quiz"):
        return ["Quiz"]
    if c == "Tabletop / Shanghai":
        return ["Tabletop", "Puzzle"]
    if c.startswith("Tabletop"):
        return ["Tabletop"]
    if c.startswith("Ball & Paddle"):
        return ["Action"]
    if c.startswith("Climbing"):
        return ["Action", "Platformer"]
    if c == "Multiplay / Mini-Games":
        return ["Puzzle", "Action"]
    if c == "Redemption Game / Action":
        return ["Action"]
    if c.startswith("Misc."):
        return ["Action"]
    return ["Other"]


# ---- home ports: MAME software lists (Syl, 2026-11-23) --------------------
# A home port = a software-list entry, on a system that has an openFPGA core
# on the Pocket, whose base title exactly matches the arcade game's title
# (main or regional). Same-title-but-different games and renamed real ports
# are curated in ports_exceptions.json (add / remove, keyed by parent set).
SW_SYSTEMS = {
    "nes": "NES / Famicom", "snes": "SNES / Super Famicom",
    "megadriv": "Mega Drive / Genesis", "sms": "Master System",
    "gamegear": "Game Gear", "gameboy": "Game Boy", "gbcolor": "Game Boy Color",
    "gba": "Game Boy Advance", "pce": "PC Engine / TurboGrafx-16",
    "tg16": "PC Engine / TurboGrafx-16", "pcecd": "PC Engine CD / TurboGrafx-CD",
    "segacd": "Mega CD / Sega CD", "32x": "32X", "saturn": "Saturn",
    "psx": "PlayStation", "n64": "Nintendo 64", "a2600": "Atari 2600",
    "a7800": "Atari 7800", "lynx": "Atari Lynx", "coleco": "ColecoVision",
    "intv": "Intellivision", "vectrex": "Vectrex",
    "ngp": "Neo Geo Pocket / Color", "ngpc": "Neo Geo Pocket / Color",
    "wswan": "WonderSwan / Color", "wscolor": "WonderSwan / Color",
    "msx1_cart": "MSX", "msx2_cart": "MSX",
    "c64_cart": "Commodore 64", "c64_cass": "Commodore 64",
    "amigaocs_flop": "Amiga", "spectrum_cass": "ZX Spectrum",
}
sw_index = {}
os.makedirs(f"{ROOT}/raw/swlists", exist_ok=True)
for fname, label in SW_SYSTEMS.items():
    path = f"{ROOT}/raw/swlists/{fname}.xml"
    if not os.path.exists(path):
        try:
            import urllib.request
            urllib.request.urlretrieve(
                f"https://raw.githubusercontent.com/mamedev/mame/mame0264/hash/{fname}.xml", path)
        except Exception as e:
            print(f"software list {fname}: download failed ({e})")
            continue
    try:
        for sw in ET.parse(path).getroot().iter("software"):
            desc = (sw.findtext("description") or "").strip()
            if desc:
                sw_index.setdefault(norm_title(desc), set()).add(label)
    except Exception as e:
        print(f"software list {fname}: parse failed ({e})")
print(f"software-list titles indexed: {len(sw_index)}")
try:
    ports_exc = json.load(open(f"{ROOT}/ports_exceptions.json"))
except Exception:
    ports_exc = {"add": {}, "remove": {}}

# ---- per-(game, core) records -------------------------------------------
records = []
for core in data:
    author = core["core_id"].split(".", 1)[0]
    label = core["core_id"].split(".", 1)[1] if "." in core["core_id"] else core["core_id"]
    board = core.get("board") or (core["platforms"][0] if core["platforms"] else label)
    for g in core["games"]:
        s = (g.get("setname") or g.get("setname_hint") or "").lower() or None
        records.append({
            "title": g["title"], "set": s, "core": label, "core_id": core["core_id"],
            "author": author, "board": board, "alt": g["set_type"] == "alternative",
            "patreon": bool(core["requires_license"]),
        })

# ---- group by parent set -------------------------------------------------
groups = {}
for r in records:
    # a set name only counts for grouping if MAME or catver actually knows it;
    # otherwise (chip names, folder names, post-0.264 sets) fall back to the title.
    # The raw set is kept on the record for display in the versions list.
    s = r["set"]
    if s and s not in cloneof and s not in genre:
        s = None
    parent = root(s) if s else None
    key = parent if parent else "title:" + norm_title(r["title"])
    groups.setdefault(key, []).append(r)

# phase 2: sets unknown to MAME 0.264 (e.g. hsf2j2, added later) can't resolve
# their parent — merge them into the known-parent group with the same
# normalized title on the same core, when there is exactly one candidate.
def group_norm_title(key, rs):
    if key in meta and meta[key]["desc"]:
        return norm_title(meta[key]["desc"])
    return norm_title(rs[0]["title"])

known = {k: group_norm_title(k, rs) for k, rs in groups.items() if k in meta}
for key in list(groups):
    if key in meta:
        continue
    nt = group_norm_title(key, groups[key])
    my_cores = {r["core_id"] for r in groups[key]}
    cands = [k for k, t in known.items()
             if t == nt and my_cores & {r["core_id"] for r in groups[k]}]
    if len(cands) == 1:
        groups[cands[0]].extend(groups.pop(key))
        print(f"phase2 merge: {key} -> {cands[0]}")

out = []
for key, rs in groups.items():
    parent_set = key if not key.startswith("title:") else None
    pm = meta.get(parent_set) if parent_set else None
    # canonical title: parent's MAME description, else a member's title
    if pm and pm["desc"]:
        title = base_title(pm["desc"])
    else:
        title = base_title(rs[0]["title"])
    # metadata: parent's MAME record first, else any member's
    src = pm
    if not src:
        for r in rs:
            if r["set"] and meta.get(r["set"]):
                src = meta[r["set"]]
                break
    cat = genre.get(parent_set, "") if parent_set else ""
    if not cat:
        for r in rs:
            if r["set"] and genre.get(r["set"]):
                cat = genre[r["set"]]
                break
    # versions: one per distinct set (or per title when no set)
    versions = {}
    for r in rs:
        vk = r["set"] or ("title:" + r["title"].lower())
        v = versions.setdefault(vk, {
            "set": r["set"],
            "label": suffix((meta.get(r["set"]) or {}).get("desc", "")) or (r["title"] if r["title"] != title else ""),
            "title": r["title"],
            "cores": set(), "alt": True, "patreon": False,
            "mtitle": None, "region": None, "mtitle_mame": False,
        })
        m = meta.get(r["set"]) if r["set"] else None
        if m and m["desc"]:
            if not v["mtitle_mame"]:
                v["mtitle"] = base_title(m["desc"])
                v["region"] = m["region"]
                v["mtitle_mame"] = True
        elif not v["mtitle"]:
            v["mtitle"] = base_title(r["title"])
            v["region"] = parse_region(r["title"])
        v["cores"].add(r["core"] if r["board"].lower() == r["core"].lower() else f"{r['board']} · {r['core']}")
        v["alt"] = v["alt"] and r["alt"] and (r["set"] != parent_set)
        v["patreon"] = v["patreon"] or r["patreon"]
    vlist = sorted(versions.values(), key=lambda v: (v["alt"], v["set"] or v["title"]))
    for v in vlist:
        v["cores"] = sorted(v["cores"])
        v.pop("mtitle_mame", None)
    # regional titles: distinct names for this game, with the regions using each
    regional = {}
    for v in vlist:
        if not v.get("mtitle"):
            continue
        e = regional.setdefault(norm_title(v["mtitle"]), {"t": v["mtitle"], "r": set()})
        if v.get("region"):
            e["r"].add(v["region"])
    regional_list = [{"t": e["t"], "r": sorted(e["r"])} for e in regional.values()]
    regional_list.sort(key=lambda e: (norm_title(e["t"]) != norm_title(title), e["t"]))
    genres = map_genres(cat, parent_set)
    home = set()
    for k in {norm_title(title)} | {norm_title(e["t"]) for e in regional_list}:
        home |= sw_index.get(k, set())
    exc_key = parent_set or ("title:" + norm_title(title))
    home |= set(ports_exc.get("add", {}).get(exc_key, []))
    home -= set(ports_exc.get("remove", {}).get(exc_key, []))
    platforms = sorted({c for v in vlist for c in v["cores"]})
    # multiplayer modes: simultaneous play from nplayers.ini; co-op / comp
    # derived from the catver category + simultaneous play (see site footer)
    npl_hits = [npl[s] for s in [parent_set] + [v["set"] for v in vlist] if s and s in npl]
    sim = any(s_ for p_, s_ in npl_hits if p_ >= 2)
    npl_players = max((p_ for p_, _ in npl_hits), default=0)
    gt = cat.split(" / ")[0] if cat else None
    comp = coop = False
    if "Versus Co-op" in cat:  # catver's own category names keep the word "Versus"
        comp = coop = True
    elif "Versus" in cat:
        comp = True
    if sim and not comp and (cat == "Fighter / 2.5D" or
                               (gt in ("Shooter", "Platform", "Maze") and cat != "Shooter / Gallery")):
        coop = True
    if sim and gt in ("Sports", "Puzzle") and not coop:
        comp = True
    out.append({
        "title": title,
        "set": parent_set,
        "year": (src or {}).get("year") or None,
        "manufacturer": (src or {}).get("manufacturer") or None,
        "players": npl_players or (src or {}).get("players") or None,
        "sim": sim, "coop": coop, "comp": comp,
        "buttons": (src or {}).get("buttons") or None,
        "vertical": (src or {}).get("vertical") if src else None,
        "genre": ", ".join(genres) if genres else None,
        "genres": genres,
        "genre_top": genres[0] if genres else None,
        "regional": regional_list,
        "patreon": any(v["patreon"] for v in vlist),
        "has_main": any(not v["alt"] for v in vlist),
        "platforms": platforms,
        "home_ports": sorted(home),
        "cores": sorted({r["core"] for r in rs}),
        "authors": sorted({r["author"] for r in rs}),
        "boards": sorted({r["board"] for r in rs}),
        "versions": vlist,
    })

out.sort(key=lambda r: r["title"].lower())
json.dump(out, open(f"{ROOT}/site/games.json", "w"), ensure_ascii=False, separators=(",", ":"))
nv = sum(len(r["versions"]) for r in out)
print(f"games (grouped): {len(out)}  versions total: {nv}")
print(f"  with year: {sum(1 for r in out if r['year'])}  genre: {sum(1 for r in out if r['genre'])}  players: {sum(1 for r in out if r['players'])}")
print(f"  multi-version games: {sum(1 for r in out if len(r['versions']) > 1)}  multi-platform: {sum(1 for r in out if len(r['platforms']) > 1)}")
print(f"  modes: sim {sum(1 for r in out if r['sim'])}  co-op {sum(1 for r in out if r['coop'])}  comp {sum(1 for r in out if r['comp'])}")

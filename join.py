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

# Set-name aliases: a core's instance file can carry a non-MAME name for a
# known set (atrac17's Combatribes core ships "combatribes"; MAME's set is
# "ctribe"). Aliasing restores the game's full metadata (Syl, 2026-11-23).
SET_ALIASES = {"combatribes": "ctribe",
               # pram0d's Turtles in Time core suffixes its EU sets with _ap
               "tmht22pe_ap": "tmht22pe", "tmht24pe_ap": "tmht24pe"}
for _a, _b in SET_ALIASES.items():
    if _a in wanted:
        wanted.add(_b)

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

# ---- title -> set resolver (Syl approved, 2026-11-23) ----------------------
# Some cores ship no MAME set name (single-game cores, Namco System 11,
# several Neo Geo lists), only a title: their games got no metadata and no
# screenshot, since everything is keyed on the set. When the instance title
# matches exactly ONE non-bootleg MAME parent title, attach that set; when
# the title literally IS a set name (Midway cores name their files by set),
# attach it. Bootleg parents are excluded (a "Fatal Fury Special" record
# must not root on the fatfurspb bootleg) and ambiguous titles never match.
def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", base_title(t).lower()).strip()

_parent_titles = {}
for _ev, el in ET.iterparse(f"{ROOT}/raw/mame.xml", events=("end",)):
    if el.tag != "machine":
        continue
    if not el.get("cloneof"):
        _desc = (el.findtext("description") or "")
        if "bootleg" not in _desc.lower():
            _parent_titles.setdefault(norm_title(_desc), []).append(el.get("name", "").lower())
    el.clear()
PARENT_BY_TITLE = {k: v[0] for k, v in _parent_titles.items() if len(v) == 1}

RESOLVER_FILENAME_DENY = {"tetris"}   # the Neo Geo Tetris is a homebrew, not the arcade set
_resolved = 0
for core in data:
    for g in core["games"]:
        s = (g.get("setname") or g.get("setname_hint") or "").lower() or None
        if s and (s in cloneof or s in SET_ALIASES):
            continue
        t = (g.get("title") or "").strip()
        new = None
        if re.fullmatch(r"[a-z0-9_]+", t.lower()) and t.lower() in cloneof \
                and t.lower() not in RESOLVER_FILENAME_DENY:
            new = t.lower()
        elif norm_title(t) in PARENT_BY_TITLE:
            new = PARENT_BY_TITLE[norm_title(t)]
        if new:
            g["setname"] = new
            wanted.add(new)
            _resolved += 1
print(f"title->set resolver: {_resolved} records attached")

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
    # catver's "Fighter / 2D" bucket is side-scrolling action, NOT versus
    # fighting (Syl flagged Mystic Warriors, 2026-11-23; whole class fixed).
    "mystwarr": ["Run 'n' Gun"],        # Konami run 'n' gun (Sunset Riders kin)
    "loht": ["Platformer"],             # Legend of Hero Tonma
    "nspirit": ["Platformer"],          # Ninja Spirit
    "lkage": ["Platformer"],            # The Legend of Kage
    "edrandy": ["Platformer"],          # Edward Randy (whip action)
    "myhero": ["Beat 'em Up"],
    "splatter": ["Beat 'em Up"],        # Splatter House
    "superman": ["Beat 'em Up"],        # Taito Superman
    "wndrmomo": ["Beat 'em Up"],        # Wonder Momo
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
SW_LISTS = {
    "nes": "nes", "famicom_flop": "fds", "snes": "snes",
    "megadriv": "megadriv", "sms": "sms",
    "gamegear": "gamegear", "gameboy": "gameboy", "gbcolor": "gbcolor",
    "gba": "gba", "pce": "pce",
    "tg16": "pce", "pcecd": "pcecd",
    "segacd": "segacd", "32x": "32x", "saturn": "saturn",
    "psx": "psx", "n64": "n64", "a2600": "a2600",
    "a7800": "a7800", "lynx": "lynx", "coleco": "coleco",
    "intv": "intv", "vectrex": "vectrex",
    "ngp": "ngp", "ngpc": "ngp",
    "wswan": "wswan", "wscolor": "wswan",
    "msx1_cart": "msx", "msx2_cart": "msx",
    # SuperGrafx games run on the Pocket's PC Engine core; SG-1000 and
    # Amstrad CPC are Pocket platforms too (added 2026-11-23 after Syl
    # spotted 1941's SuperGrafx port missing).
    "sgx": "pce", "sg1000": "sg1000",
    "cpc_cass": "cpc", "cpc_flop": "cpc",
    "c64_cart": "c64", "c64_cass": "c64",
    "amigaocs_flop": "amiga", "spectrum_cass": "spectrum",
}
# Display names (Syl, 2026-11-23). A (jp, west) pair renders region-aware:
# only Japanese releases -> the Japanese name alone (SFC), only Western
# releases -> the Western name alone (SNES), both or unknown -> "SFC / SNES".
SW_LABELS = {
    "nes": ("Famicom", "NES"), "snes": ("SFC", "SNES"),
    "pce": ("PCE", "TG16"), "pcecd": ("PCECD", "TGCD"),
    "megadriv": "Mega Drive / Genesis", "sms": "Master System",
    "gamegear": "Game Gear", "gameboy": "GB", "gbcolor": "GBC",
    "gba": "GBA", "fds": "FDS",
    "segacd": "Mega CD / Sega CD", "32x": "32X", "saturn": "Saturn",
    "psx": "PlayStation", "n64": "Nintendo 64", "a2600": "Atari 2600",
    "a7800": "Atari 7800", "lynx": "Atari Lynx", "coleco": "ColecoVision",
    "intv": "Intellivision", "vectrex": "Vectrex",
    "ngp": "Neo Geo Pocket / Color", "wswan": "WonderSwan / Color",
    "msx": "MSX", "sg1000": "SG-1000",
    "cpc": "Amstrad CPC", "c64": "C64",
    "amiga": "Amiga", "spectrum": "ZX Spectrum",
}
# ports_exceptions.json still uses the earlier display labels.
LEGACY_PORT_LABELS = {
    "NES / Famicom": "nes", "SNES / Super Famicom": "snes",
    "PC Engine / TurboGrafx-16": "pce", "PC Engine CD / TurboGrafx-CD": "pcecd",
    "Game Boy": "gameboy", "Game Boy Color": "gbcolor",
    "Game Boy Advance": "gba", "Commodore 64": "c64",
}
def port_system(label):
    """Map an exceptions-file label (old or new vocabulary) to a system key;
    unknown labels (e.g. X68000, which has no software list) pass through."""
    if label in LEGACY_PORT_LABELS:
        return LEGACY_PORT_LABELS[label]
    for k, v in SW_LABELS.items():
        if v == label or (isinstance(v, tuple) and label in (v[0], v[1], f"{v[0]} / {v[1]}")):
            return k
    return label
def port_label(syskey, flags):
    lab = SW_LABELS.get(syskey, syskey)
    if isinstance(lab, tuple):
        if flags and flags.get("jp") and not flags.get("west"):
            return lab[0]
        if flags and flags.get("west") and not flags.get("jp"):
            return lab[1]
        return f"{lab[0]} / {lab[1]}"
    return lab
def sw_regions(desc):
    """Regions from the (…) groups of a software-list description."""
    txt = " ".join(re.findall(r"\(([^)]*)\)", desc))
    jp = "Japan" in txt or "World" in txt
    west = any(w in txt for w in ("USA", "Europe", "World", "Australia", "Canada"))
    return jp, west
sw_index = {}
os.makedirs(f"{ROOT}/raw/swlists", exist_ok=True)
for fname, syskey in SW_LISTS.items():
    path = f"{ROOT}/raw/swlists/{fname}.xml"
    if not os.path.exists(path):
        try:
            import urllib.request
            urllib.request.urlretrieve(
                f"https://raw.githubusercontent.com/mamedev/mame/mame0264/hash/{fname}.xml", path)
        except Exception as e:
            print(f"software list {fname}: download failed ({e})")
            continue
    # The pce/sgx lists carry no region annotations, but membership in the
    # PC Engine list IS a Japanese release (and tg16 membership a Western
    # one) — use the list itself as the region signal there.
    list_region = {"pce": "jp", "sgx": "jp", "tg16": "west"}.get(fname)
    try:
        for sw in ET.parse(path).getroot().iter("software"):
            desc = (sw.findtext("description") or "").strip()
            if desc:
                jp, west = sw_regions(desc)
                if list_region == "jp":
                    jp = True
                elif list_region == "west":
                    west = True
                slot = sw_index.setdefault(norm_title(desc), {}).setdefault(
                    syskey, {"jp": False, "west": False})
                slot["jp"] |= jp
                slot["west"] |= west
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
    author = core.get("author") or core["core_id"].split(".", 1)[0]
    label = core["core_id"].split(".", 1)[1] if "." in core["core_id"] else core["core_id"]
    if label.endswith("_Analogizer"):
        continue  # Analogizer variants duplicate their base core (Syl, 2026-11-23): not listed
    board = core.get("board") or (core["platforms"][0] if core["platforms"] else label)
    for g in core["games"]:
        s = (g.get("setname") or g.get("setname_hint") or "").lower() or None
        records.append({
            "title": g["title"], "set": s, "core": label, "core_id": core["core_id"],
            "author": author, "board": board, "repo": core.get("repo"),
            "alt": g["set_type"] == "alternative",
            "patreon": bool(core["requires_license"]),
        })

# ---- Wikipedia article link (Syl, 2026-11-23): icon in the Game column.
# Stamp only when the cached article title matches the game title exactly
# (normalized), or the key is in WIKI_ALLOW: hand-checked same-game articles
# under an alternate title (e.g. Vulcan Venture -> "Gradius II"). Everything
# else the search coughed up (companies, films, disambiguation pages, the
# original a port was adapted from...) gets no icon.
WIKI_ALLOW = {
    "88games", "1942", "asteroid", "tekken", "xenophob", "llander", "tron",
    "cloak", "indytemp", "tempest", "chelnov", "devilw", "demonwld",
    "1943kai", "2020bb", "bakutotu", "breakrev", "bublbob2", "cninja",
    "chukatai", "title:cloak dagger", "title:combatribes", "dankuga",
    "dkongjr", "ddux", "eightman", "fastlane", "genpeitd", "title:get star",
    "hwrace", "hsf2", "kingdmgp", "landmakr", "title:last blade the",
    "fitegolf", "lightbr", "makaimurbbl", "maniach", "mmaze", "mmatrix",
    "megaman2", "megaman", "mpang", "title:mortalkombat", "mbombrd",
    "nbajamte", "neomrdo", "pang3", "panicbom", "pistoldm", "pitfall2",
    "pleiads", "ws", "pzloop2", "puzzldpr", "rallybik", "roadblst",
    "skykiddx", "smashtv", "sfa",
    "title:street fighter ii special champion edition", "sf2hf", "sf2",
    "sfzch", "sfz2al", "title:strikeforce", "sbagman", "ssf2", "sxevious",
    "szaxxon", "pwrgoal", "title:top hunter", "tumblep", "toutrun", "vsav2",
    "vulcan", "wizdfire", "wrally2", "wrestwar",
}
wiki_cache = {}
_wc = f"{ROOT}/raw/wiki_cache.json"
if os.path.exists(_wc):
    wiki_cache = json.load(open(_wc))

def wiki_url(key, title, regional):
    w = wiki_cache.get(key)
    if not w or not w.get("article"):
        return None
    art = w["article"]
    titles = {norm_title(title)} | {norm_title(e["t"]) for e in (regional or [])}
    if norm_title(art) in titles or key in WIKI_ALLOW:
        return "https://en.wikipedia.org/wiki/" + art.replace(" ", "_")
    return None

# ---- Core column: platform name + author(s), each author linked to the
# GitHub REPOSITORY of their core for that platform (Syl, 2026-11-23 —
# not the author's profile page). When an author has several cores on one
# platform, prefer the repo they own themselves (e.g. Mazamars312's own
# NeoGeo repo over the Analogizer fork's repo).
def _core_authors(rs):
    repos = {}
    for r in rs:
        repos.setdefault(r["board"], {}).setdefault(r["author"], set())
        if r["repo"]:
            repos[r["board"]][r["author"]].add(r["repo"])
    out = []
    for board, authors in sorted(repos.items()):
        lst = []
        for name, rset in sorted(authors.items()):
            pick = next((x for x in sorted(rset) if x.split("/")[0].lower() == name.lower()),
                        sorted(rset)[0] if rset else None)
            lst.append({"name": name,
                        "url": f"https://github.com/{pick}" if pick else None})
        out.append({"platform": board, "authors": lst})
    # Curated extra credit (Syl, 2026-11-23): Mazamars' Neo Geo core plays the
    # whole Neo Geo library, including the few sets only NeoMillie's list
    # carries — credit him on every Neo Geo entry.
    for entry in out:
        if entry["platform"] == "Neo Geo" and \
                not any(a["name"] == "Mazamars312" for a in entry["authors"]):
            entry["authors"].append({"name": "Mazamars312",
                "url": "https://github.com/Mazamars312/Analogue_Pocket_Neogeo"})
            entry["authors"].sort(key=lambda a: a["name"])
    return out

for r in records:
    if r["set"] in SET_ALIASES:
        r["set"] = SET_ALIASES[r["set"]]

# CPS Changer sets are CPS-1.5 hardware, wherever the core ships them
# (Jotego bundles the Changer Street Fighter Zero sets with his CPS-1 core;
# Syl, 2026-11-23: they belong under CPS-1.5, not CPS-1).
for r in records:
    if r["set"] and meta.get(r["set"]) and "CPS Changer" in (meta[r["set"]]["desc"] or ""):
        r["board"] = "Capcom CPS-1.5"

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

# phase 3: curated merges — same game, but MAME keeps two parents (Syl,
# 2026-11-23: the CPS Changer "Street Fighter Zero" sets are the same game
# as Street Fighter Alpha: Warriors' Dreams).
GROUP_MERGES = {"sfzch": "sfa",
                # silkwrmj (Japan set) is unknown to MAME 0.264, so its
                # record lands in a title group; it is the same game.
                "title:silkworm": "silkworm",
                # Gaelco renamed its World Rally sets after MAME 0.264;
                # current MAME (via Arcade Database) lists these as clones
                # of wrally / wrally2 (Syl approved the merge, 2026-11-23).
                "wrallyac": "wrally", "wrallyata": "wrally",
                "wrallyd": "wrally", "wrallye": "wrally",
                "wrally2b": "wrally2", "wrally2c": "wrally2",
                "wrally2d": "wrally2",
                # Same story for Gradius III: gradius3ja / gradius3jas are
                # post-0.264 names for extra Japanese revisions of gradius3.
                "gradius3ja": "gradius3", "gradius3jas": "gradius3"}
for src_k, dst_k in GROUP_MERGES.items():
    if src_k in groups and dst_k in groups:
        groups[dst_k].extend(groups.pop(src_k))
        print(f"phase3 merge: {src_k} -> {dst_k}")

# Curated display titles (Syl): the name the game is known by beats the MAME
# parent's original-region name (Puck Man is the Japanese original, but the
# entry must read Pac-Man).
TITLE_OVERRIDES = {"puckman": "Pac-Man"}

# Unofficial hacks (Syl, 2026-11-23): hidden by default on the site, behind
# a "Show unofficial hacks" checkbox. Detection: the [HBMAME] / "- HBMame"
# tags the cores themselves put in the game titles, plus this curated list
# of untagged hacks. Homebrew ORIGINAL games (Xeno Crisis, Frog Feast,
# NeoTRIS...) are NOT hacks and stay visible.
HACK_TITLES = {"Xevious 2002", "Xevious 2003", "Xevious 2004",
               "Xevious 2005", "Xevious Black",
               "Street Fighter II' Champion Re-Edit",
               "SNK vs. Capcom Remix Ultra", "Windjammers Supersonic"}

out = []
for key, rs in groups.items():
    parent_set = key if not key.startswith("title:") else None
    pm = meta.get(parent_set) if parent_set else None
    # canonical title: parent's MAME description, else a member's title
    if pm and pm["desc"]:
        title = base_title(pm["desc"])
    else:
        title = base_title(rs[0]["title"])
    if parent_set in TITLE_OVERRIDES:
        title = TITLE_OVERRIDES[parent_set]
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
    home_sys = {}
    for k in {norm_title(title)} | {norm_title(e["t"]) for e in regional_list}:
        for sk, fl in sw_index.get(k, {}).items():
            cur = home_sys.setdefault(sk, {"jp": False, "west": False})
            cur["jp"] |= fl["jp"]
            cur["west"] |= fl["west"]
    exc_key = parent_set or ("title:" + norm_title(title))
    for lab in ports_exc.get("add", {}).get(exc_key, []):
        home_sys.setdefault(port_system(lab), None)
    for lab in ports_exc.get("remove", {}).get(exc_key, []):
        home_sys.pop(port_system(lab), None)
    home = {port_label(sk, fl) for sk, fl in home_sys.items()}
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
        "wiki": wiki_url(parent_set or ("title:" + norm_title(title)), title, regional_list),
        "patreon": any(v["patreon"] for v in vlist),
        "hack": ("[HBMAME]" in title or "- HBMame" in title
                 or title in HACK_TITLES),
        "has_main": any(not v["alt"] for v in vlist),
        "platforms": platforms,
        "core_authors": _core_authors(rs),
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

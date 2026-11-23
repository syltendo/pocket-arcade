#!/usr/bin/env python3
"""Join dataset v0 with MAME metadata -> site data file (grouped).

One entry per GAME: all versions (parent set + clones/alternates, across all
cores) are merged into a single record whose "versions" list names each set,
and "platforms" lists every Pocket platform/core combination running it.

Inputs : data/games-v0.json, raw/mame.xml (MAME 0.264 -listxml), raw/catver.ini
Output : site/games.json
"""
import json, re
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

full = wanted | {root(s) for s in wanted}
meta = {}
for _ev, el in ET.iterparse(f"{ROOT}/raw/mame.xml", events=("end",)):
    if el.tag != "machine":
        continue
    name = el.get("name", "").lower()
    if name in full:
        disp = el.find("display")
        inp = el.find("input")
        meta[name] = {
            "desc": (el.findtext("description") or "").strip(),
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

def base_title(desc):
    return re.sub(r"\s*\([^)]*\)\s*$", "", desc).strip()

def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", base_title(t).lower()).strip()

def suffix(desc):
    m = re.search(r"\(([^)]*)\)\s*$", desc)
    return m.group(1) if m else ""

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
        })
        v["cores"].add(r["core"] if r["board"].lower() == r["core"].lower() else f"{r['board']} · {r['core']}")
        v["alt"] = v["alt"] and r["alt"] and (r["set"] != parent_set)
        v["patreon"] = v["patreon"] or r["patreon"]
    vlist = sorted(versions.values(), key=lambda v: (v["alt"], v["set"] or v["title"]))
    for v in vlist:
        v["cores"] = sorted(v["cores"])
    platforms = sorted({c for v in vlist for c in v["cores"]})
    out.append({
        "title": title,
        "set": parent_set,
        "year": (src or {}).get("year") or None,
        "manufacturer": (src or {}).get("manufacturer") or None,
        "players": (src or {}).get("players") or None,
        "buttons": (src or {}).get("buttons") or None,
        "vertical": (src or {}).get("vertical") if src else None,
        "genre": cat or None,
        "genre_top": cat.split(" / ")[0] if cat else None,
        "patreon": any(v["patreon"] for v in vlist),
        "has_main": any(not v["alt"] for v in vlist),
        "platforms": platforms,
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

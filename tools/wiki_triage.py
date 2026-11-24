#!/usr/bin/env python3
"""Pre-triage of wiki_candidates.json — sorts Wikipedia's home-port claims
into 'probablement vrai', 'probablement faux' and 'incertain', each with its
reason, so a human only has to validate instead of researching from scratch.

Main automated signal: a fuzzy title match in the SAME system's MAME
software list (the exact-title pass in join.py missed subtitle/variant
titles, e.g. arcade "Bad Dudes vs. Dragonninja" vs NES "Bad Dudes").
Nothing here is applied to the site; validated lines still go through
ports_exceptions.json.
"""
import json, os, re
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


def base_title(t):
    while True:
        t2 = re.sub(r"\s*\([^)]*\)\s*$", "", t).strip()
        if t2 == t:
            return t
        t = t2


def norm(t):
    return re.sub(r"[^a-z0-9]+", " ", base_title(t).lower()).strip()


def tokens(t):
    return set(norm(t).split()) - {"the", "a", "an", "of"}


# software titles per system label
sw = {}
for fname, label in SW_SYSTEMS.items():
    path = f"{ROOT}/raw/swlists/{fname}.xml"
    if not os.path.exists(path):
        continue
    titles = sw.setdefault(label, {})
    for node in ET.parse(path).getroot().iter("software"):
        desc = (node.findtext("description") or "").strip()
        if desc:
            titles.setdefault(norm(desc), desc)
print("software titles per system loaded")

games = {g["set"] or ("title:" + norm(g["title"])): g
         for g in json.load(open(f"{ROOT}/site/games.json"))}
cand = json.load(open(f"{ROOT}/wiki_candidates.json"))

rows = []
for entry in cand["wiki_adds"]:
    g = games.get(entry["set"] or ("title:" + norm(entry["title"])))
    keys = [g["title"]] + [e["t"] for e in (g.get("regional") or [])] if g else [entry["title"]]
    key_tokens = [tokens(k) for k in keys]
    for system in entry["adds"]:
        verdict, reason = "incertain", "aucun recoupement trouvé"
        titles = sw.get(system)
        if titles is None:
            reason = "pas de software list pour ce système (X68000…)"
        else:
            for ntok in key_tokens:
                if not ntok:
                    continue
                for stitle_norm, stitle in titles.items():
                    stok = tokens(stitle)
                    if not stok:
                        continue
                    if (ntok <= stok or stok <= ntok) and min(len(ntok), len(stok)) >= 1 \
                            and not (len(ntok) == 1 and len(stok) > 1 and len(next(iter(ntok))) < 5):
                        verdict = "probablement vrai"
                        reason = f"la liste {system} contient « {stitle} » (titre variante)"
                        break
                if verdict != "incertain":
                    break
        rows.append({"title": entry["title"], "set": entry["set"],
                     "system": system, "verdict": verdict, "reason": reason})

order = {"probablement vrai": 0, "incertain": 1, "probablement faux": 2}
rows.sort(key=lambda r: (order[r["verdict"]], r["title"], r["system"]))
json.dump(rows, open(f"{ROOT}/wiki_triage.json", "w"), ensure_ascii=False, indent=1)
with open(f"{ROOT}/wiki_triage.md", "w") as f:
    f.write("# Pré-tri des candidats Wikipedia — à valider par un humain\n\n")
    f.write("Rien n'est appliqué automatiquement. Une ligne validée devient une entrée "
            "« add » de ports_exceptions.json.\n")
    for v in ("probablement vrai", "incertain", "probablement faux"):
        sel = [r for r in rows if r["verdict"] == v]
        f.write(f"\n## {v} ({len(sel)} portages prétendus)\n\n")
        for r in sel:
            f.write(f"- **{r['title']}** → {r['system']} — {r['reason']}\n")
from collections import Counter
print(Counter(r["verdict"] for r in rows))
print("total claims:", len(rows))

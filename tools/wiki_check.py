#!/usr/bin/env python3
"""Wikipedia cross-check for home ports — CANDIDATES ONLY, nothing is applied.

For each game in site/games.json, find its English Wikipedia article, read the
infobox "platforms" field, map the names to the site's system labels, and
diff against the published home_ports (which come from the MAME software
lists + ports_exceptions.json).

Output: wiki_candidates.json + wiki_candidates.md with
  - "wiki_adds": systems Wikipedia claims that the software lists don't have
  - "wiki_misses": systems the software lists have that Wikipedia doesn't
    mention (informational only — software lists are the stronger source)

Syl's rule (2026-11-23): Wikipedia is a cross-check, never an automatic
source. A candidate only reaches the site after human validation, by adding
it to ports_exceptions.json. Article results are cached in
raw/wiki_cache.json so reruns are cheap and resumable.
"""
import json, os, re, sys, time
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET  # noqa: F401  (kept for parity with join.py)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://en.wikipedia.org/w/api.php"
UA = {"User-Agent": "PocketArcadeDB-wiki-check/0.1 (cross-check tool; contact: site owner)"}

PLATMAP = [
    ("NES / Famicom", ["Nintendo Entertainment System", "Famicom", "NES"]),
    ("SNES / Super Famicom", ["Super Nintendo Entertainment System", "Super Famicom", "SNES"]),
    ("Mega Drive / Genesis", ["Sega Genesis", "Mega Drive"]),
    ("Master System", ["Master System"]),
    ("Game Gear", ["Game Gear"]),
    ("Game Boy", ["Game Boy"]),
    ("Game Boy Color", ["Game Boy Color"]),
    ("Game Boy Advance", ["Game Boy Advance"]),
    ("PC Engine / TurboGrafx-16", ["TurboGrafx-16", "PC Engine"]),
    ("PC Engine CD / TurboGrafx-CD", ["TurboGrafx-CD", "PC Engine CD", "Super CD-ROM"]),
    ("Mega CD / Sega CD", ["Sega CD", "Mega-CD", "Mega CD"]),
    ("32X", ["32X"]),
    ("Saturn", ["Sega Saturn"]),
    ("PlayStation", ["PlayStation (console)", "PlayStation"]),
    ("Nintendo 64", ["Nintendo 64"]),
    ("Atari 2600", ["Atari 2600"]),
    ("Atari 7800", ["Atari 7800"]),
    ("Atari Lynx", ["Atari Lynx"]),
    ("ColecoVision", ["ColecoVision"]),
    ("Intellivision", ["Intellivision"]),
    ("Vectrex", ["Vectrex"]),
    ("Neo Geo Pocket / Color", ["Neo Geo Pocket"]),
    ("WonderSwan / Color", ["WonderSwan"]),
    ("MSX", ["MSX"]),
    ("Commodore 64", ["Commodore 64"]),
    ("Amiga", ["Amiga"]),
    ("ZX Spectrum", ["ZX Spectrum"]),
    ("X68000", ["X68000"]),
]
# longest keys first so "Game Boy Color" wins over "Game Boy", etc.
PLATKEYS = sorted(((k, label) for label, keys in PLATMAP for k in keys),
                  key=lambda x: -len(x[0]))


def api(params):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def norm(t):
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def base_title(t):
    while True:
        t2 = re.sub(r"\s*\([^)]*\)\s*$", "", t).strip()
        if t2 == t:
            return t
        t = t2


def article_ok(article, title):
    """Reject series/company/wrong-game articles: the article title must be
    the game title, optionally with a parenthetical disambiguator."""
    a = norm(base_title(article))
    g = norm(title)
    return a == g


def find_article(title):
    for cand in (title, f"{title} (video game)", f"{title} (arcade game)"):
        try:
            d = api({"action": "parse", "page": cand, "prop": "wikitext",
                     "section": 0, "format": "json", "redirects": 1})
            if "parse" in d:
                return d["parse"]["title"], d["parse"]["wikitext"]["*"]
        except Exception:
            pass
    try:
        d = api({"action": "query", "list": "search",
                 "srsearch": f'"{title}" arcade video game', "srlimit": 3, "format": "json"})
        for hit in d.get("query", {}).get("search", []):
            if article_ok(hit["title"], title):
                d2 = api({"action": "parse", "page": hit["title"], "prop": "wikitext",
                          "section": 0, "format": "json", "redirects": 1})
                if "parse" in d2:
                    return d2["parse"]["title"], d2["parse"]["wikitext"]["*"]
    except Exception:
        pass
    return None, None


def platforms_from_wikitext(wt):
    m = re.search(r"\|\s*platforms?\s*=\s*(.+)", wt or "")
    if not m:
        return None
    raw = m.group(1)
    blob = " | ".join(re.findall(r"\[\[([^\]|]+)", raw)) or re.sub(
        r"\{\{[^}]*\}\}", " ", raw)
    out = set()
    low = blob.lower()
    claimed = []
    for key, label in PLATKEYS:
        i = low.find(key.lower())
        if i >= 0:
            claimed.append((i, key, label))
    claimed.sort()
    used = []
    for i, key, label in claimed:
        if any(i < u2 and i + len(key) > u1 for u1, u2 in used):
            continue
        used.append((i, i + len(key)))
        out.add(label)
    return sorted(out)


def main():
    games = json.load(open(f"{ROOT}/site/games.json"))
    cache_path = f"{ROOT}/raw/wiki_cache.json"
    cache = {}
    if os.path.exists(cache_path):
        cache = json.load(open(cache_path))
    results = {"wiki_adds": [], "wiki_misses": [], "no_article": 0, "no_platforms": 0}
    for n, g in enumerate(games, 1):
        title = g["title"]
        key = g["set"] or ("title:" + norm(title))
        if key in cache:
            wiki = cache[key]
        else:
            art, wt = find_article(title)
            plats = platforms_from_wikitext(wt) if wt else None
            wiki = {"article": art, "platforms": plats}
            cache[key] = wiki
            if n % 25 == 0:
                json.dump(cache, open(cache_path, "w"), ensure_ascii=False)
                print(f"  {n}/{len(games)} checked", flush=True)
            time.sleep(0.15)
        if not wiki.get("article"):
            results["no_article"] += 1
            continue
        if wiki.get("platforms") is None:
            results["no_platforms"] += 1
            continue
        cur = set(g.get("home_ports") or [])
        wk = set(wiki["platforms"])
        adds = sorted(wk - cur)
        misses = sorted(cur - wk)
        if adds:
            results["wiki_adds"].append(
                {"title": title, "set": g["set"], "article": wiki["article"], "adds": adds})
        if misses:
            results["wiki_misses"].append(
                {"title": title, "set": g["set"], "article": wiki["article"], "misses": misses})
    json.dump(cache, open(cache_path, "w"), ensure_ascii=False)
    json.dump(results, open(f"{ROOT}/wiki_candidates.json", "w"), ensure_ascii=False, indent=1)
    with open(f"{ROOT}/wiki_candidates.md", "w") as f:
        f.write("# Wikipedia cross-check — candidates for human validation\n\n")
        f.write("Nothing here is applied automatically. A line becomes real only when it is "
                "added to ports_exceptions.json after validation.\n\n")
        f.write(f"## Wikipedia claims a port the software lists don't have "
                f"({len(results['wiki_adds'])} games)\n\n")
        for r in results["wiki_adds"]:
            f.write(f"- **{r['title']}** ({r['set']}): {', '.join(r['adds'])} — "
                    f"[[{r['article']}]]\n")
        f.write(f"\n## Software lists have a port Wikipedia doesn't mention "
                f"({len(results['wiki_misses'])} games, informational)\n\n")
        for r in results["wiki_misses"]:
            f.write(f"- **{r['title']}** ({r['set']}): {', '.join(r['misses'])}\n")
    print(f"done: {len(results['wiki_adds'])} games with wiki-only claims, "
          f"{len(results['wiki_misses'])} with list-only, "
          f"{results['no_article']} no article, {results['no_platforms']} no platforms field")


if __name__ == "__main__":
    sys.exit(main())

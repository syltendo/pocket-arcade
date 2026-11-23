# Pocket Arcade Database

A searchable database of every arcade game playable on the **Analogue Pocket** through openFPGA cores — with the core and platform that run each game.

**Live site:** https://syltendo.github.io/pocket-arcade-db/

## What it does

- Instant search by game title or MAME set name.
- Filters: genre, number of players, publisher / developer, year (decade), core, core author, platform / board, screen orientation (horizontal / vertical-Tate), main sets vs all sets (alternatives are shown by default).
- Beta / Patreon cores are included and badged.
- Each game lists every other Pocket platform · core combination that runs the same MAME set ("Also on").

## Data sources

- [openFPGA Library](https://openfpga-library.github.io/analogue-pocket/) API — the core catalogue; each core's game list is extracted from the instance files inside its own latest release.
- MAME 0.264 (`-listxml`) — year, manufacturer, players, buttons, screen orientation, clone relationships.
- [progettoSNAPS catver](https://www.progettosnaps.net/catver/) — genre per MAME set.
- Jotego's [jtbin game_list.md](https://github.com/jotego/jtbin/blob/master/game_list.md) — set names for Jotego cores.

Metadata only — this project distributes no ROMs.

## Regenerating the data

```sh
python3 tools/collect.py   # Library API + release zips -> data/games-v0.json
python3 tools/join.py      # + MAME xml & catver.ini   -> site/games.json
```

Prototype built 2026-11-23: 240 arcade cores, 804 games (2,021 versions grouped under their parent game).

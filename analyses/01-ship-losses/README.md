# 01 — Ship losses map

**Question.** Where were ships lost between 1400 and 2030 (map opens on
1500–1860, the project's Age of Sail window), who owned them when they were
lost, where did they come from, and why did they sink?

This analysis builds one table of ship losses from every downloaded source
except Three Decks, then plots it on an interactive world map. Every derived
value keeps its raw source text and the id of the source record.

## Inputs

Read from `data/raw/` (never written back). The source ids, tier and licence
are taken from `fetch/manifest.yaml` and the fetcher's `_provenance.json`.

| Source id | Tier | Licence | Notes |
|---|---|---|---|
| `ukho-wrecks-extra` | T1 | OGL | Quoted TSV in the extra zip; `circumstances_of_loss` free text |
| `wa-shipwrecks` | T1 | CC-BY-4.0 | 305 point features, controlled `sunk_code` |
| `zenodo-shipwrecks` | T3 | CC-BY-4.0 | 4,463 rows, `lat;lon` with a trailing U+FEFF |
| `wp-en-shipwrecks` | T3 | CC-BY-SA-4.0 | Yearly lists, `Ship/State/Description` tables (needs network) |
| `slavevoyages` | T1 | Public domain; imputed fields CC-BY-NC | `FATE` codes; ownership and captors |
| `prize-papers` | T1 | Metadata terms unstated | Captures, not sinkings; `redistribute=false` |
| `ireland-wiid` | T1 | CC-BY-4.0 | BOM CSV; only 146 losses ≤1860 have coordinates |
| `ireland-infomar` | T1 | CC-BY-4.0 | Surveyed coordinates that donate to WIID rows |
| `emodnet-shipwrecks` | T1 | CC-BY-4.0 | 7,073 points; `"n/a"` means null |
| `novascotia-shipwrecks` | T1 | NS-Open-Government-Licence | Text locations geocoded within Nova Scotia |
| `dutch-asiatic-shipping` | T1 | None stated | VOC voyages; `redistribute=false` |
| `todo-a-babor` | T2 | None stated | Spanish losses and British prizes; `redistribute=false` |
| `ibm-maritime-archives` | T3 | Apache-2.0 | 710 DAS cross-checks + 120 curated wrecks |
| `wikidata` | T3 | CC0-1.0 | Optional battle gazetteer |
| `geonames`, `naturalearth` | T1 | CC-BY-4.0 / public domain | Geocoding gazetteers (plan Phase 0.3) |

Three Decks is out of scope (`data/raw/threedecks/` is reserved). Lloyd's List
OCR is deferred to a later NLP pass.

## Method

```
build.py --source ID --stage extract|geocode|ownership|dedupe|map|all
```

- **Extract** (`shiplosses/sources/`): a pure function over local files with no
  network access, returning DataFrames in the shared schema. Source fields used
  are kept in `raw`. Unknown coded values are counted, never dropped silently.
- **Normalise** (`shiplosses/normalize/`): partial dates, degrees-and-decimal
  minutes and other coordinate formats, ship names, polities, cause classes
  (`data/cause_rules.csv`) and location phrases.
- **Geocode** (`geocode.py`): source coordinates, then `data/place_overrides.csv`,
  source gazetteers, and — when downloaded — GeoNames and Natural Earth marine
  areas. Online Nominatim is off by default (`--online-geocode`).
- **Ownership** (`ownership.py`): links `ownership_events` to losses by name
  similarity, date window and matching polity.
- **De-duplicate** (`dedupe.py`): deterministic joins (WIID = INFOMAR =
  EMODnet Irish; IBM `maarer:<n>` = DAS `Number`) then fuzzy clusters.
- **Map** (`mapping/`): `outputs/map.html` (Leaflet, canvas, embedded data) and
  `outputs/map_<period>.png` small multiples.

Outputs go to `outputs/` and are gitignored. Only code, the curated `data/`
tables and synthetic fixtures are committed.

## Rebuild

```
just ship-losses                 # full offline rebuild
just ship-losses --stage extract # one stage
just ship-losses --redistributable-only
```

## Status and known gaps

- Offline rebuild works from `data/raw/`; a second run produces identical tables.
- Wikipedia lists and Wikidata are not downloaded yet, so those extractors
  contribute nothing offline; the Wikipedia parser is covered by a synthetic
  test against the documented page layout.
- Prize Papers event pages (the ship-to-capture link) require the Phase 0.2
  harvester extension to be fetched; until then Prize Papers contributes
  captures without the linking events.
- The GeoNames and Natural Earth gazetteers require the Phase 0.3 download;
  offline geocoding otherwise relies on source coordinates and overrides.
- SlaveVoyages imputed variables and every non-redistributable source are
  dropped by `--redistributable-only`.

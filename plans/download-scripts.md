# Plan: scripts to download the Age of Sail datasets

Scope: every source in [Age of Sail GIS datasets.md](../Age%20of%20Sail%20GIS%20datasets.md) **except Three Decks** (threedecks.org and eicships.threedecks.org), which another agent owns. This plan covers fetching raw data and recording where it came from. Parsing, geocoding and building the loss-event table come later.

All endpoint checks below were run from this machine on 2026-10-02.

---

## 1. What the endpoint checks changed

Several findings change the research doc's conclusions. Read these before building anything.

| # | Finding | Effect on the plan |
|---|---|---|
| 1 | **The Prize Papers portal is open.** It returned 200, not 403. It runs Goobi viewer with a public REST API (`/api/v1/`, OpenAPI spec at `/api/v1/openapi.json`, 43,930 indexed docs). The index has `MD_CAPTURE_PLACE`, `MD_CAPTURE_DATE_START/END`, `MD_CAPTURE_CONFISCATING_ACTOR`, `MD_SHIP_FLAG`, `MD_GEO_POINT`, `MD_ALL_COORDS_FOR_SPATIALSEARCH` and `MD_EVENT_SLAVEVOYAGES_VOYAGE_ID`. A case study lists **~130 Spanish ships captured by Britain** (War of the Austrian Succession). | It becomes the **highest-value source** for the capture layer and gets its own harvester (§5.1). `robots.txt` disallows `/search/` and `/oai`, so use the API only. Terms limit **images** to research, private study or education, so fetch metadata only. |
| 2 | **Wikidata P1028 is "donated by", not "destroyed by".** The doc's 17,293 count is meaningless for losses. Of the 2,039 items with a Three Decks ID (P11085), only **7** have P17 or P8047 set to Spain (Q29), **59** have coordinates (P625), and 2,037 have P793 (significant event; mostly launchings, untested). | The Wikidata spine is thinner than the doc hoped. The harvester pulls full entity JSON and does not rely on P11085 alone (§5.2). |
| 3 | **Ireland's WIID CSV downloads directly** (ArcGIS item data URL). Its columns are now verified: `Wreck Name, Wreck No, Classification, Place of Loss, Date of Loss, DD_Lat, DD_Long, Source of Co-ordinate, Description, Record Source, Date_of_Loss_Year_Only`. `DD_Lat/DD_Long = 0` means no location. | Closes an "unverified" item. |
| 4 | **Western Australia WAM-002 has a public ArcGIS REST layer**, although the file downloads need a login. It holds only 305 features but includes **`port_from`, `port_to`, `sinking`**, `when_lost`, `country_bu`, `lat`, `long`. | Page the REST query. No login is needed. |
| 5 | **The UKHO wrecks set is on a public ArcGIS portal**: item `1aa31582b285461f81518007eeed9963` ("Wrecks Layer External Export File", Excel) and `4dbf2ace22bf4f9785fb445d0593bc2c` (shapefiles). | A direct download. The format is now known. |
| 6 | **The HGIS jurisdiction snapshots total ~3.3 GB**: 6 RARs of 484–626 MB. The territorial gazetteer comes as two RARs (138 MB dated 2023-10-26, 213 MB dated 2023-10-27). The ports zip (41 KB) and flotas zip (2 MB) are small. The ports terms are **CC BY-NC-SA 4.0**. All files are unrestricted through the Dataverse API. | The jurisdictions download only when a `--large` flag is passed. Take only the newer gazetteer RAR. |
| 7 | **CLIWOC**: Ottens' GPKG is 190 MB and served through GitHub LFS. The KNMI download pages now redirect to an unrelated project. The PANGAEA parent 611088 is a collection of **5,468 datasets**: `?format=textfile` returns 400 on the parent, and the probe of `?format=zip` failed. | Use the GPKG by default. A PANGAEA per-child harvest is optional, kept for its T1 provenance. |
| 8 | **Blocked for scripts**: the Historic England data-downloads page (403), HathiTrust (403), the NOAA AWOIS InPort page (403) and the Thenmap API (connection failed). | Treat these as manual or skipped (§7). |

---

## 2. Approach: use httpx with a manifest, not Scrapy

**Recommendation: don't build these as Scrapy spiders.** About 90% of the sources are known file URLs or JSON APIs: Zenodo, Dataverse, figshare, CKAN, ArcGIS REST, SPARQL, MediaWiki and Goobi. None needs link-following at scale, and the only HTML pages to fetch are two on Todo a Babor plus one Newberry index page. A Scrapy project would bring the Twisted reactor, settings, pipelines and an item model to replace `for url in manifest: stream_to_disk(url)`. Revisit Scrapy only if a source later needs a real crawl. Three Decks may be that case, but the other agent owns it.

Use **one small Python package**:

- a manifest listing each source;
- a few resolvers that turn a manifest entry into concrete file URLs;
- one downloader that streams, resumes, checksums and writes a provenance record.

Python 3.11 and `uv` are already installed. `httpx` and `pandas` are present globally, but pin them in the project anyway.

### Layout

```
pyproject.toml                  # uv project, deps below
fetch/
  __main__.py                   # CLI: python -m fetch ...
  manifest.yaml                 # one entry per source (see schema)
  core.py                       # HTTP client, rate limiter, streaming download, resume, sha256, provenance
  resolvers/
    direct.py                   # plain URL(s)
    zenodo.py                   # /api/records/{id} -> files[]
    dataverse.py                # /api/datasets/:persistentId -> files[] -> /api/access/datafile/{id}
    figshare.py                 # /v2/articles/{id} -> files[]
    ckan.py                     # package_show -> resources[] (filter by format)
    github.py                   # raw / codeload archive URLs (avoid the 60 req/h API)
    arcgis_portal.py            # /sharing/rest/content/items/{id}/data
    arcgis_rest.py              # paged /query -> GeoJSON (WA, fallback for others)
    socrata.py                  # /api/views/{id}/rows.csv
  harvesters/
    prizepapers.py              # Goobi viewer REST (§5.1)
    wikidata.py                 # WDQS SPARQL + wbgetentities (§5.2)
    wikipedia.py                # MediaWiki API: parsed HTML + wikitext + revid (§5.3)
    todoababor.py               # 2 HTML pages (§5.4)
  validate.py                   # open every file, count rows/features, write inventory
tests/
  fixtures/                     # recorded JSON responses per resolver
  test_resolvers.py             # respx-mocked; no network
  test_live.py                  # @pytest.mark.network: HEAD each manifest URL
data/                           # gitignored
  raw/<source_id>/...           # downloaded files, untouched
  raw/<source_id>/_provenance.json
  raw/_inventory.csv            # written by validate.py
```

**Dependencies:** `httpx`, `pyyaml`, `pandas`, `lxml` (for `read_html`), `pytest` and `respx`. Two optional extras:

- `[validate]`: `pyogrio` and `pyreadstat`, for opening GPKG/SHP files and SPSS `.sav` files.
- `[rar]`: `rarfile`, which needs `7z` or `unrar` on PATH.

### Manifest entry schema

```yaml
- id: ie_wiid                       # also the folder name under data/raw/
  group: wrecks                     # captures | wrecks | colonial | routes | trade
  title: Wreck Inventory of Ireland
  resolver: direct                  # see resolvers/
  url: https://www.arcgis.com/sharing/rest/content/items/d4b084c880b546fabe38345461b563d2/data
  filename: wiid.csv                # optional override
  licence: CC-BY-4.0
  tier: T1
  approx_bytes: 5_000_000
  large: false                      # true => only with --large
  redistribute: true                # false for NC / "do not redistribute" / unknown
  status: verified-2026-10-02       # verified | listed | resolve | manual | skip
  notes: DD_Lat/DD_Long == 0 means unlocated
```

### Downloader behaviour (`core.py`)

- **Politeness:**
  - Requests serialise per host, with a 1 s gap by default and overrides per host in the manifest.
  - Global concurrency is 4 hosts at once.
  - Retries back off exponentially on 429, 5xx and timeouts, up to 5 attempts, and honour `Retry-After`.
- **User-Agent:** `dead-reckoning-fetch/0.1 (+<contact>)`. `<contact>` is read from the `DR_CONTACT` environment variable, or from a gitignored `.env`. **Do not hard-code an email address.** Wikimedia's policy requires a contact in the User-Agent, so the Wikidata and Wikipedia harvesters refuse to run if `DR_CONTACT` is unset.
- **Streaming:** writes to `*.part` with `Range` resume, then renames once complete. Files that already exist are skipped if the size and the ETag or Last-Modified match the provenance record; `--force` re-downloads them.
- **Provenance:** `_provenance.json` per source records the URL(s), final URL after redirects, `fetched_at` (UTC), HTTP status, bytes, sha256, ETag and Last-Modified, plus the manifest's licence, tier and redistribute fields. It also stores resolver inputs such as the Zenodo version, Dataverse version number and Wikipedia `revid`.
- **No extraction during download.** Archives are stored as downloaded. A separate command, `python -m fetch extract <id>`, unpacks them into `data/interim/<id>/`. RAR files need 7-Zip.
- **Windows:** use `pathlib` everywhere and keep filenames short. HGIS RAR contents may hit `MAX_PATH`, so extract to a short root if needed.

### CLI

```
python -m fetch list [--group G]               # table: id, status, size, licence
python -m fetch get  [--group G | --id ID ...] [--large] [--force] [--dry-run]
python -m fetch extract ID
python -m fetch validate                       # writes data/raw/_inventory.csv
python -m fetch manual                         # prints instructions for manual/blocked sources and checks whether the files are present
```

---

## 3. Source inventory

Status key:
- ✅ probed today, and the file or file list came back;
- 📋 the publisher's API lists the URL, but the file wasn't fetched;
- 🔍 the URL needs resolving during implementation;
- ✋ manual;
- ⛔ skip.

Sizes are from API metadata or HEAD where known.

### 3.1 Captures and losses (group `captures`)

| id | Source | Method | Endpoint | Size | Licence | Status |
|---|---|---|---|---|---|---|
| `prizepapers` | Prize Papers portal | harvester §5.1 | `https://portal.prizepapers.de/api/v1/` | ~MBs JSON | Metadata terms unstated; images research-only | ✅ API + fields |
| `wikidata` | Wikidata (WDQS, QLever fallback) | harvester §5.2 | `https://query.wikidata.org/sparql`, `wbgetentities` | ~50 MB JSON | CC0 | ✅ (2,042 P11085 statements on 2,039 distinct items, via WDQS) |
| `wp_en_lists` | en.wikipedia: Spanish ships of the line; List of naval battles | harvester §5.3 | MediaWiki `action=parse` | small | CC BY-SA 4.0 | ✅ |
| `wp_en_shipwrecks` | en.wikipedia yearly/decadal shipwreck lists, 1650–1860 | harvester §5.3 | MediaWiki `action=parse` | ~200 pages | CC BY-SA 4.0 | ✅ API; page titles 🔍 |
| `wp_es_anexos` | es.wikipedia annexes: navíos de línea, fragatas | harvester §5.3 | MediaWiki `action=parse` on es | small | CC BY-SA 4.0 | 🔍 (unverified in doc) |
| `todoababor` | Todo a Babor loss list and reverse list | harvester §5.4 | 2 article URLs | 2 pages | None stated | ✅ (robots allows) |
| `slavevoyages` | Trans-Atlantic DB export + codebooks | direct | `https://legacy.slavevoyages.org/documents/download/tastdb-exp-2019.csv`, `SPSS_Codebook_2019.pdf`, `SPSS_Codebook_2023-11-06.pdf` | ~30 MB | Public domain; imputed vars CC BY-NC 3.0 US | ✅ links. Also list `tastdb-exp-2020.sav` as optional |
| `lloyds_list` | Lloyd's List 1741–1800 (Internet Archive) | direct | `https://archive.org/download/lloydslist17411800farn/lloydslist17411800farn_djvu.txt` (1.8 MB); PDF 27 MB `large` | 1.8 MB | None stated | ✅ metadata |
| `cdb90` | CDB90 battles | github | `codeload.github.com/jrnold/CDB90/zip/HEAD` | small | ODC-BY | ✅ repo |
| `brecke` | Brecke Conflict Catalog | direct | notes PDF ✅; Excel URL 🔍 (linked from same host) | small | None stated | 🔍 |
| `hcd_codebook` | Historical Conflict Dataset codebook | direct | su.se PDF URL from doc | small | ? | 🔍 (was unfetchable) |
| `combined_slave` | Combined slave-trade voyages | github | `revans011/database-of-combined-slave-trade-voyages` | small | MIT (code) | ✅ repo, optional |

### 3.2 Wrecks (group `wrecks`)

| id | Source | Method | Endpoint | Size | Licence | Status |
|---|---|---|---|---|---|---|
| `ie_wiid` | Ireland Wreck Inventory | direct | `https://www.arcgis.com/sharing/rest/content/items/d4b084c880b546fabe38345461b563d2/data` | ~5 MB | CC BY 4.0 | ✅ content |
| `ie_infomar` | INFOMAR shipwrecks | direct | `https://gsi.geodata.gov.ie/downloads/Marine/Data/Downloads/Shapefiles/IE_GSI_MI_Shipwrecks_IE_Waters_WGS84_LAT.zip` | small | CC BY 4.0 | 📋 (CKAN) |
| `ns_shipwrecks` | Nova Scotia Marine Heritage | socrata | `https://data.novascotia.ca/api/views/rq3a-h5hk/rows.csv?accessType=DOWNLOAD` + `/api/views/rq3a-h5hk.json` | 425 KB | NS OGL | ✅ content |
| `wa_wam002` | Western Australia shipwrecks | arcgis_rest | `https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/People_and_Society/MapServer/0/query` (`where=1=1&outFields=*&f=geojson`, 305 features, maxRecordCount 10,000) | small | CC BY 4.0 | ✅ count. Check whether 305 is the full WA set or a subset |
| `hi_wrecks` | Hawaii wrecks | direct | `https://files.hawaii.gov/dbedt/op/gis/data/wrecks.shp.zip` + hub CSV `.../items/50d3bdbea2314e56a88e8115ad9a695b/csv?layers=29` | small | None provided | 📋 (CKAN) |
| `ukho_wrecks` | UKHO wrecks and obstructions | arcgis_portal | `https://datahub.admiralty.co.uk/portal/sharing/rest/content/items/{1aa31582b285461f81518007eeed9963,4dbf2ace22bf4f9785fb445d0593bc2c,60c0908526b844a68494c038a457e1a7}/data` | ? | OGL (item text) | 📋 (portal search) |
| `canmore` | Canmore points (all heritage) | direct | `http://inspire.hes.scot/AtomService/DATA/Canmore_Points.zip` | 36 MB | OGL | ✅ HEAD. Filter to maritime records downstream |
| `noaa_wrecks` | NOAA Wrecks and Obstructions (MarineCadastre) | 🔍 | Start from `https://marinecadastre.gov/data/`; fallback ENC Direct REST `https://encdirect.noaa.gov/arcgis/rest/services/encdirect` | ? | ? | 🔍 |
| `noaa_awois` | NOAA AWOIS legacy (MDB) | 🔍 | InPort 403; look under nauticalcharts.noaa.gov | ? | ? | 🔍 |
| `emodnet_wrecks` | EMODnet heritage shipwrecks | 🔍 | GeoNetwork record lists no distribution URLs; find the WFS layer name via EMODnet Human Activities GetCapabilities | ? | CC BY 4.0 | 🔍 |
| `zenodo_shipwrecks` | Zenodo shipWrecks.csv | zenodo | record `7347768` → `shipWrecks.csv` | 732 KB | CC BY 4.0 | ✅ |
| `he_protected` | Historic England Protected Wreck Sites | ✋ | Data-downloads page returns 403 to scripts | small | OGL v3 | ✋ |
| `ni_wrecks` | Northern Ireland wrecks | ✋/🔍 | Unpath'd Waters ADS resource `65ca5022…` | ? | "Not set" | ✋ |

Skipped: AUCHD (search only), ShipwreckMap.ca (paid), Wrecksite.eu (subscription), the Historic England NMHR (by request), DataMapWales (sign-in), the Kaggle wrecks upload (T3, unverified), DARMC and OxREP (end before 1500), the Spanish Ministerio de Cultura and shipwrecks.es maps (no export), and the Marine Institute `wrecks` CKAN entry (WMS only, duplicates WIID).

### 3.3 Colonial extent (group `colonial`)

| id | Source | Method | Endpoint | Size | Licence | Status |
|---|---|---|---|---|---|---|
| `cliopatria` | Cliopatria | github | `https://github.com/Seshat-Global-History-Databank/cliopatria/raw/main/cliopatria.geojson.zip` (the GitHub release has no assets). Record the commit SHA. | 44 MB | CC BY 4.0 | ✅ tree |
| `hist_basemaps` | historical-basemaps | github | Fetch `index.json` (239 KB), then each `geojson/world_<year>.geojson` with year ≤ 1880 | ~50 MB | GPL-3.0 | ✅ index |
| `hgis_ports` | HGIS Puertos 1701–1808 | dataverse | `doi:10.7910/DVN/UXDJLQ` | 41 KB | CC BY-NC-SA 4.0 | ✅ |
| `hgis_territorios` | HGIS territorial gazetteer v4 | dataverse | `doi:10.7910/DVN/YPEU5E`. Newest RAR only, `territorios-2023-10-27.rar` | 213 MB | Custom NC | ✅ |
| `hgis_jurisdicciones` | HGIS jurisdictions, 6 snapshots | dataverse | `doi:10.7910/DVN/HZJGKA` | **3.26 GB**, `large` | Custom NC | ✅ |
| `hgis_other` | HGIS consulados, cajas reales, mints, shipyards | dataverse | List DOIs through the DataCite listing in the doc (pass `curl -g` or URL-encode the `page[size]` brackets) | small | Custom NC | 🔍 DOIs |
| `coldat` | COLDAT | dataverse | `doi:10.7910/DVN/T9SDEW` (`COLDAT_colonies.tab`, `COLDAT_dyads.tab`, PDF, readme) | ~1 MB | CC0 | ✅ |
| `owid_coldat` | OWID COLDAT republication | direct | `https://ourworldindata.org/grapher/european-overseas-colonies-by-colonizer.csv` | 102 KB | CC BY | ✅ content |
| `newberry_ahcb` | Newberry AHCB | direct | Parse links from `publications.newberry.org/ahcb/downloads/united_states.html`; national zip first, states optional | ~100s MB | Conflicting (see doc) | 🔍 links |
| `cshapes` | CShapes 2.0 | direct | Link from `icr.ethz.ch/data/cshapes/` | small | CC BY-NC-SA 4.0 | 🔍, optional (starts 1816/1886) |
| `icow_col` | ICOW Colonial History | direct | Link from `paulhensel.org/icowcol.html` | small | **Do not redistribute** | 🔍, optional, `redistribute: false` |

Skipped: Thenmap (API down, starts 1945), Euratlas (paid), GeaCron (unverified, likely paid).

### 3.4 Routes and logbooks (group `routes`)

| id | Source | Method | Endpoint | Size | Licence | Status |
|---|---|---|---|---|---|---|
| `cliwoc_gpkg` | CLIWOC 2.1 GeoPackage (Ottens) | direct | `https://github.com/stvno/stvno.github.io/raw/master/page/cliwoc/CLIWOC21.gpkg` (redirects to `media.githubusercontent.com`) | 190 MB | None stated (T3) | ✅ HEAD |
| `cliwoc_pangaea` | CLIWOC 2.1 (PANGAEA, T1) | 🔍 | List children of 611088 through PANGAEA's search API or the `pangaeapy` library, then `?format=textfile` per child (5,468 requests at 1 req/s ≈ 1.5 h). Test the parent `?format=zip` first. | ? `large` | CC BY 3.0 | 🔍, optional |
| `reshare_ew` | England and Wales ports and routes | direct | `https://reshare.ukdataservice.ac.uk/853711/1/Data_HistoricPorts.zip`, `/2/Data_ShippingRoutes.zip`, `/3/DataGuide.docx` | small | CC BY-SA 4.0 / CC BY 4.0 (conflict) | ✅ links |
| `hgis_flotas` | HGIS flotas y galeones routes | dataverse | `doi:10.7910/DVN/UGLWCR` | 2 MB | Custom | ✅ |
| `das` | Dutch-Asiatic Shipping | direct | `https://resources.huygens.knaw.nl/das/voyages_with_details.csv`, `voyages_with_opvarenden.csv` | small | None stated | ✅ links |
| `stro` | STRO 2.0 Sound Toll | figshare | article `27176202`, 18 CSVs | **1.6 GB**, `large` | CC BY 4.0 | ✅ |
| `manila_galleon` | Manila galleon tables (NOAA) | direct | `https://www.ncei.noaa.gov/pub/data/paleo/historical/pacific/acapulco-manila.pdf` | 1 MB | Cite DOI | ✅ |
| `noaa_eic` | NOAA EIC logbooks (C00785) | 🔍 | The landing page and ISO XML list no data URL. Search NCEI or contact NCEI. | ? | NOAA | 🔍 |
| `portic` | PORTIC API | 🔍 | API manual unverified | ? | AGPL (code) | 🔍, optional |
| `sea_routing` | Historical_Sea_Routing | github | archive zip | ? | CC BY-NC 4.0 | ✅ repo, optional |
| `ibm_maritime` | IBM chuk-mcp-maritime-archives | github | archive zip | ? | Apache 2.0 | ✅ repo, optional |
| `shipping_lanes` | Shipping-Lanes (modern) | github | archive zip | small | CC BY-SA 4.0 | ✅ repo, optional (not historical) |

Skipped or manual: ICOADS R3 (free registration, so manual), IEEE DataPort (login), the Kaggle CLIWOC15 file (needs a Kaggle API token; optional if `KAGGLE_*` env vars are set), Navigocorpus (guest login), the DAS RDF on Zenodo (restricted), and the Lloyd's Register and Chaunu scans (page images only).

### 3.5 Trade and gazetteers (group `trade`)

| id | Source | Method | Endpoint | Size | Licence | Status |
|---|---|---|---|---|---|---|
| `toflit18` | TOFLIT18 | zenodo | record `13749501`, `toflit18_data-1.0.2.zip` | 266 MB | ODbL | ✅ |
| `ricardo` | RICardo | github | `codeload.github.com/medialab/ricardo_data/zip/HEAD` | ? | ODbL | ✅ repo |
| `federico_tena` | Federico-Tena World Trade | 🔍 | Parse links from the UC3M page | ? | None stated | 🔍 |
| `globalise_places` | GLOBALISE VOC places | zenodo | record `13341556`, `datasprint-amh-v0.1.zip` | 9 MB | CC BY 4.0 | ✅ |
| `whg` | WHG datasets 12, 1245, 819, 657, 15 | direct | Dataset metadata via `https://whgazetteer.org/api/datasets/?id=N` ✅. The place export link on the dataset page is `/entity/dataset:N/api?filetype=tsv`; confirm it returns the full dataset without login. | small | Mostly none; WHG additions CC BY 4.0 | 🔍 export |
| `sv_ports` | SlaveVoyages common-ports CSV with lat/long | 🔍 | Find the Google Drive link in the UCSC guide | small | ? | 🔍 |

Skipped: CUST 3 (paid).

---

## 4. Order of work

Each phase ends with `python -m fetch validate` passing for every source the phase added.

1. **Scaffolding.**
   - Write `pyproject.toml`, `core.py`, the manifest loader, the CLI (`list`, `get`, `--dry-run`) and the provenance writer.
   - Add `data/` and `.env` to `.gitignore`.
   - Write tests for resume, skip-if-unchanged and provenance.
2. **Generic resolvers and every ✅/📋 file source**: direct, zenodo, dataverse, figshare, ckan, github, socrata, arcgis_portal and arcgis_rest. Most of the inventory is covered once these work. Download the default (non-`large`) set: about 1 GB in total, mostly TOFLIT18 266 MB, CLIWOC GPKG 190 MB, HGIS territorios 213 MB, Cliopatria 44 MB and Canmore 36 MB.
3. **Harvesters for the capture layer**, in order of value: `prizepapers`, then `wikidata`, `wikipedia` and `todoababor`.
4. **The 🔍 items.** Resolve each URL, then promote it to `verified` or demote it to `manual`/`skip` with a note. Do this as one pass, so every manifest entry ends in a final state.
5. **Manual list.** `python -m fetch manual` prints, for each ✋ source, the page to visit, the file to save and the destination path. It then checks that the file is present and writes a provenance record with `fetched_by: manual`.
6. **`--large` set**: HGIS jurisdictions, STRO, the Lloyd's PDF and, optionally, PANGAEA CLIWOC. Run these when needed; they are not part of CI.

---

## 5. Harvester details

### 5.1 Prize Papers (`harvesters/prizepapers.py`)

1. Save `/api/v1/openapi.json` and `/api/v1/index/fields/` to `data/raw/prizepapers/` before anything else. Build against the spec, not against guesses.
2. Find the index-query endpoint in the spec. Goobi viewer normally exposes a Solr-style query with `query`, `resultFields`, `sortFields`, `count` and `offset`. Use it to page through:
   - `DOCSTRCT:ship`
   - `DOCSTRCT:capture`
   - `DOCSTRCT:court_process`, optional; it links ships to cases.

   These facet values appear in the portal's own links. Request every `MD_SHIP_*`, `MD_CAPTURE_*` and `MD_EVENT_*` field, plus `MD_GEO_POINT`, `MD_ALL_PLACE*`, `MD_ALL_COORDS_FOR_SPATIALSEARCH`, `PI`, `IDDOC` and `IDDOC_PARENT`.
3. Harvest **all** ships and captures rather than filtering on Spain server-side. The flag values are unknown (Spanish, Spain, España…), and the whole capture set is useful context anyway. Filter Spanish ships downstream on `MD_SHIP_FLAG_FOR_FACET`.
4. Pace requests at **≤1 per second**, serial, with page size ≤100. Write one JSON file per page (`ship_00000.json`, …) so a re-run resumes where it stopped.
5. Do not touch `/search/`, `/oai` or image or PDF content. `robots.txt` disallows the first two, and the terms restrict the third.
6. Sanity check: the ~130 Spanish ships from the "Spanish Ships" case study (War of the Austrian Succession) should appear among the ship records whose flag is Spanish.
7. Courtesy step, not a blocker: tell the project (Oldenburg) about the harvest and ask whether a bulk metadata export exists.

### 5.2 Wikidata (`harvesters/wikidata.py`)

1. **Item lists by SPARQL.** Save each raw result as JSON, with the query text stored beside it.
   - **a.** All items with P11085 (Three Decks ID). This doubles as the **join-key file for the Three Decks agent**: write `data/raw/wikidata/p11085.csv` with `qid,threedecks_id,label`.
   - **b.** Ships (`P31/P279*` ship) linked to Spain, with no P11085 requirement. Count each route separately, because finding #2 shows P17/P8047 alone reaches only 7 items:
     - P17 or P8047 set to Spain or the Spanish Empire;
     - P137 (operator) set to the Spanish Navy;
     - membership in a "ships of the Spanish Navy" category or list.
   - **c.** Naval battles (instance of naval battle or its subclasses) dated 1492–1860, with P585/P580, P276, P625 and P710.

   Resolve QIDs such as "Spanish Navy" and "naval battle" by label at runtime and record them in provenance. Don't hard-code QIDs you haven't checked.
2. **Full entity JSON.** Fetch every QID from step 1 with `wbgetentities` in batches of 50. The full JSON includes the P793 event qualifiers (date, location, participant) that the SPARQL counts can't show. Roughly 2,000 + N items means about 60–100 requests.
3. **Limits.** WDQS allows 60 s per query. If a query times out, fall back to QLever (`https://qlever.dev/api/wikidata`). Set `maxlag=5` on `wbgetentities`. Run serially, with `DR_CONTACT` in the User-Agent.
4. **Report.** Write `summary.json` with the counts the doc wanted:
   - Spanish ship items;
   - how many have a capture-type P793 event;
   - how many have coordinates;
   - how many battle items have P625.

### 5.3 Wikipedia (`harvesters/wikipedia.py`)

1. Use `action=parse&prop=text|wikitext|revid&format=json&formatversion=2`. Save the wikitext, the HTML and the `revid`; the `revid` makes every parse reproducible.
2. Discover the shipwreck-list titles rather than hard-coding them. Read `Category:Lists of shipwrecks by year` with `list=categorymembers` and keep titles for 1650–1860; the coverage is yearly for some decades and per decade for the 1700s.
3. For the es.wikipedia annexes, resolve the exact titles first with `action=query&titles=…&redirects`. The doc's titles are unverified.
4. Parsing tables into rows belongs to the next stage, not to this harvester. Keep the harvester fetch-only.

### 5.4 Todo a Babor (`harvesters/todoababor.py`)

There are two URLs, and robots.txt allows both. Fetch each once at a 3 s spacing and save the HTML. No licence is stated, so set `redistribute: false`. Parsing comes later, keeping each entry's apresado, destruido or incendiado class.

---

## 6. Licences and redistribution

- `data/` is gitignored, so nothing downloaded is committed.
- Every provenance file carries `licence` and `redistribute`. The downstream build must propagate these: any output that mixes NC sources (HGIS, SlaveVoyages imputed variables, CShapes, Historical_Sea_Routing) is NC. ICOW must never be redistributed.
- historical-basemaps is GPL-3.0. Keep derived geometries from it separate from CC-BY layers until a licence decision is made.

## 7. Manual or blocked sources

| Source | Why | What the human does |
|---|---|---|
| Historic England Protected Wreck Sites | Downloads page returns 403 to scripts | Download the shapefile zip in a browser and save it to `data/raw/he_protected/` |
| Northern Ireland wrecks | Only reachable through the Unpath'd Waters portal | Export from ADS if allowed; otherwise skip |
| ICOADS R3 | Free registration | Register at GDEX and download the IMMA subset for 1662–1860 |
| Kaggle CLIWOC15 | Needs an API token | Optional: set `KAGGLE_USERNAME`/`KAGGLE_KEY`; the script then fetches it |
| HathiTrust Lloyd's List 1785–86 | 403 | Skip; the Internet Archive copy covers 1741–1800 |

## 8. Coordination with the Three Decks agent

- `data/raw/three_decks/` is reserved for that agent; these scripts must never write there.
- `data/raw/wikidata/p11085.csv` (§5.2, step 1a) is the shared join key. Tell the other agent where to find it.
- Propose the same `_provenance.json` schema to the other agent, so `validate` can inventory its output as well.

## 9. Definition of done

- Every manifest entry ends in a final state: `verified`, `manual` or `skip`, with a note. None is left at `resolve`.
- `python -m fetch get` (default set) runs cleanly from an empty `data/`. A second run downloads nothing.
- `python -m fetch validate` opens every file (CSV header, GeoJSON or GPKG feature count, zip listing) and writes `data/raw/_inventory.csv` with rows or features, columns, CRS where applicable, and sha256.
- `pytest` passes offline; `pytest -m network` passes HEAD checks on every verified URL.
- Write a short `data/raw/README.md`, generated from the manifest, that lists sources, licences and fetch dates.

# Data

Source data for the Age of Sail mapping work. The sources and their caveats are described in [`../Age of Sail GIS datasets.md`](../Age%20of%20Sail%20GIS%20datasets.md).

```
data/
  sources.csv        registry: one row per source; slug = folder name below
  raw/<slug>/        files exactly as downloaded, never edited
  derived/<slug>/    cleaned, reshaped or geocoded output built from that one source
```

## Rules

- **`raw/` is read-only.** If a file is wrong, re-download it; do not edit it in place.
- **Record provenance.** When you download into `raw/<slug>/`, add a `README.md` there with the URL, download date, version or DOI, and the licence as shown that day. Licences in `sources.csv` come from the research notes and several conflict.
- **One source per `derived/` folder.** `derived/<slug>/` holds only what can be built from `raw/<slug>/`. Anything that joins two or more sources, such as the battle and port gazetteer or the loss-event table, belongs in [`../analyses/`](../analyses/).
- **Derived files must be reproducible.** Note in `derived/<slug>/README.md` which script produced each file.
- **Copies of one dataset share a slug.** Mirrors with different licences or formats (for example CLIWOC from PANGAEA, the Ottens GeoPackage and Kaggle) go in subfolders of the same `raw/<slug>/`.
- **Adding a source:** add a row to `sources.csv`, then create `raw/<slug>/` and `derived/<slug>/`, each with a `.gitkeep`.

`sources.csv` columns: `themes` uses `events`, `battles`, `wrecks`, `colonial`, `routes`, `ports`, `trade` and `gazetteer`, separated by `;`. `access` is `open`, `registration`, `permission` (owner's consent needed) or `unverified` (the page could not be opened during research).

## Git

Data files are not committed. Only this README, `sources.csv`, the `.gitkeep` files and each source folder's `README.md` are tracked. Some sources are large (STRO is about 1.6 GB, ICOADS much more), and some forbid redistribution (Three Decks is "all rights reserved").

## Sources without folders

These sources from the research notes were left out because they cannot be downloaded or fall outside the period. Add them if that changes.

- **Paid:** Euratlas Periodis, CUST 3 at British Online Archives, the ShipwreckMap.ca CSV export.
- **No bulk access:** Australian National Shipwrecks (AUCHD), Historic England NMHR, Wrecksite.eu, the Spanish wreck inventories (cultura.gob.es, shipwrecks.es), the Spanish Navy's 1,580-wreck database, Lloyd's Register scans, EIC Ships, Chaunu's *Séville et l'Atlantique*, New Spain Fleets.
- **Outside the period:** CShapes 2.0, ICOW Colonial History, Thenmap, DARMC, OxREP, Shipping-Lanes.
- **Judged unusable:** CDB90, the Brecke Conflict Catalog, the Historical Conflict Dataset.

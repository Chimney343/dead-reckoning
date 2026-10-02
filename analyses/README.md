# Analyses

Work that combines sources or answers a question. Analyses read from `data/derived/` (or `data/raw/` when a source needs no cleaning) and never write back into `data/`.

```
analyses/
  <NN>-<slug>/
    README.md      question, input source slugs, method, status
    ...            scripts and notebooks
    outputs/       tables, layers and figures produced here
```

- Number folders in the order they are started (`01-`, `02-`, …).
- Cross-source datasets live here as an analysis's `outputs/`, for example the geocoded battle and port gazetteer or the Spanish loss-event table from the research notes. A later analysis may read an earlier one's `outputs/`; list it as an input in the README.
- Keep outputs reproducible from the scripts in the same folder.

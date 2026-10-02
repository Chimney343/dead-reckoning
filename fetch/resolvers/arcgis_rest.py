"""ArcGIS REST feature service: count, then page the query as GeoJSON."""

from __future__ import annotations

from urllib.parse import urlencode, urlparse, urlunparse

from ..core import FileSpec
from ..manifest import Entry


def resolve(entry: Entry, client) -> list[FileSpec]:
    parsed = urlparse(entry.url)
    base = urlunparse(parsed._replace(query=""))
    where = entry.params.get("where", "1=1")
    out_fields = entry.params.get("out_fields", "*")
    page_size = int(entry.params.get("page_size", 1000))

    count_url = base + "?" + urlencode(
        {"where": where, "returnCountOnly": "true", "f": "json"}
    )
    count = client.get(count_url).json().get("count", 0)

    urls: list[str] = []
    offset = 0
    while offset < count:
        query = {
            "where": where,
            "outFields": out_fields,
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "outSR": 4326,
        }
        urls.append(base + "?" + urlencode(query))
        offset += page_size
    if not urls:
        urls.append(
            base
            + "?"
            + urlencode(
                {
                    "where": where,
                    "outFields": out_fields,
                    "f": "geojson",
                    "outSR": 4326,
                }
            )
        )

    filename = entry.filename or f"{entry.id}.geojson"
    return [
        FileSpec(
            urls=urls,
            filename=filename,
            merge="geojson",
            meta={"count": count, "where": where, "page_size": page_size},
        )
    ]

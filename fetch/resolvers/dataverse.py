"""Harvard Dataverse: dataset metadata -> /api/access/datafile/{id}."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from ..core import FileSpec
from ..manifest import Entry
from . import safe_filename


def resolve(entry: Entry, client) -> list[FileSpec]:
    parsed = urlparse(entry.url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    doi = parse_qs(parsed.query).get("persistentId", [entry.params.get("doi", "")])[0]

    data = client.get(entry.url).json()["data"]["latestVersion"]
    version = data.get("versionNumber")
    specs: list[FileSpec] = []
    for item in data.get("files", []):
        data_file = item.get("dataFile", item)
        file_id = data_file.get("id")
        filename = safe_filename(data_file.get("filename", ""))
        directory = item.get("directoryLabel")
        if directory:
            filename = safe_filename(f"{directory}/{filename}")
        specs.append(
            FileSpec(
                urls=[f"{base}/api/access/datafile/{file_id}"],
                filename=filename,
                meta={"doi": doi, "version": version, "file_id": file_id},
            )
        )
    return specs

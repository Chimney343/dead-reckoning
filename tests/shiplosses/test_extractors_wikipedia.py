"""Synthetic Wikipedia shipwreck-list extractor test (plan section 10)."""

from __future__ import annotations

import json

from shiplosses.sources import wikipedia

PAGE = {
    "title": "List of shipwrecks in 1805",
    "revid": 1,
    "url": "https://en.wikipedia.org/wiki/List_of_shipwrecks_in_1805",
    "wikitext": "{{coord|52.7|-4.1}}",
    "html": """
    <h2>February</h2>
    <h3>14</h3>
    <table class="wikitable">
      <tr><th>Ship</th><th>State</th><th>Description</th></tr>
      <tr><td>HMS Example</td><td><a>Royal Navy</a></td>
          <td>The ship was wrecked near Barmouth, Caernarvonshire, United Kingdom.</td></tr>
      <tr><td>Le Vengeur</td><td><a>France</a></td>
          <td>She was captured off Berbice by a French privateer.
              She was plundered and sunk.</td></tr>
    </table>
    """,
}


def test_wikipedia_extractor_parses_table_and_capture(tmp_path):
    directory = tmp_path / "raw" / "wikipedia" / "en-shipwrecks"
    directory.mkdir(parents=True)
    (directory / "List_of_shipwrecks_in_1805.json").write_text(
        json.dumps(PAGE), encoding="utf-8"
    )

    extract = wikipedia.extract(tmp_path / "raw")
    assert len(extract.losses) == 2
    rows = extract.losses.set_index("ship_name")
    example = rows.loc["HMS Example"]
    assert example["flag_at_loss_polity"] == "Great Britain"
    assert example["cause_class"] == "stranded"
    assert example["loss_date"] == "1805-02-14"
    assert example["location_text"].startswith("near Barmouth")
    vengeur = rows.loc["Le Vengeur"]
    assert vengeur["flag_at_loss_polity"] == "France"
    assert vengeur["cause_class"] == "enemy_action"
    assert len(extract.events) == 1
    assert extract.events.iloc[0]["to_polity"] == "France"

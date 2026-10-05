"""The QA report surfaces unknown labels and sections (Plan 6, layer 8)."""

from __future__ import annotations

from threedecks.items import ShipRecord
from threedecks.state import StateStore

from scripts.qa_report import build_report


def test_report_counts_unknown_labels_and_sections(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_ship(
        ShipRecord(
            td_id=1,
            name="One",
            url="https://x/1",
            unknown_labels=["Refloated By"],
            unknown_sections=["Prize Money"],
        )
    )
    store.save_ship(ShipRecord(td_id=2, name="Two", url="https://x/2"))
    store.close()

    report, markdown = build_report(tmp_path)
    assert report["unknown_labels"] == {"Refloated By": 1}
    assert report["unknown_sections"] == {"Prize Money": 1}
    assert "## Unknown sections\n\n- Prize Money: 1" in markdown


def test_report_says_none_when_every_section_is_known(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_ship(ShipRecord(td_id=1, name="One", url="https://x/1"))
    store.close()

    report, markdown = build_report(tmp_path)
    assert report["unknown_sections"] == {}
    assert "## Unknown sections\n\n- none" in markdown


def test_incarnation_links_mirrored_by_previously_are_not_broken(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_ship(ShipRecord(td_id=1, name="Spanish", url="u1", next_td_ids=[2]))
    store.save_ship(ShipRecord(td_id=2, name="British", url="u2", previous_td_ids=[1]))
    store.save_ship(ShipRecord(td_id=3, name="Lone", url="u3", next_td_ids=[4, 1]))
    store.close()

    report, markdown = build_report(tmp_path)
    # 1 <-> 2 mirror each other; 3 -> 1 is not mirrored; 3 -> 4 is not fetched yet.
    assert report["broken_incarnation_links"] == [
        {"from": 3, "to": 1, "field": "next_td_ids"}
    ]
    assert report["unchecked_incarnation_links"] == 1
    assert "- 1 to ships not fetched yet" in markdown


def test_report_lists_dates_the_source_got_wrong(tmp_path):
    from threedecks.items import BaseRow, HistoryEvent
    from threedecks.parsing.dates import parse_td_date

    store = StateStore(tmp_path / "state.sqlite")
    store.save_ship(ShipRecord(
        td_id=7, name="Seven", url="u7",
        base_rows=[BaseRow(label="Launched", text="60.1739"),
                   BaseRow(label="Shipyard", text="Ferrol - Spain")],
        history=[HistoryEvent(text="x", date=parse_td_date("36.5.1801")),
                 HistoryEvent(text="y", date=parse_td_date("1.5.1801"))],
    ))
    store.close()

    report, markdown = build_report(tmp_path)
    assert report["unparseable_dates"] == [
        {"td_id": 7, "where": "Launched", "raw": "60.1739"},
        {"td_id": 7, "where": "Service History", "raw": "36.5.1801"},
    ]
    assert "- ship 7, Launched: 60.1739" in markdown

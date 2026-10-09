"""The QA report surfaces unknown labels and sections (Plan 6, layer 8)."""

from __future__ import annotations

from threedecks.items import (
    ActionRecord,
    FleetIndexRow,
    FleetRecord,
    FleetRow,
    FleetShip,
    HistoryEvent,
    LabeledDate,
    Participant,
    ShipRecord,
)
from threedecks.parsing.dates import parse_td_date
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


def test_report_reports_action_asymmetry(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_ship(
        ShipRecord(
            td_id=2682,
            name="San Ildefonso",
            url="u",
            history=[HistoryEvent(text="x", battle_ids=[5])],
        )
    )
    store.save_action(
        ActionRecord(
            battle_id=5,
            name="Battle Five",
            participants=[Participant(td_id=9999, ship_label="Other")],
        )
    )
    store.close()

    report, markdown = build_report(tmp_path)
    actions = report["actions"]
    # 2682's history cites battle 5, but battle 5 does not list 2682.
    assert actions["ship_history_not_in_action"] == [{"ship_id": 2682, "battle_id": 5}]
    assert actions["count"] == 1
    assert "## Actions" in markdown


def test_report_lists_history_battles_without_an_action(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_ship(
        ShipRecord(
            td_id=1,
            name="One",
            url="u",
            history=[HistoryEvent(text="x", battle_ids=[42])],
        )
    )
    store.close()

    report, _ = build_report(tmp_path)
    assert report["actions"]["history_battles_without_action"] == [42]


def test_report_reports_fleet_asymmetry_and_out_of_lifecycle(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_ship(
        ShipRecord(
            td_id=1,
            name="One",
            url="u1",
            fleets=[FleetRow(fleet_id=5)],
            lifecycle=[LabeledDate(label="Launched", text="1.1.1800",
                                   date=parse_td_date("1.1.1800"))],
        )
    )
    store.save_ship(
        ShipRecord(
            td_id=2,
            name="Two",
            url="u2",
            lifecycle=[LabeledDate(label="Launched", text="1.1.1800",
                                   date=parse_td_date("1.1.1800"))],
        )
    )
    store.save_fleet(
        FleetRecord(
            fleet_id=5,
            name="Five",
            ships=[FleetShip(td_id=2, ship_label="Two", joined=parse_td_date("1.1.1790"))],
        )
    )
    store.save_fleet_index([FleetIndexRow(fleet_id=5, name="Five")])
    store.close()

    report, markdown = build_report(tmp_path)
    fleets = report["fleets"]
    # Ship 1 cites fleet 5, but fleet 5's ships do not list ship 1.
    assert fleets["ship_fleet_not_in_fleet"] == [{"ship_id": 1, "fleet_id": 5}]
    # Fleet 5 lists ship 2, but ship 2's fleets do not cite fleet 5.
    assert fleets["fleet_ship_not_in_ship_fleets"] == [{"fleet_id": 5, "ship_id": 2}]
    # Ship 2 was launched in 1800; the fleet joins it in 1790.
    assert fleets["out_of_lifecycle"] == [
        {"fleet_id": 5, "td_id": 2, "field": "joined", "date": "1790-01-01"}
    ]
    assert "## Fleets" in markdown

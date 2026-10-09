"""Fleet state: the ``fleets`` and ``fleet_index`` tables (Task FL4)."""

from __future__ import annotations

from threedecks.items import FleetIndexRow, FleetRecord, FleetRow, ShipRecord
from threedecks.state import StateStore


def make_fleet(fleet_id: int = 97, name: str = "Saumarez's Squadron 1798") -> FleetRecord:
    return FleetRecord(
        fleet_id=fleet_id,
        name=name,
        url=f"https://x/{fleet_id}",
        parser_version="1",
    )


def make_index_row(fleet_id: int | None, name: str) -> FleetIndexRow:
    return FleetIndexRow(fleet_id=fleet_id, name=name)


def test_save_fleet_writes_the_record_and_done_together(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed_pages("fleet", ["97"], discovered_by="index")
    store.save_fleet(make_fleet(97))
    assert store.page_status("fleet", "97") == "done"
    assert store.get_fleet(97)["name"] == "Saumarez's Squadron 1798"
    store.close()


def test_save_fleet_index_skips_rows_without_an_id_and_marks_done(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed_pages("fleet_index", ["1"], discovered_by="start")
    stored = store.save_fleet_index(
        [make_index_row(1, "A"), make_index_row(None, "Orphan"), make_index_row(2, "B")]
    )
    assert stored == 2
    assert store.page_status("fleet_index", "1") == "done"
    assert [row["name"] for row in store.iter_fleet_index()] == ["A", "B"]
    store.close()


def test_fleet_count_and_iteration(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_fleet(make_fleet(2, "Second"))
    store.save_fleet(make_fleet(1, "First"))
    assert store.fleet_count() == 2
    assert [row["fleet_id"] for row in store.iter_fleets()] == [1, 2]
    store.close()


def test_ship_and_fleet_namespaces_do_not_interfere(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed([97], discovered_by="test")
    store.save_ship(ShipRecord(td_id=97, name="Ship 97"))
    store.seed_pages("fleet", ["97"], discovered_by="test")
    store.save_fleet(make_fleet(97))
    assert store.status(97) == "done"
    assert store.page_status("fleet", "97") == "done"
    assert store.get_ship(97)["name"] == "Ship 97"
    assert store.get_fleet(97)["name"] == "Saumarez's Squadron 1798"
    store.close()


def test_ship_fleet_ids_are_sorted_and_unique(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_ship(
        ShipRecord(
            td_id=1,
            name="One",
            fleets=[FleetRow(fleet_id=139), FleetRow(fleet_id=97)],
        )
    )
    store.save_ship(
        ShipRecord(td_id=2, name="Two", fleets=[FleetRow(fleet_id=97), FleetRow(fleet_id=None)])
    )
    assert store.ship_fleet_ids() == [97, 139]
    store.close()


def test_reopening_keeps_fleets_and_index(tmp_path):
    path = tmp_path / "state.sqlite"
    store = StateStore(path)
    store.save_fleet(make_fleet(97))
    store.save_fleet_index([make_index_row(97, "Saumarez's Squadron 1798")])
    store.close()

    reopened = StateStore(path)
    assert reopened.fleet_count() == 1
    assert reopened.get_fleet(97)["name"] == "Saumarez's Squadron 1798"
    assert [row["fleet_id"] for row in reopened.iter_fleet_index()] == [97]
    reopened.close()

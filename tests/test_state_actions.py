"""Action state: the ``actions`` and ``action_index`` tables (Task A4)."""

from __future__ import annotations

from threedecks.items import ActionIndexRow, ActionRecord, HistoryEvent, ShipRecord
from threedecks.state import StateStore


def make_action(battle_id: int = 157, name: str = "Battle of Trafalgar") -> ActionRecord:
    return ActionRecord(
        battle_id=battle_id,
        name=name,
        url=f"https://x/{battle_id}",
        parser_version="1",
    )


def make_index_row(battle_id: int | None, name: str) -> ActionIndexRow:
    return ActionIndexRow(battle_id=battle_id, name=name)


def test_save_action_writes_the_record_and_done_together(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed_pages("action", ["157"], discovered_by="index")
    store.save_action(make_action(157))
    assert store.page_status("action", "157") == "done"
    assert store.get_action(157)["name"] == "Battle of Trafalgar"
    store.close()


def test_save_action_index_page_skips_rows_without_an_id_and_marks_done(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed_pages("action_index", ["1"], discovered_by="start")
    stored = store.save_action_index_page(
        "1", [make_index_row(1, "A"), make_index_row(None, "Orphan"), make_index_row(2, "B")]
    )
    assert stored == 2
    assert store.page_status("action_index", "1") == "done"
    assert [row["name"] for row in store.iter_action_index()] == ["A", "B"]
    store.close()


def test_action_count_and_iteration(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_action(make_action(2, "Second"))
    store.save_action(make_action(1, "First"))
    assert store.action_count() == 2
    assert [row["battle_id"] for row in store.iter_actions()] == [1, 2]
    store.close()


def test_ship_and_action_namespaces_do_not_interfere(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed([157], discovered_by="test")
    store.save_ship(ShipRecord(td_id=157, name="Ship 157"))
    store.seed_pages("action", ["157"], discovered_by="test")
    store.save_action(make_action(157))
    assert store.status(157) == "done"
    assert store.page_status("action", "157") == "done"
    assert store.get_ship(157)["name"] == "Ship 157"
    assert store.get_action(157)["name"] == "Battle of Trafalgar"
    store.close()


def test_history_battle_ids_are_sorted_and_unique(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_ship(
        ShipRecord(
            td_id=2682,
            name="San Ildefonso",
            history=[
                HistoryEvent(text="a", battle_ids=[157, 149]),
                HistoryEvent(text="b", battle_ids=[157]),
            ],
        )
    )
    store.save_ship(
        ShipRecord(td_id=1, name="Other", history=[HistoryEvent(text="c", battle_ids=[200])])
    )
    assert store.history_battle_ids() == [149, 157, 200]
    store.close()


def test_reopening_keeps_actions_and_index(tmp_path):
    path = tmp_path / "state.sqlite"
    store = StateStore(path)
    store.save_action(make_action(157))
    store.save_action_index_page("1", [make_index_row(157, "Battle of Trafalgar")])
    store.close()

    reopened = StateStore(path)
    assert reopened.action_count() == 1
    assert reopened.get_action(157)["name"] == "Battle of Trafalgar"
    assert [row["battle_id"] for row in reopened.iter_action_index()] == [157]
    reopened.close()

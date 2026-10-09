"""crawl_status.py reports an actions block too (Task A8)."""

from __future__ import annotations

from threedecks.items import ActionRecord, FleetRecord
from threedecks.state import StateStore

from scripts import crawl_status


def test_status_includes_the_actions_block(tmp_path, capsys):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed_pages("action_index", ["1"], discovered_by="x")
    store.mark_page_status("action_index", "1", "done")
    store.seed_pages("action", ["157"], discovered_by="x")
    store.save_action(ActionRecord(battle_id=157, name="Battle of Trafalgar"))
    run_id = store.start_run("actions")
    store.finish_run(run_id, close_reason="finished", pages_fetched=10)
    store.close()

    assert crawl_status.main(["--data-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "actions stored: 1" in out
    assert "action_index : 1 pages" in out
    assert "action       : 1 pages" in out
    assert "last actions  :" in out


def test_status_includes_the_fleets_block(tmp_path, capsys):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed_pages("fleet_index", ["1"], discovered_by="x")
    store.mark_page_status("fleet_index", "1", "done")
    store.seed_pages("fleet", ["97"], discovered_by="x")
    store.save_fleet(FleetRecord(fleet_id=97, name="Saumarez's Squadron 1798"))
    run_id = store.start_run("fleets")
    store.finish_run(run_id, close_reason="finished", pages_fetched=10)
    store.close()

    assert crawl_status.main(["--data-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "fleets stored : 1" in out
    assert "fleet_index" in out and "1 pages" in out
    assert "last fleets   :" in out

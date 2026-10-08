"""crawl_status.py reports an actions block too (Task A8)."""

from __future__ import annotations

from threedecks.items import ActionRecord
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

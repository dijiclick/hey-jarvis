from jarvis.store import Store


def test_add_and_list_routines(tmp_path):
    s = Store(tmp_path / "j.db")
    s.add_routine("morning tests", "every morning at 9", "run the tests in ShopFront", "ShopFront", 1000.0)
    s.add_routine("lead check", "every 30 minutes", "check Gmail for new leads", None, 500.0)
    routines = s.list_routines()
    assert [r.name for r in routines] == ["lead check", "morning tests"]
    assert routines[1].project == "ShopFront" and routines[1].enabled is True
    assert routines[0].project is None


def test_adding_the_same_name_replaces_it(tmp_path):
    s = Store(tmp_path / "j.db")
    s.add_routine("brief", "every morning at 9", "old task", None, 100.0)
    s.add_routine("brief", "every day at 8", "new task", "ShopFront", 200.0)
    routines = s.list_routines()
    assert len(routines) == 1
    assert routines[0].task == "new task" and routines[0].schedule == "every day at 8"
    assert routines[0].next_run == 200.0


def test_due_routines_respects_time_and_enabled(tmp_path):
    s = Store(tmp_path / "j.db")
    s.add_routine("soon", "every 5 minutes", "a", None, 100.0)
    s.add_routine("later", "every 5 minutes", "b", None, 900.0)
    s.add_routine("off", "every 5 minutes", "c", None, 50.0)
    s.set_routine_enabled("off", False)
    assert [r.name for r in s.due_routines(500.0)] == ["soon"]


def test_mark_routine_run_advances_and_a_finished_one_off_is_disabled(tmp_path):
    s = Store(tmp_path / "j.db")
    rid = s.add_routine("repeat", "every 5 minutes", "a", None, 100.0)
    s.mark_routine_run(rid, 100.0, 400.0)
    routine = s.get_routine("repeat")
    assert routine.last_run == 100.0 and routine.next_run == 400.0 and routine.enabled is True

    once = s.add_routine("one off", "once 2026-10-01 14:00", "b", None, 100.0)
    s.mark_routine_run(once, 100.0, None)
    assert s.get_routine("one off").enabled is False
    # the spent one-off never comes due again; the repeating one still does
    assert [r.name for r in s.due_routines(10_000.0)] == ["repeat"]


def test_remove_and_missing_routine(tmp_path):
    s = Store(tmp_path / "j.db")
    s.add_routine("gone", "every morning at 9", "a", None, 100.0)
    assert s.remove_routine("gone") is True
    assert s.remove_routine("gone") is False
    assert s.get_routine("gone") is None
    assert s.set_routine_enabled("nope", True) is False

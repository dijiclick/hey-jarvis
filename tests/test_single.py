from jarvis.single import acquire_lock


def test_only_one_holder_at_a_time(tmp_path):
    first = acquire_lock(tmp_path)
    assert first is not None
    assert acquire_lock(tmp_path) is None
    first.close()
    again = acquire_lock(tmp_path)
    assert again is not None
    again.close()

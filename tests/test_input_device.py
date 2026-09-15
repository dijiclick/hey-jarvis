from jarvis.audio import pick_input_device

# a Mac with Bluetooth earbuds connected; index 1 is the system default, index 2 is output-only
DEVICES = [
    {"name": "iPhone Microphone", "max_input_channels": 1},
    {"name": "Sam's Buds2", "max_input_channels": 1},
    {"name": "Sam's Buds2", "max_input_channels": 0},
    {"name": "MacBook Air Microphone", "max_input_channels": 1},
]


def test_auto_uses_the_microphone_you_chose_in_macos():
    assert pick_input_device("auto", DEVICES, default_index=1) == 1
    assert pick_input_device("auto", DEVICES, default_index=3) == 3
    assert pick_input_device("auto", DEVICES, default_index=0) == 0


def test_auto_is_stable_across_repeated_calls():
    # the bug this replaced: selection opened the mic to measure it, which collapsed a Bluetooth link,
    # so consecutive calls disagreed and the chosen microphone changed on every restart
    chosen = {pick_input_device("auto", DEVICES, default_index=1) for _ in range(10)}
    assert chosen == {1}


def test_auto_skips_a_default_that_cannot_record():
    assert pick_input_device("auto", DEVICES, default_index=2) == 0   # output-only entry
    assert pick_input_device("auto", DEVICES, default_index=None) == 0
    assert pick_input_device("auto", DEVICES, default_index=99) == 0


def test_auto_returns_none_when_there_is_no_input_at_all():
    assert pick_input_device("auto", [{"name": "Speakers", "max_input_channels": 0}], default_index=None) is None


def test_an_explicit_name_overrides_the_default():
    assert pick_input_device("macbook", DEVICES, default_index=1) == 3
    assert pick_input_device("buds", DEVICES, default_index=3) == 1
    assert pick_input_device("iphone", DEVICES, default_index=1) == 0
    assert pick_input_device("nonexistent", DEVICES, default_index=1) is None


def test_default_means_let_coreaudio_choose():
    assert pick_input_device("default", DEVICES, default_index=1) is None
    assert pick_input_device(None, DEVICES, default_index=1) is None
    assert pick_input_device("", DEVICES, default_index=1) is None

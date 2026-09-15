import asyncio
from types import SimpleNamespace

from jarvis.app import DEAF_AFTER_S, JarvisApp
from jarvis.audio import next_input_device

DEVICES = [
    {"name": "iPhone Microphone", "max_input_channels": 1},
    {"name": "Sam's Buds2", "max_input_channels": 1},
    {"name": "Sam's Buds2", "max_input_channels": 0},
    {"name": "MacBook Air Microphone", "max_input_channels": 1},
]


def test_next_input_skips_the_current_and_the_dead_default():
    # moving off the silent Bluetooth default must not land back on it
    assert next_input_device(1, DEVICES, default_index=1) == 3
    assert next_input_device(0, DEVICES, default_index=1) == 3
    assert next_input_device(3, DEVICES, default_index=1) == 0


def test_next_input_prefers_the_built_in_mic_over_a_continuity_iphone():
    # the iPhone mic can be in another room; the built-in one is always present and measured 121-207 here
    assert next_input_device(1, DEVICES, default_index=1) == 3
    only_iphone_left = [DEVICES[0], DEVICES[1]]
    assert next_input_device(1, only_iphone_left, default_index=1) == 0


def test_next_input_returns_the_default_only_as_a_last_resort():
    two = [DEVICES[1], DEVICES[3]]      # default index 0 here, one alternative
    assert next_input_device(1, two, default_index=0) == 0


def test_next_input_gives_up_when_there_is_nowhere_to_go():
    one = [{"name": "Only mic", "max_input_channels": 1}]
    assert next_input_device(0, one, default_index=0) is None


def make_app(levels):
    settings = SimpleNamespace(home=None, db_path=":memory:", confirm_timeout_s=120, input_device="auto")
    app = JarvisApp(settings, audio_factory=lambda loop: None)
    app.voice = SimpleNamespace(is_open=True)
    app.audio = SimpleNamespace(input_level=0, output_level=0, switch_input=lambda i: switched.append(i))
    return app


switched: list = []


async def test_watchdog_switches_away_from_a_deaf_microphone():
    switched.clear()
    app = make_app(levels=None)
    app.audio.input_level = 0          # flat: the earbuds are idling in music mode
    said = []
    app.notify_deaf = lambda name: said.append(name)

    task = asyncio.create_task(app._deaf_watchdog(interval_s=0.02, deaf_after_s=0.1,
                                                 pick_next=lambda cur: 3))
    await asyncio.sleep(0.3)
    task.cancel()
    assert switched == [3], "should have moved to another input once"
    assert said, "and should have told the user out loud"


async def test_watchdog_stays_quiet_while_audio_is_arriving():
    switched.clear()
    app = make_app(levels=None)
    app.audio.input_level = 800        # hearing the room
    task = asyncio.create_task(app._deaf_watchdog(interval_s=0.02, deaf_after_s=0.1,
                                                 pick_next=lambda cur: 3))
    await asyncio.sleep(0.3)
    task.cancel()
    assert switched == []


async def test_watchdog_does_nothing_when_no_session_is_open():
    switched.clear()
    app = make_app(levels=None)
    app.voice = SimpleNamespace(is_open=False)
    app.audio.input_level = 0
    task = asyncio.create_task(app._deaf_watchdog(interval_s=0.02, deaf_after_s=0.1,
                                                 pick_next=lambda cur: 3))
    await asyncio.sleep(0.2)
    task.cancel()
    assert switched == []


async def test_watchdog_switches_only_once_per_deaf_spell():
    switched.clear()
    app = make_app(levels=None)
    app.audio.input_level = 0
    task = asyncio.create_task(app._deaf_watchdog(interval_s=0.02, deaf_after_s=0.05,
                                                 pick_next=lambda cur: 3))
    await asyncio.sleep(0.4)
    task.cancel()
    assert switched == [3], "reopening a Bluetooth device repeatedly is what kills it"


def test_deaf_threshold_is_a_sane_default():
    assert 2 <= DEAF_AFTER_S <= 30

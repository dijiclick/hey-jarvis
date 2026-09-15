import time

from jarvis.chrome_consent import ChromeConsentClicker, pick_allow

# (role, label) nodes as read from Chrome 153's real "Allow remote debugging?" sheet
DIALOG = [
    ("AXSheet", ""),
    ("AXGroup", ""),
    ("AXHeading", "Allow remote debugging? | Allow remote debugging?"),
    ("AXStaticText", "An external app wants full control over this Chrome session to debug it."),
    ("AXButton", "Turn off in settings | Turn off in settings"),
    ("AXButton", "Cancel | Cancel"),
    ("AXButton", "Allow | Allow"),
]


def until(pred, timeout=2.0):
    end = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def test_pick_allow_on_the_remote_debugging_dialog():
    assert pick_allow(DIALOG) == 6


def test_pick_allow_ignores_other_dialogs():
    assert pick_allow([("AXHeading", "Save password?"), ("AXButton", "Allow | Allow")]) is None


def test_pick_allow_needs_the_exact_allow_button():
    assert pick_allow([("AXHeading", "Allow remote debugging?"), ("AXButton", "Allow once | Allow once")]) is None


def test_polls_only_while_armed_and_counts_clicks():
    calls = []
    now = [0.0]

    def runner():
        calls.append(1)
        return "clicked" if len(calls) == 2 else "none"

    c = ChromeConsentClicker(window_s=1.0, interval_s=0.01, runner=runner, clock=lambda: now[0])
    time.sleep(0.05)
    assert calls == []
    c.arm()
    until(lambda: len(calls) >= 3)
    assert c.clicks == 1
    now[0] = 5.0
    until(lambda: c._thread is None)
    settled = len(calls)
    time.sleep(0.05)
    assert len(calls) == settled
    c.arm()
    until(lambda: len(calls) > settled)
    c.stop()


def test_runner_errors_do_not_kill_the_loop():
    calls = []

    def runner():
        calls.append(1)
        raise RuntimeError("AX unavailable")

    c = ChromeConsentClicker(window_s=5.0, interval_s=0.01, runner=runner)
    c.arm()
    until(lambda: len(calls) >= 3)
    c.stop()

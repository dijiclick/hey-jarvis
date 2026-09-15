import pytest
from pynput.keyboard import Key, KeyCode

from jarvis.hotkey import HotkeyMatcher, parse_hotkey


def test_parse():
    assert parse_hotkey("<ctrl>+<alt>+j") == (frozenset({"ctrl", "alt"}), 38)
    assert parse_hotkey("<cmd>+<shift>+<space>") == (frozenset({"cmd", "shift"}), 49)


@pytest.mark.parametrize("spec", ["<ctrl>+<alt>", "<ctrl>+f13", "<ctrl>+j+k"])
def test_parse_rejects(spec):
    with pytest.raises(ValueError):
        parse_hotkey(spec)


def test_matches_physical_key_even_when_option_changes_the_character():
    m = HotkeyMatcher("<ctrl>+<alt>+j")
    assert m.press(Key.ctrl_l) is False
    assert m.press(Key.alt) is False
    assert m.press(KeyCode(vk=38, char="∆")) is True


def test_requires_exact_modifiers():
    m = HotkeyMatcher("<ctrl>+<alt>+j")
    m.press(Key.ctrl)
    assert m.press(KeyCode(vk=38, char="j")) is False
    m.press(Key.alt)
    m.press(Key.shift)
    assert m.press(KeyCode(vk=38)) is False


def test_release_clears_modifiers():
    m = HotkeyMatcher("<ctrl>+<alt>+j")
    m.press(Key.ctrl)
    m.press(Key.alt)
    m.release(Key.alt)
    assert m.press(KeyCode(vk=38)) is False

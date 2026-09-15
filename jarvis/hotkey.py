"""Global hotkey matching by physical key.

pynput's GlobalHotKeys compares typed characters, so Option/Shift (Option+J types "∆") and non-English
input sources break it. This matches the macOS virtual key code plus the exact set of held modifiers.
"""
from pynput.keyboard import Key, KeyCode

MODIFIERS = {
    Key.ctrl: "ctrl", Key.ctrl_l: "ctrl", Key.ctrl_r: "ctrl",
    Key.alt: "alt", Key.alt_l: "alt", Key.alt_r: "alt", Key.alt_gr: "alt",
    Key.cmd: "cmd", Key.cmd_l: "cmd", Key.cmd_r: "cmd",
    Key.shift: "shift", Key.shift_l: "shift", Key.shift_r: "shift",
}
ALIASES = {"ctrl": "ctrl", "control": "ctrl", "alt": "alt", "option": "alt", "cmd": "cmd", "command": "cmd",
           "shift": "shift"}
# macOS virtual key codes for the ANSI layout; the physical keys are the same under a non-Latin input source
VK = {"a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12,
      "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38,
      "k": 40, "n": 45, "m": 46, "space": 49}


def parse_hotkey(spec: str) -> tuple[frozenset[str], int]:
    mods: set[str] = set()
    trigger = None
    for part in spec.lower().split("+"):
        name = part.strip().strip("<>")
        if name in ALIASES:
            mods.add(ALIASES[name])
        elif name in VK:
            if trigger is not None:
                raise ValueError(f"hotkey {spec!r} has more than one non-modifier key")
            trigger = VK[name]
        else:
            raise ValueError(f"unsupported key {part!r} in hotkey {spec!r}")
    if trigger is None:
        raise ValueError(f"hotkey {spec!r} needs a non-modifier key")
    return frozenset(mods), trigger


def _vk(key) -> int | None:
    if isinstance(key, KeyCode):
        return key.vk
    if isinstance(key, Key):
        return getattr(key.value, "vk", None)
    return None


class HotkeyMatcher:
    def __init__(self, spec: str):
        self.modifiers, self.trigger = parse_hotkey(spec)
        self._down: set[str] = set()

    def press(self, key) -> bool:
        mod = MODIFIERS.get(key)
        if mod:
            self._down.add(mod)
            return False
        return _vk(key) == self.trigger and self._down == self.modifiers

    def release(self, key) -> None:
        mod = MODIFIERS.get(key)
        if mod:
            self._down.discard(mod)

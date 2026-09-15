from jarvis import notifier as nmod
from jarvis.notifier import Notifier, applescript_string


def test_applescript_string_escapes():
    assert applescript_string('say "hi" \\ ok') == '"say \\"hi\\" \\\\ ok"'
    assert applescript_string("merhaba dünya") == '"merhaba dünya"'


async def test_telegram_disabled_without_token():
    assert await Notifier(None, None, None).telegram("x") is False


async def test_desktop_runs_osascript(monkeypatch):
    calls = []

    class Proc:
        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        return Proc()

    monkeypatch.setattr(nmod.asyncio, "create_subprocess_exec", fake_exec)
    await Notifier(None, None, None).desktop("Jarvis · A", 'done "ok"')
    assert calls[0][0] == "osascript"
    assert 'display notification "done \\"ok\\"" with title "Jarvis · A"' in calls[0][2]

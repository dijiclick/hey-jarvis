from types import SimpleNamespace

from jarvis.app import JarvisApp


class FakeNotifier:
    def __init__(self):
        self.desktop_calls, self.telegram_calls = [], []

    async def desktop(self, title, body):
        self.desktop_calls.append((title, body))

    async def telegram(self, text):
        self.telegram_calls.append(text)
        return True


def make_app(away=False):
    settings = SimpleNamespace(home=None, db_path=":memory:", confirm_timeout_s=120, input_device="auto")
    app = JarvisApp(settings, audio_factory=lambda loop: None)
    app.notifier = FakeNotifier()
    app.voice = SimpleNamespace(is_open=False, is_away=lambda: away)
    return app


async def test_no_credits_is_explained_in_plain_words():
    app = make_app()
    with app.hub.subscribe() as queue:
        await app._explain_failure(RuntimeError("Error code: 429 - You have no credits remaining"))
        event = await queue.get()
    assert "no credits" in event.data["text"].lower()
    assert "platform.openai.com" in event.data["text"]
    title, body = app.notifier.desktop_calls[0]
    assert title == "Jarvis can't talk" and "credit" in body.lower()


async def test_a_rejected_key_says_which_file_to_fix():
    app = make_app()
    await app._explain_failure(RuntimeError("invalid_api_key: incorrect API key provided"))
    assert "~/.jarvis/.env" in app.notifier.desktop_calls[0][1]


async def test_a_timeout_says_it_will_recover():
    app = make_app()
    await app._explain_failure(TimeoutError("request timed out"))
    assert "did not answer in time" in app.notifier.desktop_calls[0][1]


async def test_an_unknown_failure_still_names_itself():
    app = make_app()
    await app._explain_failure(ValueError("something odd"))
    assert "ValueError" in app.notifier.desktop_calls[0][1]


async def test_telegram_only_when_the_user_is_away():
    near = make_app(away=False)
    await near._explain_failure(RuntimeError("no credits remaining"))
    assert near.notifier.telegram_calls == []

    far = make_app(away=True)
    await far._explain_failure(RuntimeError("no credits remaining"))
    assert far.notifier.telegram_calls and far.notifier.telegram_calls[0].startswith("⚠️")


async def test_a_broken_notifier_never_masks_the_original_failure():
    app = make_app()

    class Broken:
        async def desktop(self, *a):
            raise OSError("osascript missing")

        async def telegram(self, *a):
            raise OSError("no network")

    app.notifier = Broken()
    await app._explain_failure(RuntimeError("no credits remaining"))   # must not raise

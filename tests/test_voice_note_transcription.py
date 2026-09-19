from types import SimpleNamespace

from jarvis.telegram_inbox import transcribe_with_gemini


async def test_voice_notes_use_the_model_that_understood_persian():
    # measured on real Persian clips: flash-lite wrote "جارویس، ساعت چنده؟" as "Joe Arviza, so ATChande." (and, with
    # a hint, in Cyrillic); gemini-3.5-flash with a Persian hint got every clip right
    seen = {}

    class Models:
        def generate_content(self, model, contents):
            seen["model"], seen["prompt"] = model, contents[1]
            return SimpleNamespace(text="جارویس، ساعت چنده؟")

    text = await transcribe_with_gemini("key", b"OggS", client_factory=lambda key: SimpleNamespace(models=Models()))
    assert text == "جارویس، ساعت چنده؟"
    assert seen["model"] == "gemini-3.5-flash"
    assert "Persian" in seen["prompt"] and "never translate" in seen["prompt"].lower()


async def test_no_key_means_no_transcription():
    assert await transcribe_with_gemini(None, b"OggS") == ""


async def test_the_gemini_client_stays_open_for_the_whole_request():
    # the real google-genai client closes its connection when it is garbage-collected; calling
    # factory(key).models.generate_content(...) freed it mid-request ("the client has been closed")
    state = {"open": True}

    class Models:
        def generate_content(self, model, contents):
            if not state["open"]:
                raise RuntimeError("Cannot send a request, as the client has been closed.")
            return SimpleNamespace(text="آره انجام بده")

    class Client:
        def __init__(self):
            self.models = Models()

        def __del__(self):
            state["open"] = False

    assert await transcribe_with_gemini("key", b"OggS", client_factory=lambda key: Client()) == "آره انجام بده"

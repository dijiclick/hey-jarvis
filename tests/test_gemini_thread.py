import subprocess
import sys
import textwrap

# Runs in a fresh interpreter: LiveKit's plugin registry is process-global, so once any other test
# has imported the Google plugin on the main thread this bug can no longer be observed in-process.
WAKE_FROM_WORKER = textwrap.dedent("""
    import asyncio
    import threading
    from types import SimpleNamespace

    import jarvis.voice as voice  # imported on the main thread, as cli.main does

    settings = SimpleNamespace(
        voice_provider="gemini", gemini_api_key="gem-key", gemini_model="gemini-3.1-flash-live-preview",
        gemini_voice="Enceladus", default_language="English", openai_api_key=None, voice="cinder",
    )
    errors = []

    async def open_voice():
        voice.build_realtime_model(settings, http=None)

    def jarvis_loop():
        # the wake word, the hotkey and the menu's Talk all open the voice on this thread
        try:
            asyncio.run(open_voice())
        except Exception as e:
            errors.append(repr(e))

    t = threading.Thread(target=jarvis_loop, name="jarvis-loop")
    t.start()
    t.join()
    print("ERRORS:", errors)
    raise SystemExit(1 if errors else 0)
""")


def test_gemini_voice_opens_from_the_worker_thread_the_wake_word_uses():
    r = subprocess.run([sys.executable, "-c", WAKE_FROM_WORKER], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]

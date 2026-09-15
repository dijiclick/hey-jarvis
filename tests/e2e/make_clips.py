"""Generate 24 kHz mono WAV clips with OpenAI TTS for end-to-end runs."""
import json
import os
import sys
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

CLIPS = {
    "en_time": "Jarvis, what time is it?",
    "en_sandbox_file": "Jarvis, in the jarvis sandbox project, create a file called notes.txt containing the word hello.",
    "tr_sandbox_file": "Jarvis, jarvis sandbox projesinde merhaba.txt adında bir dosya oluştur ve içine merhaba yaz.",
    "en_push_main": "Jarvis, in the jarvis sandbox project, commit everything and push to main.",
    "en_yes": "Yes, go ahead.",
    "en_no": "No, don't do that.",
    "en_status": "Jarvis, what are you working on right now?",
}


def main(out_dir: str) -> None:
    key = os.environ.get("OPENAI_API_KEY") or dotenv_values(Path.home() / ".jarvis" / ".env")["OPENAI_API_KEY"]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, text in CLIPS.items():
        body = json.dumps({"model": "gpt-4o-mini-tts", "voice": "cedar", "input": text,
                           "response_format": "wav"}).encode()
        req = urllib.request.Request("https://api.openai.com/v1/audio/speech", data=body,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            (out / f"{name}.wav").write_bytes(resp.read())
        print("wrote", out / f"{name}.wav")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tests/e2e/out/clips")

import json
import os
from datetime import datetime, timezone

from jarvis.mac_actions import chat_message_arrived

SENT_AT = 1_800_000_000.0


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def transcript(root, records, touched=SENT_AT + 2):
    """A Claude Code chat transcript as the VS Code extension writes it: one JSON record per line."""
    folder = root / "-Users-me-Projects-superpower"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "session.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")  # json.dumps escapes Persian as \\u
    os.utime(path, (touched, touched))
    return path


def user(text, ts):
    return {"type": "user", "timestamp": iso(ts), "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def assistant(text, ts):
    return {"type": "assistant", "timestamp": iso(ts), "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def test_a_new_user_message_with_the_prompt_counts(tmp_path):
    transcript(tmp_path, [user("What does the API cost per minute?", SENT_AT + 1)])
    assert chat_message_arrived("What does the API cost per minute?", SENT_AT, tmp_path) is True


def test_a_persian_prompt_matches_even_when_escaped(tmp_path):
    transcript(tmp_path, [user("هزینه API در دقیقه چقدر است؟", SENT_AT + 1)])
    assert chat_message_arrived("هزینه API در دقیقه چقدر است؟", SENT_AT, tmp_path) is True


def queued(text, ts):
    return {"type": "attachment", "timestamp": iso(ts), "attachment": {"type": "queued_command", "prompt": text}}


def test_a_message_queued_while_the_chat_is_busy_counts(tmp_path):
    # seen live: sent while Claude was mid-answer, the prompt was saved as a queued_command attachment, not a user turn
    transcript(tmp_path, [queued("JARVIS live test (sent by the fast lane, please ignore)", SENT_AT + 2)])
    assert chat_message_arrived("JARVIS live test (sent by the fast lane, please ignore)", SENT_AT, tmp_path) is True


def test_the_assistant_quoting_the_prompt_does_not_count(tmp_path):
    transcript(tmp_path, [assistant("You asked: What does the API cost per minute?", SENT_AT + 1)])
    assert chat_message_arrived("What does the API cost per minute?", SENT_AT, tmp_path) is False


def test_the_same_message_sent_earlier_does_not_count(tmp_path):
    transcript(tmp_path, [user("run the tests", SENT_AT - 600)])
    assert chat_message_arrived("run the tests", SENT_AT, tmp_path) is False


def test_a_transcript_untouched_since_sending_is_ignored(tmp_path):
    transcript(tmp_path, [user("run the tests", SENT_AT + 1)], touched=SENT_AT - 60)
    assert chat_message_arrived("run the tests", SENT_AT, tmp_path) is False

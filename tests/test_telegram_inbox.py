from jarvis.telegram_inbox import TelegramInbox

OWNER = "6310000001"
STARTED = 1_800_000_000


def update(uid, text=None, chat=OWNER, date=STARTED + 10, voice=None):
    msg = {"message_id": uid, "date": date, "chat": {"id": int(chat)}}
    if text is not None:
        msg["text"] = text
    if voice is not None:
        msg["voice"] = {"file_id": voice, "duration": 3}
    return {"update_id": uid, "message": msg}


class Phone:
    """Stands in for Telegram and the rest of Jarvis: records what the owner would see and what ran."""

    def __init__(self, batches):
        self.batches, self.offsets, self.sent, self.orders, self.cancelled = list(batches), [], [], [], 0

    async def fetch(self, offset):
        self.offsets.append(offset)
        batch = self.batches.pop(0) if self.batches else []
        if isinstance(batch, Exception):
            raise batch
        return batch

    async def send(self, text):
        self.sent.append(text)

    async def download(self, file_id):
        return b"OggS-voice-" + file_id.encode()

    async def transcribe(self, audio):
        return "open WhatsApp and tell Sam I'm on my way"

    def order(self, text):
        self.orders.append(text)
        return 41

    def status(self):
        return "Job 41 in home is running."

    async def cancel(self):
        self.cancelled += 1
        return "Cancelled job 41."


def inbox(phone):
    return TelegramInbox(fetch=phone.fetch, send=phone.send, download=phone.download, transcribe=phone.transcribe,
                         order=phone.order, status=phone.status, cancel=phone.cancel, owner_chat_id=OWNER,
                         started_at=STARTED)


async def test_a_text_order_from_the_owner_runs_and_is_acknowledged():
    phone = Phone([[update(7, "check my Gmail for new leads")]])
    await inbox(phone).poll_once()
    assert phone.orders == ["check my Gmail for new leads"]
    assert phone.sent and "41" in phone.sent[0], "the owner learns right away that it started"


async def test_a_stranger_can_never_give_orders():
    # the bot controls the whole Mac, so only the owner's chat is obeyed
    phone = Phone([[update(7, "delete everything", chat="999")]])
    await inbox(phone).poll_once()
    assert phone.orders == [] and phone.sent == []


async def test_messages_from_before_jarvis_started_are_not_run():
    phone = Phone([[update(7, "/start", date=STARTED - 60), update(8, "send the invoice", date=STARTED - 30)]])
    await inbox(phone).poll_once()
    assert phone.orders == [] and phone.sent == []


async def test_status_and_cancel_answer_directly():
    phone = Phone([[update(7, "/status"), update(8, "/cancel")]])
    await inbox(phone).poll_once()
    assert phone.orders == []
    assert phone.sent == ["Job 41 in home is running.", "Cancelled job 41."] and phone.cancelled == 1


async def test_a_voice_note_is_transcribed_then_run():
    phone = Phone([[update(7, voice="AwACAgQ")]])
    await inbox(phone).poll_once()
    assert phone.orders == ["open WhatsApp and tell Sam I'm on my way"]
    assert "open WhatsApp and tell Sam I'm on my way" in phone.sent[0], "say what was heard, so mishearing shows"


async def test_the_read_position_moves_past_handled_messages():
    phone = Phone([[update(7, "one"), update(9, "two")], []])
    box = inbox(phone)
    await box.poll_once()
    await box.poll_once()
    assert phone.offsets == [None, 10]


async def test_a_network_error_does_not_stop_the_listener():
    phone = Phone([ConnectionError("offline"), [update(7, "still here?")]])
    box = inbox(phone)
    await box.poll_once()
    await box.poll_once()
    assert phone.orders == ["still here?"]

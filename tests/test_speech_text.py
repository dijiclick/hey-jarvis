import pytest

from jarvis.speech_text import detect_language, is_goodbye, spoken_text


@pytest.mark.parametrize("text", ["bye bye", "Bye!", "Goodbye Jarvis.", "okay, see you", "خداحافظ", "بای بای",
                                  "مرسی، خدافظ", "thanks, that's all", "مرسی جارویس! خدا حافظ", "خدا حافظ",
                                  # the transcriber sometimes writes an English "bye bye" in Hindi script
                                  "बाय बाय", "बाय", "Бай бай", "До свидания!",
                                  # dismissals count only when they are the whole sentence
                                  "turn off", "Jarvis, turn off.", "you can turn off now", "I don't need you",
                                  "I don't need you anymore, thanks", "go to sleep", "stop listening",
                                  "خاموش شو", "جارویس خاموش شو", "دیگه کاری ندارم", "لازمت ندارم", "برو بخواب",
                                  "Kapan", "sana ihtiyacım yok", "görüşürüz", "tamam bu kadar",
                                  "Выключись", "ты мне не нужен", "Пока", "на этом всё"])
def test_goodbye(text):
    assert is_goodbye(text) is True


@pytest.mark.parametrize("text", ["write a goodbye email to Ali about the meeting", "open Safari",
                                  "یه ایمیل خداحافظی به علی بنویس و بفرست", "", "hmm",
                                  "turn off the wifi", "turn off dark mode", "I don't need you to send it",
                                  "وای فای رو خاموش کن", "کامپیوتر رو خاموش کن", "bluetooth'u kapat",
                                  "пока подожди", "выключи свет"])
def test_not_goodbye(text):
    assert is_goodbye(text) is False


def test_strips_code_blocks_and_markdown():
    md = ("## Done\nFixed **login** in `auth.ts`.\n```ts\nconst a = 1\n```\n- tests pass\n"
          "See [the PR](https://github.com/x/y/pull/1) and https://vercel.app/abc")
    out = spoken_text(md)
    for bad in ["```", "**", "#", "https", "const a"]:
        assert bad not in out
    assert "Fixed login in auth.ts." in out
    assert "tests pass" in out
    assert "the PR" in out


def test_paths_become_basenames():
    assert spoken_text("Edited /Users/me/Projects/ShopFront/app/login/page.tsx") == "Edited page.tsx."


def test_truncates_at_sentence_boundary():
    out = spoken_text("This is one sentence. " * 100, limit=100)
    assert len(out) <= 101
    assert out.endswith(".") or out.endswith("…")


def test_right_to_left_text_untouched():
    s = "باگ لاگین درست شد. همه تست‌ها پاس شدند."
    assert spoken_text(s) == s


def test_detect_language():
    assert detect_language("سلام جارویس ساعت چنده") == "Persian"
    assert detect_language("Hey Jarvis, what time is it?") == "English"
    assert detect_language("Merhaba, bugün hava nasıl? Işığı aç") == "Turkish"
    assert detect_language("Привет") == "Russian"
    assert detect_language("  ...  ") is None

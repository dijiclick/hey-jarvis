import re

_FENCE = re.compile(r"```.*?```", re.S)
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_PATH = re.compile(r"(?:~|/)(?:[\w.\-@]+/)+([\w.\-@]+)")


def spoken_text(md: str, limit: int = 700) -> str:
    s = _FENCE.sub(" ", md)
    s = _LINK.sub(r"\1", s)
    s = _URL.sub("a link", s)
    s = s.replace("`", "")
    s = _PATH.sub(r"\1", s)
    s = re.sub(r"^\s{0,3}#{1,6}\s*", "", s, flags=re.M)
    s = re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", s, flags=re.M)
    s = re.sub(r"\*\*|__|(?<!\w)\*(?!\s)|\|", "", s)
    s = re.sub(r"[ \t]*\n+[ \t]*", ". ", s)
    s = re.sub(r"([.!?؟])\s*\.", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    if s and s[-1] not in ".!?؟…":
        s += "."
    if len(s) <= limit:
        return s
    cut = s[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("؟ "))
    return cut[: end + 1] if end > limit // 3 else cut.rstrip() + "…"


# the transcriber sometimes writes an English "bye" in another script (Hindi "बाय", Russian "бай")
_GOODBYE_WORDS = {"bye", "byebye", "goodbye", "خداحافظ", "خدافظ", "بای", "خداحافظی", "बाय", "बाई", "अलविदा", "бай"}
_GOODBYE_PHRASES = ("see you", "good bye", "bye bye", "that's all", "thats all", "güle güle", "hoşça kal",
                    "بای بای", "до свидания")


# polite words around a dismissal ("Jarvis, you can turn off now, thanks") that don't change its meaning
_FILLER = {"jarvis", "hey", "ok", "okay", "please", "thanks", "now", "anymore", "جارویس", "مرسی", "ممنون", "خب",
           "باشه", "لطفا", "tamam", "teşekkürler", "sağol", "спасибо", "ладно", "джарвис"}
# dismissals end the conversation only when they are the whole sentence: "turn off" does, "turn off the wifi" doesn't
_DISMISSALS = ("turn off", "you can turn off", "switch off", "i don't need you", "i dont need you",
               "i do not need you", "go to sleep", "stop listening", "that's it", "you can go", "good night",
               "خاموش شو", "خاموش باش", "دیگه کاری ندارم", "کاری ندارم", "لازمت ندارم", "دیگه لازمت ندارم",
               "برو بخواب", "بسه", "کافیه", "تمام", "همین",
               "kapan", "sana ihtiyacım yok", "görüşürüz", "bu kadar", "uyu", "hoşçakal", "iyi geceler",
               "выключись", "отключись", "ты мне не нужен", "ты мне больше не нужен", "пока", "пока пока",
               "на этом всё", "спокойной ночи")


def _words(text: str) -> list[str]:
    s = text.lower().replace("‌", " ").replace("’", "'").replace("ё", "е").strip()
    # Devanagari vowel signs are not \w, so include the whole block or "बाय" splits in two
    return re.findall(r"[\w'\u0900-\u097f]+", s)


def _core(text: str) -> str:
    return " ".join(w for w in _words(text) if w not in _FILLER)


_DISMISSAL_CORES = {_core(p) for p in _DISMISSALS}


def is_goodbye(text: str) -> bool:
    """A short sign-off like "bye bye", "خداحافظ" or "turn off"; long requests that merely mention goodbye don't count."""
    s = text.lower().replace("‌", " ").strip()
    if _core(text) in _DISMISSAL_CORES:
        return True
    words = _words(text)
    if not words or len(words) > 5:
        return False
    # speech-to-text often splits compound words in two, so also match with spaces removed
    joined = re.sub(r"[\s\W_]+", "", s)
    return (bool(set(words) & _GOODBYE_WORDS) or any(p in s for p in _GOODBYE_PHRASES)
            or any(w in joined for w in ("خداحافظ", "خدافظ")))


def detect_language(text: str) -> str | None:
    if re.search(r"[؀-ۿ]", text):
        return "Persian"
    if re.search(r"[Ѐ-ӿ]", text):
        return "Russian"
    if re.search(r"[ğĞşŞıİ]", text):
        return "Turkish"
    if re.search(r"[A-Za-z]", text):
        return "English"
    return None


def ends_with_question(text: str) -> bool:
    """True when a report closes by asking the user something, so their next yes or no answers it."""
    return text.rstrip().endswith(("?", "؟"))


# a sentence decides the conversation language only when it is clearly in one language: stray words, names and
# mis-transcribed fragments ("مسج ایلاف پک" for English speech) must not flip it
SWITCH_MIN_WORDS = 4
SWITCH_SHARE = 0.7
LANGUAGE_NAMES = {"english": "English", "persian": "Persian", "farsi": "Persian", "turkish": "Turkish",
                  "russian": "Russian", "انگلیسی": "English", "فارسی": "Persian", "ترکی": "Turkish",
                  "روسی": "Russian", "ingilizce": "English", "farsça": "Persian", "türkçe": "Turkish",
                  "rusça": "Russian"}
_ASKING = re.compile(r"\b(speak|talk|answer|reply|respond|say it|switch to)\b|حرف بزن|صحبت کن|بگو|جواب بده|"
                     r"konuş|cevap ver", re.I)


def sentence_language(text: str) -> str | None:
    """The language of a whole sentence, or None when it is too short or mixes languages."""
    words = re.findall(r"\w+", text)
    if len(words) < SWITCH_MIN_WORDS:
        return None
    persian = sum(1 for w in words if re.search(r"[؀-ۿ]", w))
    russian = sum(1 for w in words if re.search(r"[Ѐ-ӿ]", w))
    latin = len(words) - persian - russian
    for count, language in ((persian, "Persian"), (russian, "Russian")):
        if count / len(words) >= SWITCH_SHARE:
            return language
    if latin / len(words) >= SWITCH_SHARE:
        return detect_language(" ".join(w for w in words if not re.search(r"[؀-ۿЀ-ӿ]", w)))
    return None


def requested_language(text: str) -> str | None:
    """The language the user explicitly asks for ("speak Persian", "به انگلیسی بگو", "Türkçe konuş"), or None."""
    lowered = text.lower()
    if not _ASKING.search(lowered):
        return None
    return next((language for word, language in LANGUAGE_NAMES.items() if word in lowered), None)

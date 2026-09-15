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


_GOODBYE_WORDS = {"bye", "byebye", "goodbye", "خداحافظ", "خدافظ", "بای", "خداحافظی"}
_GOODBYE_PHRASES = ("see you", "good bye", "bye bye", "that's all", "thats all", "güle güle", "hoşça kal",
                    "بای بای")


def is_goodbye(text: str) -> bool:
    """A short sign-off like "bye bye" or "خداحافظ"; long requests that merely mention goodbye don't count."""
    s = text.lower().replace("‌", " ").strip()
    words = re.findall(r"[\w']+", s)
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

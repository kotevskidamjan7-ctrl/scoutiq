"""Name and position normalization shared by all importers and the player linker."""

import re
import unicodedata

# Letters that Unicode decomposition does not reduce to ASCII on its own
_SPECIAL = str.maketrans(
    {
        "ø": "o", "Ø": "o", "ß": "ss", "đ": "dj", "Đ": "dj", "ł": "l", "Ł": "l",
        "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe", "ı": "i", "þ": "th", "ð": "d",
    }
)
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")


def normalize_name(name: str | None) -> str:
    """'Martin Ødegaard' -> 'martin odegaard'; 'Luka Modrić' -> 'luka modric'."""
    if not name:
        return ""
    text = name.translate(_SPECIAL)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("-", " ").replace("'", "")
    text = _NON_ALNUM.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


# Transfermarkt `players.position` values -> ScoutIQ position groups
TM_POSITION_GROUP = {
    "Goalkeeper": "GK",
    "Defender": "DEF",
    "Midfield": "MID",
    "Attack": "FWD",
}


def tm_position_group(position: str | None) -> str | None:
    """Unknown or 'Missing' positions stay None (reported, never guessed)."""
    return TM_POSITION_GROUP.get(position or "")

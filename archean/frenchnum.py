"""Deterministic parsing of French numbers, amounts and dates.

No model, no network, no global state, no configuration. Given the same string
this module returns the same answer forever, which is what lets the numbers in
``results.json`` be defended six months from now.

Scope
-----
This is not a general French NLP component. It covers the subset the ARCHEAN
corpus actually contains, audited line by line over all 11 254 OCR lines and
recorded in DISCOVERY.md §11.1. Where the standard grammar is closed and cheap
to implement, the implementation is complete anyway; the distinction between
*attested* and *implemented for completeness* is kept explicit below so that
coverage is never mistaken for evidence.

Attested spelled numbers
    ``trente sept mille`` (37 000), ``trois cent soixante dix`` (370),
    ``cent cinquante mille`` (150 000), ``mille cinq cent`` (1 500),
    ``deux cent mille`` (200 000), ``deux mille`` (2 000), ``cinq cents`` (500),
    ``deux cent quatre-vingt-quinze`` (295), ``cent`` (100).

Implemented but NOT attested here
    ``million``, ``milliard``, ``vingts`` as a plural, ``soixante-et-onze`` and
    the rest of the 70/90 family beyond ``soixante dix`` and
    ``quatre-vingt-quinze``.

Deliberately NOT implemented
    ``mil`` as the archaic year form (*mil neuf cent*). It has zero occurrences
    in this corpus, and accepting it would make a misread ``mille`` silently
    parse as a different number. Ordinals (*premier*, *deuxième*). Decimals
    written out in words. Negative numbers.

Separators
    Hyphen and space are interchangeable. The corpus writes
    ``trois cent soixante dix`` without hyphens four lines from
    ``quatre-vingt-quinze`` with them, and ``deux mille dix-sept`` alongside
    ``deux mille dix huit``. Requiring either one fails on real documents.

Refusing rather than guessing
    Every entry point raises on input it cannot read unambiguously. Nothing
    here ever returns a "best effort" value. A partial date stays partial: a
    year without a day does not acquire one.
"""

from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

__all__ = [
    "FrenchParseError",
    "FrenchNumberError",
    "FrenchDateError",
    "DateParts",
    "NumeralRepair",
    "parse_french_integer",
    "try_parse_french_integer",
    "parse_french_amount",
    "parse_french_month",
    "parse_french_year",
    "parse_french_date",
    "parse_french_date_parts",
    "repair_numeral",
    "looks_like_numeral",
]


class FrenchParseError(ValueError):
    """Base class: the input could not be read unambiguously."""


class FrenchNumberError(FrenchParseError):
    """A number could not be parsed."""


class FrenchDateError(FrenchParseError):
    """A date could not be parsed."""


# ---------------------------------------------------------------------------
# shared text handling
# ---------------------------------------------------------------------------


def _fold(s: str) -> str:
    """Lower-case, strip accents, normalize whitespace and apostrophes.

    Accent folding is required because OCR emits both ``février`` and
    ``FEVRIER`` for the same month.
    """
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


# ---------------------------------------------------------------------------
# spelled-out integers
# ---------------------------------------------------------------------------

#: Words worth 0-16 plus the irregular teens, as single lexemes.
_UNITS: Final[dict[str, int]] = {
    "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4,
    "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
    "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15,
    "seize": 16,
}

#: Round tens that stand alone. 70 and 90 are built additively from 60 and 80.
_TENS: Final[dict[str, int]] = {
    "vingt": 20, "vingts": 20, "trente": 30, "quarante": 40,
    "cinquante": 50, "soixante": 60,
}

_HUNDRED: Final[frozenset[str]] = frozenset({"cent", "cents"})

#: Scale words, largest first. ``mil`` is intentionally absent; see the module
#: docstring.
_SCALES: Final[dict[str, int]] = {
    "milliard": 1_000_000_000, "milliards": 1_000_000_000,
    "million": 1_000_000, "millions": 1_000_000,
    "mille": 1_000, "milles": 1_000,
}

_FILLER: Final[frozenset[str]] = frozenset({"et"})

_KNOWN_WORDS: Final[frozenset[str]] = frozenset(
    set(_UNITS) | set(_TENS) | set(_HUNDRED) | set(_SCALES) | set(_FILLER)
)


def _tokenize_number(text: str) -> list[str]:
    """Split on spaces and hyphens, which this corpus uses interchangeably."""
    folded = _fold(text)
    if not folded:
        raise FrenchNumberError("empty input")
    return [t for t in re.split(r"[\s\-]+", folded) if t]


def _merge_quatre_vingt(tokens: list[str]) -> list[str]:
    """Collapse ``quatre vingt(s)`` into one lexeme worth 80.

    Without this, ``quatre`` and ``vingt`` would be added as 4 + 20. French has
    no construction where those two words are adjacent and not 80, so the merge
    is safe.
    """
    out: list[str] = []
    i = 0
    while i < len(tokens):
        if (
            tokens[i] == "quatre"
            and i + 1 < len(tokens)
            and tokens[i + 1] in ("vingt", "vingts")
        ):
            out.append("quatre-vingt")
            i += 2
        else:
            out.append(tokens[i])
            i += 1
    return out


def parse_french_integer(text: str) -> int:
    """Parse a spelled-out French integer.

    >>> parse_french_integer("trois cent soixante dix")
    370
    >>> parse_french_integer("trente-sept mille")
    37000
    >>> parse_french_integer("deux cent quatre-vingt-quinze")
    295

    Raises :class:`FrenchNumberError` on anything it cannot read exactly. It
    never guesses and never partially parses: a single unknown word fails the
    whole string, because a silently dropped word changes the value.
    """
    tokens = _merge_quatre_vingt(_tokenize_number(text))

    unknown = [t for t in tokens if t not in _KNOWN_WORDS and t != "quatre-vingt"]
    if unknown:
        raise FrenchNumberError(
            f"not French number words: {unknown!r} in {text!r}. "
            f"Refusing to parse partially, because dropping a word changes "
            f"the value."
        )
    if all(t in _FILLER for t in tokens):
        raise FrenchNumberError(f"no number words in {text!r}")

    total = 0          # completed scale groups
    current = 0        # the group being built
    group_has_content = False
    seen_scales: list[int] = []
    # Value of the immediately preceding unit word, or None. Used to reject
    # "deux trois" while allowing "dix-sept" (10 + 7 = 17) and
    # "soixante dix sept" (60 + 10 + 7 = 77).
    last_unit: int | None = None

    for tok in tokens:
        if tok in _FILLER:
            continue

        if tok in _UNITS:
            value = _UNITS[tok]
            # Only "dix" may be followed by another unit, forming 17-19.
            if last_unit is not None and last_unit != 10:
                raise FrenchNumberError(
                    f"two unit words in a row in {text!r} ({last_unit} then "
                    f"{value}); this is not a French numeral"
                )
            if last_unit == 10 and not 7 <= value <= 9:
                raise FrenchNumberError(
                    f"{text!r}: 'dix' may only be followed by sept, huit or "
                    f"neuf, forming 17-19"
                )
            current += value
            group_has_content = True
            last_unit = value if last_unit is None else last_unit + value

        elif tok == "quatre-vingt":
            current += 80
            group_has_content = True
            last_unit = None

        elif tok in _TENS:
            current += _TENS[tok]
            group_has_content = True
            last_unit = None

        elif tok in _HUNDRED:
            multiplier = current if current else 1
            if multiplier > 99:
                raise FrenchNumberError(
                    f"{multiplier} hundreds in {text!r} is not a French numeral"
                )
            current = multiplier * 100
            group_has_content = True
            last_unit = None

        else:  # a scale word
            scale = _SCALES[tok]
            if seen_scales and scale >= seen_scales[-1]:
                raise FrenchNumberError(
                    f"scale words out of order in {text!r}: {tok!r} cannot "
                    f"follow a smaller or equal scale"
                )
            seen_scales.append(scale)
            multiplier = current if group_has_content else 1
            total += multiplier * scale
            current = 0
            group_has_content = False
            last_unit = None

    return total + current


def try_parse_french_integer(text: str) -> int | None:
    """:func:`parse_french_integer`, returning ``None`` instead of raising."""
    try:
        return parse_french_integer(text)
    except FrenchParseError:
        return None


# ---------------------------------------------------------------------------
# numeric amounts written in digits
# ---------------------------------------------------------------------------

# French groups thousands with "." or a space and marks decimals with ",".
# In this corpus: "37.000", "368.102", "217 241", "150 000,00", "259 480,92".
# Reading "368.102" as 368.102 instead of 368102 would be a three-orders-of-
# magnitude error in the share capital, so this is not optional.
_AMOUNT_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<int>\d{1,3}(?:[ .]\d{3})+|\d+)(?:,(?P<frac>\d{1,2}))?$"
)


def parse_french_amount(text: str) -> Decimal:
    """Parse a digit-written French amount into an exact :class:`Decimal`.

    >>> parse_french_amount("368.102")
    Decimal('368102')
    >>> parse_french_amount("217 241")
    Decimal('217241')
    >>> parse_french_amount("259 480,92")
    Decimal('259480.92')

    ``.`` and a space are thousands separators; ``,`` is the decimal mark.
    Ambiguous groupings such as ``1.23`` are refused rather than guessed.
    """
    s = _fold(text).replace(" ", " ").strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        raise FrenchNumberError("empty amount")

    m = _AMOUNT_RE.match(s)
    if not m:
        raise FrenchNumberError(
            f"{text!r} is not an unambiguous French amount. Thousands are "
            f"grouped by '.' or ' ' in threes and decimals marked by ','."
        )

    integer = m.group("int").replace(" ", "").replace(".", "")
    frac = m.group("frac")
    try:
        return Decimal(f"{integer}.{frac}") if frac else Decimal(integer)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the regex
        raise FrenchNumberError(f"cannot read amount {text!r}") from exc


# ---------------------------------------------------------------------------
# dates
# ---------------------------------------------------------------------------

_MONTHS: Final[dict[str, int]] = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12,
}
_MONTH_ALT: Final[re.Pattern[str]] = re.compile(
    r"\b(janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|"
    r"octobre|novembre|decembre)\b"
)


@dataclass(frozen=True)
class DateParts:
    """Whatever of a date the text actually stated. ``None`` means absent.

    The corpus typesets spelled dates across two lines — ``L'an deux mille
    dix-sept,`` then ``Le vingt-et-un février,`` — so a single line often
    yields only part of a date. Combining parts from different lines is a
    layout decision for the caller, not something this module invents.
    """

    day: int | None = None
    month: int | None = None
    year: int | None = None
    day_month_ambiguous: bool = False

    @property
    def is_complete(self) -> bool:
        return None not in (self.day, self.month, self.year)

    def to_date(self) -> _dt.date:
        if not self.is_complete:
            raise FrenchDateError(
                f"incomplete date {self}; refusing to invent the missing part"
            )
        assert self.year is not None and self.month is not None
        assert self.day is not None
        return _dt.date(self.year, self.month, self.day)

    def iso(self) -> str:
        return self.to_date().isoformat()


def parse_french_month(text: str) -> int:
    """Month name to 1-12. Accepts any case and accented or unaccented forms."""
    folded = _fold(text)
    if folded in _MONTHS:
        return _MONTHS[folded]
    raise FrenchDateError(f"{text!r} is not a French month name")


def parse_french_year(text: str) -> int:
    """Parse a year written in digits or in words.

    >>> parse_french_year("2005")
    2005
    >>> parse_french_year("deux mille dix-sept")
    2017

    Two-digit years are refused: ``05`` could be 1905 or 2005 and nothing in
    the string decides it.
    """
    folded = _fold(text)
    folded = re.sub(r"^l'an\s+", "", folded)
    folded = folded.rstrip(",. ")

    if folded.isdigit():
        if len(folded) != 4:
            raise FrenchDateError(
                f"{text!r}: only four-digit years are accepted; {folded!r} is "
                f"ambiguous about its century"
            )
        return int(folded)

    value = try_parse_french_integer(folded)
    if value is None:
        raise FrenchDateError(f"{text!r} is not a year")
    if not 1000 <= value <= 2999:
        raise FrenchDateError(
            f"{text!r} parses to {value}, which is not a plausible year"
        )
    return value


_NUMERIC_DATE: Final[re.Pattern[str]] = re.compile(
    r"\b(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})\b"
)
_DAY_MONTH_YEAR: Final[re.Pattern[str]] = re.compile(
    r"\b(\d{1,2})(?:er)?\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})\b"
)
_DAY_MONTH: Final[re.Pattern[str]] = re.compile(
    r"\b(\d{1,2})(?:er)?\s+(" + "|".join(_MONTHS) + r")\b"
)


def parse_french_date_parts(text: str) -> DateParts:
    """Extract whatever date information a string states. Never invents.

    Handles the three shapes present in the corpus:

    >>> parse_french_date_parts("Le 17 mai 2005").iso()
    '2005-05-17'
    >>> parse_french_date_parts("enregistre le 27/06/2008").iso()
    '2008-06-27'
    >>> parse_french_date_parts("Le vingt neuf janvier deux mille treize").iso()
    '2013-01-29'

    and returns partial results for the split preamble form rather than
    guessing the rest:

    >>> parse_french_date_parts("Le vingt-et-un février,")
    DateParts(day=21, month=2, year=None, day_month_ambiguous=False)
    >>> parse_french_date_parts("L'an deux mille dix-sept,")
    DateParts(day=None, month=None, year=2017, day_month_ambiguous=False)
    """
    folded = _fold(text)
    if not folded:
        raise FrenchDateError("empty input")

    # -- dd/mm/yyyy ----------------------------------------------------
    m = _NUMERIC_DATE.search(folded)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not 1 <= a <= 31 or not 1 <= b <= 12:
            raise FrenchDateError(
                f"{text!r}: {a}/{b} is not a valid day/month pair. French "
                f"dates are day-first."
            )
        parts = DateParts(
            day=a, month=b, year=year, day_month_ambiguous=(a <= 12)
        )
        parts.to_date()  # rejects 31/02
        return parts

    # -- numeric day + month word + numeric year ------------------------
    m = _DAY_MONTH_YEAR.search(folded)
    if m:
        parts = DateParts(
            day=int(m.group(1)),
            month=_MONTHS[m.group(2)],
            year=int(m.group(3)),
        )
        parts.to_date()
        return parts

    # -- fully or partly spelled ----------------------------------------
    month_match = _MONTH_ALT.search(folded)
    if month_match:
        month = _MONTHS[month_match.group(1)]
        before = folded[: month_match.start()]
        after = folded[month_match.end():]

        day = _spelled_day(before)
        if day is None:
            m2 = re.search(r"\b(\d{1,2})(?:er)?\s*$", before.strip())
            day = int(m2.group(1)) if m2 else None

        year = _trailing_year(after)
        parts = DateParts(day=day, month=month, year=year)
        if parts.is_complete:
            parts.to_date()
        return parts

    # -- numeric day + month word, no year ------------------------------
    m = _DAY_MONTH.search(folded)
    if m:
        return DateParts(day=int(m.group(1)), month=_MONTHS[m.group(2)])

    # -- a bare year, spelled or not ------------------------------------
    year = _trailing_year(folded)
    if year is not None:
        return DateParts(year=year)

    raise FrenchDateError(f"no date found in {text!r}")


def _spelled_day(before: str) -> int | None:
    """Read a spelled day-of-month from the words before a month name."""
    words = [
        w for w in re.split(r"[\s\-]+", before.strip().rstrip(","))
        if w and w not in {"le", "du", "ce", "l'an", "lan"}
    ]
    while words and words[0] not in _KNOWN_WORDS:
        words.pop(0)
    if not words:
        return None
    value = try_parse_french_integer(" ".join(words))
    if value is None or not 1 <= value <= 31:
        return None
    return value


def _trailing_year(after: str) -> int | None:
    """Read a year from the words after a month name, if one is stated."""
    tail = after.strip().strip(",.").strip()
    if not tail:
        return None
    m = re.search(r"\b(\d{4})\b", tail)
    if m:
        return int(m.group(1))
    words = [w for w in re.split(r"[\s\-]+", tail) if w]
    # drop any leading words that are not number words ("l'an", "le", ...)
    while words and words[0] not in _KNOWN_WORDS:
        words.pop(0)
    # take the longest leading run that is still a plausible year
    for end in range(len(words), 0, -1):
        value = try_parse_french_integer(" ".join(words[:end]))
        if value is not None and 1000 <= value <= 2999:
            return value
    return None


def parse_french_date(text: str) -> _dt.date:
    """A complete date, or an error. Never a partial one.

    >>> parse_french_date("EN DATE DU 27 JUIN 2008").isoformat()
    '2008-06-27'
    """
    return parse_french_date_parts(text).to_date()


# ===========================================================================
# SEPARATE LAYER: OCR numeral repair
#
# Nothing above this line ever repairs anything. This layer is opt-in, reports
# every change it makes, and is deliberately narrow.
#
# Why it is this narrow: scanning the corpus for tokens within edit distance 1
# of a French number or month word returns `nombre` (143x), `mais` (33x),
# `main` (16x) and `d'eux` (12x) -- all ordinary French words, one edit from
# `novembre`, `mai`, `mai` and `deux`. A similarity-based repairer would
# corrupt 204 correct tokens to fix 8 broken ones. So every rule below is an
# exact substitution, gated on the token already looking like a numeral, and
# each one cites the corpus token that motivated it.
# ===========================================================================

#: Digit lookalikes, each with the corpus token that justifies it.
_DIGIT_CONFUSIONS: Final[dict[str, tuple[str, str]]] = {
    "o": ("0", "37.0o0 -> 37.000, constitution art.7 (…ec5 p.3)"),
    "O": ("0", "same glyph confusion as 'o', upper case"),
    "s": ("5", "200s -> 2005, 'le 17 mai 200s' (…ec4 p.6)"),
    "S": ("5", "26S6 -> 2656, greffe stamp"),
}

#: Non-digit characters allowed inside a numeral without being a corruption.
_NUMERAL_PUNCT: Final[frozenset[str]] = frozenset({".", ",", " ", " "})

#: Word-level repairs. Each key is not a French word, so there is no real word
#: to damage.
_WORD_REPAIRS: Final[dict[str, tuple[str, str]]] = {
    "cing": ("cinq", "'cing cents euros' and 'delai maximum de cing' (stamps)"),
}


@dataclass(frozen=True)
class NumeralRepair:
    """A repair that was applied, and why. Always reported, never silent."""

    original: str
    repaired: str
    rules: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.original != self.repaired


def looks_like_numeral(token: str) -> bool:
    """True when a token is shaped like a number that OCR has damaged.

    The guard that keeps this layer from touching French words. A token
    qualifies only if it holds at least two real digits, every non-digit
    character is either numeral punctuation or a documented digit lookalike,
    and it contains at least one of those lookalike *letters* — so a clean
    ``27/06/2008`` or ``2/3`` is never a candidate for repair.
    """
    t = token.strip()
    if len(t) < 2:
        return False
    digits = sum(c.isdigit() for c in t)
    if digits < 2:
        return False
    has_confusable_letter = False
    for c in t:
        if c.isdigit() or c in _NUMERAL_PUNCT:
            continue
        if c in _DIGIT_CONFUSIONS:
            has_confusable_letter = True
            continue
        if c == "/":
            continue
        return False
    return has_confusable_letter


def repair_numeral(token: str) -> NumeralRepair:
    """Apply the documented repairs to one token.

    >>> repair_numeral("37.0o0").repaired
    '37.000'
    >>> repair_numeral("200s").repaired
    '2005'
    >>> repair_numeral("soixante").changed
    False

    A token that is not numeral-shaped is returned untouched. The result always
    says which rules fired, so a caller can carry the caveat into a note rather
    than presenting a repaired figure as if the document had printed it.
    """
    stripped = token.strip()

    word = _fold(stripped)
    if word in _WORD_REPAIRS:
        replacement, why = _WORD_REPAIRS[word]
        return NumeralRepair(token, replacement, (f"word {word!r}: {why}",))

    if not looks_like_numeral(stripped):
        return NumeralRepair(token, token, ())

    out: list[str] = []
    rules: list[str] = []
    for c in stripped:
        if c in _DIGIT_CONFUSIONS:
            digit, why = _DIGIT_CONFUSIONS[c]
            out.append(digit)
            rules.append(f"{c!r}->{digit!r}: {why}")
        elif c == "/":
            # Only reachable once a confusable letter is present, so this is
            # never a date. Corpus case: '400/o0o' -> '400.000'.
            out.append(".")
            rules.append("'/'->'.': 400/o0o -> 400.000 (…ec0 p.4)")
        else:
            out.append(c)

    return NumeralRepair(token, "".join(out), tuple(dict.fromkeys(rules)))

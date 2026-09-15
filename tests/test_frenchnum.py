"""Tests for deterministic French number, amount and date parsing.

The cases marked "corpus" are strings that genuinely occur in the ARCHEAN
actes; the audit that established them is DISCOVERY.md §11.1. Cases marked
"grammar" exercise forms the parser implements but that this corpus does not
contain, and they are labelled so that coverage is never mistaken for evidence.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from archean.frenchnum import (
    DateParts,
    FrenchDateError,
    FrenchNumberError,
    FrenchParseError,
    looks_like_numeral,
    parse_french_amount,
    parse_french_date,
    parse_french_date_parts,
    parse_french_integer,
    parse_french_month,
    parse_french_year,
    repair_numeral,
    try_parse_french_integer,
)

# ===========================================================================
# Integers - forms attested in the corpus
# ===========================================================================

CORPUS_NUMBERS = [
    pytest.param("trente sept mille", 37_000, id="37000-constitution-capital"),
    pytest.param("trois cent soixante dix", 370, id="370-constitution-shares"),
    pytest.param("cent", 100, id="100-nominal"),
    pytest.param("cent cinquante mille", 150_000, id="150000-2006-capital"),
    pytest.param("mille cinq cent", 1_500, id="1500-2006-shares"),
    pytest.param("deux cent mille", 200_000, id="200000-2007-capital"),
    pytest.param("deux mille", 2_000, id="2000-2007-shares"),
    pytest.param("cinq cents", 500, id="500-registration-stamp"),
    pytest.param("deux cent quatre-vingt-quinze", 295, id="295-stamp"),
]


@pytest.mark.parametrize("text,expected", CORPUS_NUMBERS)
def test_corpus_spelled_numbers(text, expected):
    assert parse_french_integer(text) == expected


def test_corpus_numbers_match_the_golden_chain():
    """The spelled forms must agree with the capital chain they describe.

    Not a tautology: these strings were read out of the documents and the
    golden chain was built from the same documents independently.
    """
    golden = json.loads(
        (Path(__file__).parent / "golden_capital_chain.json").read_text(
            encoding="utf-8"
        )
    )
    by_seq = {r["seq"]: r for r in golden["chain"]}
    assert parse_french_integer("trente sept mille") == by_seq[1]["capital_eur_after"]
    assert parse_french_integer("trois cent soixante dix") == by_seq[1]["shares_total_after"]
    assert parse_french_integer("cent") == by_seq[1]["nominal_eur"]
    assert parse_french_integer("cent cinquante mille") == by_seq[2]["capital_eur_after"]
    assert parse_french_integer("mille cinq cent") == by_seq[2]["shares_total_after"]
    assert parse_french_integer("deux cent mille") == by_seq[4]["capital_eur_after"]
    assert parse_french_integer("deux mille") == by_seq[4]["shares_total_after"]


# ===========================================================================
# Integers - systematic grammar coverage
# ===========================================================================

@pytest.mark.parametrize("text,expected", [
    ("zero", 0), ("un", 1), ("une", 1), ("deux", 2), ("trois", 3),
    ("quatre", 4), ("cinq", 5), ("six", 6), ("sept", 7), ("huit", 8),
    ("neuf", 9), ("dix", 10), ("onze", 11), ("douze", 12), ("treize", 13),
    ("quatorze", 14), ("quinze", 15), ("seize", 16),
])
def test_units_and_teens(text, expected):
    assert parse_french_integer(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("dix-sept", 17), ("dix-huit", 18), ("dix-neuf", 19),
    ("vingt", 20), ("vingt et un", 21), ("vingt-et-un", 21),
    ("vingt-deux", 22), ("trente", 30), ("trente-sept", 37),
    ("quarante", 40), ("cinquante", 50), ("soixante", 60),
])
def test_tens_and_compounds(text, expected):
    assert parse_french_integer(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("soixante-dix", 70), ("soixante dix", 70),
    ("soixante et onze", 71), ("soixante-et-onze", 71),
    ("soixante-douze", 72), ("soixante-quinze", 75), ("soixante-seize", 76),
])
def test_seventies_are_built_from_sixty(text, expected):
    """70-79 is 'soixante' plus a teen, not a distinct word."""
    assert parse_french_integer(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("quatre-vingt", 80), ("quatre-vingts", 80), ("quatre vingt", 80),
    ("quatre vingts", 80), ("quatre-vingt-un", 81), ("quatre-vingt-dix", 90),
    ("quatre-vingt-quinze", 95), ("quatre-vingt-dix-neuf", 99),
])
def test_eighties_and_nineties(text, expected):
    """'quatre' + 'vingt' is 80, not 4 + 20."""
    assert parse_french_integer(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("cent", 100), ("cent un", 101), ("deux cents", 200), ("deux cent", 200),
    ("deux cent cinquante", 250), ("neuf cent quatre-vingt-dix-neuf", 999),
    ("trois cent soixante dix", 370),
])
def test_hundreds_including_the_plural(text, expected):
    """'cent' takes an 's' when it ends the number; both spellings occur."""
    assert parse_french_integer(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("mille", 1_000), ("mille un", 1_001), ("deux mille", 2_000),
    ("dix mille", 10_000), ("trente sept mille", 37_000),
    ("cent cinquante mille", 150_000), ("deux cent mille", 200_000),
    ("neuf cent quatre-vingt-dix-neuf mille", 999_000),
    ("mille cinq cent", 1_500),
    ("quatre cent vingt six mille six cent cinquante", 426_650),
])
def test_thousands(text, expected):
    assert parse_french_integer(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("un million", 1_000_000),
    ("deux millions", 2_000_000),
    ("un million deux cent mille", 1_200_000),
    ("un milliard", 1_000_000_000),
])
def test_millions_grammar_only_not_present_in_this_corpus(text, expected):
    """Implemented for completeness; zero occurrences in the ARCHEAN actes."""
    assert parse_french_integer(text) == expected


# -- separators, case, accents ----------------------------------------------

@pytest.mark.parametrize("text", [
    "trois cent soixante dix",
    "trois-cent-soixante-dix",
    "TROIS CENT SOIXANTE DIX",
    "  trois   cent  soixante   dix  ",
    "trois cent soixante-dix",
])
def test_hyphens_spaces_and_case_are_interchangeable(text):
    """The corpus mixes all of these, sometimes on the same page."""
    assert parse_french_integer(text) == 370


def test_accents_are_folded():
    assert parse_french_integer("zéro") == 0


def test_et_is_ignored_as_a_joiner():
    assert parse_french_integer("vingt et un") == 21
    assert parse_french_integer("soixante et onze") == 71


# -- refusing rather than guessing ------------------------------------------

@pytest.mark.parametrize("text", [
    "", "   ", "et", "et et",
])
def test_empty_and_contentless_input_is_refused(text):
    with pytest.raises(FrenchNumberError):
        parse_french_integer(text)


@pytest.mark.parametrize("text", [
    "trois cent banane",
    "capital social",
    "mille euros",
    "trente sept mille EUROS euros",
])
def test_unknown_words_fail_the_whole_string(text):
    """Never parse partially: a dropped word silently changes the value."""
    with pytest.raises(FrenchNumberError, match="not French number words"):
        parse_french_integer(text)


@pytest.mark.parametrize("text", [
    "deux trois", "cinq sept", "un deux",
])
def test_two_bare_units_in_a_row_are_refused(text):
    with pytest.raises(FrenchNumberError, match="two unit words"):
        parse_french_integer(text)


def test_scale_words_must_descend():
    with pytest.raises(FrenchNumberError, match="out of order"):
        parse_french_integer("mille million")
    with pytest.raises(FrenchNumberError, match="out of order"):
        parse_french_integer("mille mille")


def test_mil_the_archaic_year_form_is_deliberately_unsupported():
    """'mil neuf cent' is valid French but absent here; see the docstring.

    Accepting it would make a misread 'mille' parse as a different number.
    """
    with pytest.raises(FrenchNumberError):
        parse_french_integer("mil neuf cent")


def test_try_parse_returns_none_instead_of_raising():
    assert try_parse_french_integer("trois cent") == 300
    assert try_parse_french_integer("banane") is None


# ===========================================================================
# Amounts written in digits
# ===========================================================================

@pytest.mark.parametrize("text,expected", [
    pytest.param("37.000", "37000", id="corpus-37000"),
    pytest.param("150.000", "150000", id="corpus-150000"),
    pytest.param("368.102", "368102", id="corpus-368102"),
    pytest.param("217 241", "217241", id="corpus-217241"),
    pytest.param("400 000", "400000", id="corpus-400000"),
    pytest.param("150 861", "150861", id="corpus-150861"),
    pytest.param("182 759", "182759", id="corpus-182759"),
    pytest.param("64 655", "64655", id="corpus-64655"),
    pytest.param("150 000,00", "150000.00", id="corpus-with-decimals"),
    pytest.param("259 480,92", "259480.92", id="corpus-premium"),
    pytest.param("426.650", "426650", id="corpus-hadean-valuation"),
    pytest.param("5,80", "5.80", id="corpus-issue-price"),
    pytest.param("2,72", "2.72", id="corpus-buyback-price"),
    pytest.param("100", "100", id="corpus-nominal"),
])
def test_amounts_in_digits(text, expected):
    assert parse_french_amount(text) == Decimal(expected)


def test_dot_is_a_thousands_separator_not_a_decimal_point():
    """The single most damaging misreading available in this corpus.

    Reading '368.102' as 368.102 euros instead of 368 102 euros is a
    three-orders-of-magnitude error in the share capital.
    """
    assert parse_french_amount("368.102") == Decimal("368102")
    assert parse_french_amount("368.102") != Decimal("368.102")


def test_amount_returns_decimal_not_float():
    value = parse_french_amount("259 480,92")
    assert isinstance(value, Decimal)
    assert value == Decimal("259480.92")


@pytest.mark.parametrize("text", [
    "1.23",        # not a thousands group: 23 is two digits, not three
    "12.34567",
    "abc",
    "",
    "1,2,3",
    "37..000",
])
def test_ambiguous_or_malformed_amounts_are_refused(text):
    with pytest.raises(FrenchNumberError):
        parse_french_amount(text)


# ===========================================================================
# Months
# ===========================================================================

@pytest.mark.parametrize("name,number", [
    ("janvier", 1), ("février", 2), ("mars", 3), ("avril", 4), ("mai", 5),
    ("juin", 6), ("juillet", 7), ("août", 8), ("septembre", 9),
    ("octobre", 10), ("novembre", 11), ("décembre", 12),
])
def test_every_month(name, number):
    assert parse_french_month(name) == number


@pytest.mark.parametrize("name,number", [
    ("FEVRIER", 2), ("JANVIER", 1), ("MAI", 5), ("MARS", 3), ("JUIN", 6),
    ("NOVEMBRE", 11), ("OCTOBRE", 10), ("SEPTEMBRE", 9),
])
def test_uppercase_unaccented_months_as_ocr_emits_them(name, number):
    """These exact spellings appear in the corpus headers."""
    assert parse_french_month(name) == number


def test_unaccented_lowercase_months():
    assert parse_french_month("fevrier") == 2
    assert parse_french_month("aout") == 8
    assert parse_french_month("decembre") == 12


@pytest.mark.parametrize("bad", ["mais", "nombre", "main", "", "mardi", "may"])
def test_non_months_are_refused(bad):
    """'mais' and 'nombre' are real French words one edit from a month name."""
    with pytest.raises(FrenchDateError):
        parse_french_month(bad)


# ===========================================================================
# Years
# ===========================================================================

@pytest.mark.parametrize("text,expected", [
    ("2005", 2005), ("2008", 2008), ("2017", 2017), ("2024", 2024),
    pytest.param("deux mille dix-sept", 2017, id="corpus-2017-hyphenated"),
    pytest.param("deux mille dix huit", 2018, id="corpus-2018-spaced"),
    pytest.param("deux mille treize", 2013, id="corpus-2013"),
    pytest.param("deux mille dix", 2010, id="corpus-2010"),
    pytest.param("L'an deux mille dix-sept,", 2017, id="corpus-with-lan-prefix"),
])
def test_years(text, expected):
    assert parse_french_year(text) == expected


@pytest.mark.parametrize("bad", ["05", "5", "123", "banane", ""])
def test_two_digit_years_are_refused_as_ambiguous(bad):
    """'05' could be 1905 or 2005 and nothing in the string decides."""
    with pytest.raises(FrenchDateError):
        parse_french_year(bad)


def test_implausible_years_are_refused():
    with pytest.raises(FrenchDateError, match="plausible year"):
        parse_french_year("trois cent")


# ===========================================================================
# Dates - the shapes that occur in the corpus
# ===========================================================================

# Shape A: numeric day + month word + numeric year.
CORPUS_DATES_SHAPE_A = [
    ("Le 17 mai 2005,", "2005-05-17"),
    ("Le 8 août 2005,", "2005-08-08"),
    ("Le 2 septembre 2005,", "2005-09-02"),
    ("Le 20 octobre 2006,", "2006-10-20"),
    ("EN DATE DU 27 JUIN 2008", "2008-06-27"),
    ("le 19 janvier 2017", "2017-01-19"),
    ("EN DATE DU 21 FEVRIER 2017", "2017-02-21"),
    ("EN DATE DU 23 MARS 2018", "2018-03-23"),
    ("DU 24 juin 2024", "2024-06-24"),
    ("le 16 août 2005", "2005-08-16"),
    ("le 16 novembre 2006", "2006-11-16"),
    ("le 14 mai 2008", "2008-05-14"),
    ("le 31 décembre 2023", "2023-12-31"),
]


@pytest.mark.parametrize("text,iso", CORPUS_DATES_SHAPE_A)
def test_shape_a_numeric_day_month_word_year(text, iso):
    assert parse_french_date(text).isoformat() == iso


# Shape B: dd/mm/yyyy.
CORPUS_DATES_SHAPE_B = [
    ("27/06/2008", "2008-06-27"),
    ("22/12/2004", "2004-12-22"),
    ("20/10/2006", "2006-10-20"),
    ("31/03/2005", "2005-03-31"),
    ("17/05/2005", "2005-05-17"),
    ("13/09/1965", "1965-09-13"),
    ("12/02/2013", "2013-02-12"),
    ("20/01/2017", "2017-01-20"),
    ("30/05/2018", "2018-05-30"),
]


@pytest.mark.parametrize("text,iso", CORPUS_DATES_SHAPE_B)
def test_shape_b_numeric_ddmmyyyy(text, iso):
    assert parse_french_date(text).isoformat() == iso


def test_shape_b_flags_day_month_ambiguity_instead_of_hiding_it():
    """'05/01/2005' is day-first by French convention, but formally ambiguous.

    We parse day-first and say so, rather than silently choosing.
    """
    unambiguous = parse_french_date_parts("27/06/2008")
    assert unambiguous.day == 27 and not unambiguous.day_month_ambiguous

    ambiguous = parse_french_date_parts("05/01/2005")
    assert ambiguous.day == 5 and ambiguous.month == 1
    assert ambiguous.day_month_ambiguous is True


def test_shape_b_rejects_impossible_day_month_pairs():
    with pytest.raises(FrenchDateError):
        parse_french_date_parts("27/13/2008")
    with pytest.raises(ValueError):
        parse_french_date_parts("31/02/2008")


# Shape C: fully spelled.
def test_shape_c_fully_spelled_on_one_line():
    """The one complete spelled date in the corpus."""
    parts = parse_french_date_parts("Le vingt neuf janvier deux mille treize,")
    assert parts.iso() == "2013-01-29"


@pytest.mark.parametrize("text,day,month", [
    pytest.param("Le vingt-et-un février,", 21, 2, id="corpus-2017-02-21"),
    pytest.param("Le vingt-trois mars", 23, 3, id="corpus-2018-03-23"),
    pytest.param("Le dix-neuf janvier", 19, 1, id="corpus-2017-01-19"),
    pytest.param("Le trente novembre, à 10 heures,", 30, 11, id="corpus-30-nov"),
])
def test_shape_c_split_across_lines_yields_a_partial_date(text, day, month):
    """The preamble puts the year on a previous line. Do not invent it."""
    parts = parse_french_date_parts(text)
    assert parts.day == day
    assert parts.month == month
    assert parts.year is None
    assert not parts.is_complete


@pytest.mark.parametrize("text,year", [
    ("L'an deux mille dix-sept,", 2017),
    ("L'an deux mille dix huit", 2018),
    ("L'an deux mille dix,", 2010),
])
def test_a_spelled_year_line_yields_only_a_year(text, year):
    parts = parse_french_date_parts(text)
    assert parts.year == year
    assert parts.day is None and parts.month is None


def test_a_partial_date_refuses_to_become_a_date():
    """The central non-invention property."""
    parts = parse_french_date_parts("Le vingt-et-un février,")
    with pytest.raises(FrenchDateError, match="refusing to invent"):
        parts.to_date()
    with pytest.raises(FrenchDateError):
        parse_french_date("Le vingt-et-un février,")


def test_caller_may_combine_parts_explicitly():
    """Recombining two lines is the caller's decision, made on layout evidence.

    This is how the 2017 president's decision reads in the document:
        "L'an deux mille dix-sept,"  /  "Le vingt-et-un février,"
    """
    year = parse_french_date_parts("L'an deux mille dix-sept,").year
    dm = parse_french_date_parts("Le vingt-et-un février,")
    combined = DateParts(day=dm.day, month=dm.month, year=year)
    assert combined.iso() == "2017-02-21"


@pytest.mark.parametrize("bad", [
    "", "   ", "aucune date ici", "le président", "capital social",
])
def test_input_without_a_date_is_refused(bad):
    with pytest.raises(FrenchDateError):
        parse_french_date_parts(bad)


# ===========================================================================
# Date-gap fixtures, from DISCOVERY.md
#
# Each case is a real document: the decision date read from the body, and the
# deposit date from meta/. The gap is the reason event_date may never be taken
# from a filename.
# ===========================================================================

DATE_GAP_FIXTURES = [
    # (inpi_id, body text as OCR emits it, expected event date,
    #  deposit date, status)
    ("63e9593b8be6eb9f9d257ec5", "Le 15 décembre 2004", "2004-12-15",
     "2005-01-25", "VERIFIED"),
    ("63e9593b8be6eb9f9d257ec4", "Le 17 mai 2005,", "2005-05-17",
     "2006-01-03", "VERIFIED"),
    ("63e9593b8be6eb9f9d257ec2", "en date du 16 août 2005", "2005-08-16",
     "2006-01-04", "VERIFIED"),
    ("63e9593b8be6eb9f9d257ec7", "Le 20 octobre 2006,", "2006-10-20",
     "2007-02-20", "UNCERTAIN"),
    ("63e9593b8be6eb9f9d257ec3", "EN DATE DU 27 JUIN 2008", "2008-06-27",
     "2008-07-15", "VERIFIED"),
    ("63e9593a8be6eb9f9d257ebe", "EN DATE DU 21 FEVRIER 2017", "2017-02-21",
     "2017-03-28", "VERIFIED"),
    ("63e9593b8be6eb9f9d257ec0", "EN DATE DU 23 MARS 2018", "2018-03-23",
     "2018-05-30", "VERIFIED"),
    ("6936b4160bb493b0e4098925", "DU 24 juin 2024", "2024-06-24",
     "2025-12-02", "VERIFIED"),
]


@pytest.mark.parametrize(
    "inpi_id,text,expected_iso,deposit_iso,status", DATE_GAP_FIXTURES
)
def test_decision_dates_parse_from_the_document_body(
    inpi_id, text, expected_iso, deposit_iso, status
):
    assert parse_french_date(text).isoformat() == expected_iso


@pytest.mark.parametrize(
    "inpi_id,text,expected_iso,deposit_iso,status", DATE_GAP_FIXTURES
)
def test_every_decision_date_precedes_its_deposit(
    inpi_id, text, expected_iso, deposit_iso, status
):
    """A decision cannot be filed before it is taken."""
    assert dt.date.fromisoformat(expected_iso) < dt.date.fromisoformat(deposit_iso)


@pytest.mark.parametrize(
    "inpi_id,text,expected_iso,deposit_iso,status", DATE_GAP_FIXTURES
)
def test_date_gap_fixtures_match_the_real_metadata(
    actes_root, inpi_id, text, expected_iso, deposit_iso, status
):
    """The deposit dates in these fixtures are not transcribed by hand."""
    meta = json.loads(
        (actes_root / "meta").joinpath(
            next(
                p.name for p in (actes_root / "meta").glob("*.json")
                if inpi_id in p.name
            )
        ).read_text(encoding="utf-8")
    )
    assert meta["dateDepot"] == deposit_iso
    assert meta["id"] == inpi_id


def test_date_gap_fixture_statuses_match_the_golden_chain():
    """The one UNCERTAIN row here must be the one UNCERTAIN row there."""
    golden = json.loads(
        (Path(__file__).parent / "golden_capital_chain.json").read_text(
            encoding="utf-8"
        )
    )
    golden_status = {
        r["source"]["inpi_id"]: r["status"] for r in golden["chain"]
    }
    for inpi_id, _text, _iso, _dep, status in DATE_GAP_FIXTURES:
        if inpi_id in golden_status:
            assert golden_status[inpi_id] == status, (
                f"{inpi_id}: fixture says {status}, golden chain says "
                f"{golden_status[inpi_id]}"
            )


def test_the_gaps_are_large_enough_to_matter():
    """18 days to 17 months, which is why a filename date is never the event.

    DISCOVERY.md §5.4 described the smallest gap as "3 weeks"; measured against
    meta/ it is 18 days (2008-06-27 decided, 2008-07-15 deposited). The point
    stands and the figure is now exact.
    """
    gaps = [
        (dt.date.fromisoformat(dep) - dt.date.fromisoformat(exp)).days
        for _id, _t, exp, dep, _s in DATE_GAP_FIXTURES
    ]
    assert min(gaps) == 18
    assert max(gaps) == 526  # 2024-06-24 decided, 2025-12-02 deposited
    assert all(g > 0 for g in gaps)


# ===========================================================================
# OCR repair - the separate layer
# ===========================================================================

CORPUS_CORRUPTIONS = [
    pytest.param("37.0o0", "37.000", id="o-for-0-constitution-capital"),
    pytest.param("200s", "2005", id="s-for-5-in-17-mai-200s"),
    pytest.param("5o0", "500", id="o-for-0-stamp"),
    pytest.param("2o08", "2008", id="o-for-0-year-in-stamp"),
    pytest.param("26S6", "2656", id="S-for-5-greffe-number"),
    pytest.param("820o0", "82000", id="o-for-0-postcode"),
    pytest.param("400/o0o", "400.000", id="slash-and-o-2018-header"),
]


@pytest.mark.parametrize("corrupt,expected", CORPUS_CORRUPTIONS)
def test_documented_corruptions_are_repaired(corrupt, expected):
    result = repair_numeral(corrupt)
    assert result.repaired == expected
    assert result.changed
    assert result.rules, "a repair must say which rule fired"


@pytest.mark.parametrize("corrupt,expected", CORPUS_CORRUPTIONS)
def test_repairs_preserve_the_original_text(corrupt, expected):
    """The original is always kept, so a note can quote what the document said."""
    assert repair_numeral(corrupt).original == corrupt


def test_repaired_amounts_then_parse():
    """End to end: corrupted token -> repair -> amount."""
    assert parse_french_amount(repair_numeral("37.0o0").repaired) == Decimal("37000")
    assert parse_french_amount(repair_numeral("400/o0o").repaired) == Decimal("400000")
    assert parse_french_year(repair_numeral("200s").repaired) == 2005


def test_cing_is_repaired_to_cinq():
    """'cing cents euros' and 'délai maximum de cing'. 'cing' is not French."""
    result = repair_numeral("cing")
    assert result.repaired == "cinq"
    assert result.changed
    assert parse_french_integer(f"{result.repaired} cents") == 500


# -- the guard: what must never be touched ----------------------------------

@pytest.mark.parametrize("token", [
    "soixante", "cinquante", "cent", "mille", "nombre", "mais", "main",
    "novembre", "octobre", "euros", "actions", "societe", "obligations",
    "d'eux", "sociales", "onze",
])
def test_french_words_are_never_treated_as_numerals(token):
    """'o' -> '0' applied to 'soixante' would destroy it."""
    assert not looks_like_numeral(token)
    assert repair_numeral(token).repaired == token
    assert not repair_numeral(token).changed


@pytest.mark.parametrize("token", [
    "27/06/2008", "22/12/2004", "2/3", "2005/8", "150.000", "217 241",
    "368.102", "100", "1", "5,80",
])
def test_clean_numerals_and_dates_are_left_alone(token):
    """A date must never be rewritten: '/' is only a corruption beside a letter."""
    assert not looks_like_numeral(token)
    assert repair_numeral(token).repaired == token


def test_slash_is_only_rewritten_when_a_letter_is_also_corrupt():
    assert repair_numeral("27/06/2008").repaired == "27/06/2008"
    assert repair_numeral("400/o0o").repaired == "400.000"


def test_the_guard_never_fires_on_any_word_in_the_corpus(actes_root):
    """Run the guard over every alphabetic token in all 17 actes.

    This is the test that makes the repair layer safe to enable: if it never
    fires on a real French word across ~11k lines, it cannot corrupt one.
    """
    import glob

    fired = []
    for ocr_dir in sorted((actes_root / "ocr").iterdir()):
        if not ocr_dir.is_dir():
            continue
        for page_file in sorted(ocr_dir.glob("page_*.json")):
            data = json.loads(page_file.read_text(encoding="utf-8"))
            for line in data.get("ocr") or []:
                for token in re.split(r"\s+", (line.get("text") or "")):
                    token = token.strip(".,;:()«»\"'")
                    if not token:
                        continue
                    # a token with no digits at all is a word
                    if any(c.isdigit() for c in token):
                        continue
                    if looks_like_numeral(token):
                        fired.append((ocr_dir.name, token))
    assert not fired, f"guard fired on non-numeric tokens: {fired[:20]}"


def test_repair_is_never_applied_by_the_parsers_themselves():
    """The parser must fail on corruption, not silently fix it.

    Repair is opt-in so that a repaired figure is always traceable to a rule.
    """
    with pytest.raises(FrenchNumberError):
        parse_french_amount("37.0o0")
    with pytest.raises(FrenchDateError):
        parse_french_year("200s")
    with pytest.raises(FrenchNumberError):
        parse_french_integer("cing cents")


def test_undocumented_lookalikes_are_not_guessed():
    """'l'->'1' and 'B'->'8' have no corpus evidence, so they are not rules."""
    assert repair_numeral("l50").repaired == "l50"
    assert repair_numeral("B00").repaired == "B00"


def test_repair_reports_each_rule_once():
    result = repair_numeral("2oo8")
    assert result.repaired == "2008"
    assert len(result.rules) == 1


# ===========================================================================
# Purity
# ===========================================================================

def test_parsing_is_deterministic_and_stateless():
    for _ in range(3):
        assert parse_french_integer("trois cent soixante dix") == 370
        assert parse_french_date("Le 17 mai 2005").isoformat() == "2005-05-17"
        assert repair_numeral("37.0o0").repaired == "37.000"


def test_module_imports_nothing_that_talks_to_a_network():
    import archean.frenchnum as fn

    source = Path(fn.__file__).read_text(encoding="utf-8")
    for forbidden in ("requests", "urllib", "httpx", "socket", "anthropic",
                      "openai", "os.environ"):
        assert forbidden not in source, f"{forbidden} must not appear here"


def test_errors_are_specific_enough_to_act_on():
    with pytest.raises(FrenchParseError) as exc:
        parse_french_integer("trois cent banane")
    assert "banane" in str(exc.value)

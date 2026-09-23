"""Property-based tests for the four parsing layers Ask still owns.

Example-based tests pin the cases somebody thought of. These pin the rules:
an identifier never contributes a figure, a citation marker means a citation
only when it stands alone, splitting a section never invents or loses text,
and no response shape — however mangled — escapes the schema gate as an
exception.

Kept deliberately small in ``max_examples``: quantity parsing is milliseconds
per call, and a property that needs ten thousand cases to find a bug is a
property that is testing the strategy rather than the code.
"""

import sys
import unittest
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.ai_provider import repair_truncated_json
from core.ask import ledger as ledger_module
from core.ask import quantities as quantities_module
from core.ask import recovery as recovery_module
from core.ask import schema as schema_module


PROFILE = settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ------------------------------------------------- quantities vs identifiers

#: The identifier shapes the corpus actually contains: certification numbers,
#: part codes, FCC-style ids, and version strings.
UPPER = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
ALPHA = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")

upper_text = st.lists(
    st.sampled_from(UPPER),
    min_size=1,
    max_size=4,
).map("".join)

alpha_text = st.lists(
    st.sampled_from(ALPHA),
    min_size=2,
    max_size=6,
).map("".join)

identifiers = st.one_of(
    st.tuples(
        upper_text,
        st.integers(min_value=0, max_value=999999),
    ).map(lambda pair: f"{pair[0]}-{pair[1]}"),

    st.tuples(
        alpha_text,
        st.integers(min_value=0, max_value=9999),
    ).map(lambda pair: f"{pair[0]}{pair[1]}"),

    st.tuples(
        st.integers(min_value=0, max_value=30),
        st.integers(min_value=0, max_value=30),
        st.integers(min_value=0, max_value=30),
    ).map(lambda parts: "{}.{}.{}".format(*parts)),
)

#: Whole numbers large enough that quantulum3 reads them as counts rather than
#: as part of an ordinary phrase.
counts = st.integers(min_value=2, max_value=99999)

units = st.sampled_from(["units", "prototypes", "subsystems", "days", "samples", "cartons"])


class QuantityIdentifierProperties(unittest.TestCase):
    @PROFILE
    @given(identifiers)
    def test_an_identifier_is_never_a_quantity(self, identifier):
        sentence = f"The certification record {identifier} was updated by the body."
        self.assertEqual(quantities_module.quantities(sentence), [])

    @PROFILE
    @given(identifiers)
    def test_an_identifier_is_recognized_as_one_on_its_own(self, identifier):
        self.assertTrue(quantities_module.is_identifier(identifier))

    @PROFILE
    @given(counts, units)
    def test_a_genuine_count_is_always_extracted(self, count, unit):
        found = quantities_module.quantities(f"The plan covers {count} {unit}.")
        self.assertIn(f"{float(count):g}", found)

    @PROFILE
    @given(identifiers, counts, units)
    def test_an_identifier_beside_a_quantity_costs_the_quantity_nothing(
        self, identifier, count, unit
    ):
        sentence = f"Record {identifier} covers {count} {unit}."
        found = quantities_module.quantities(sentence)
        self.assertIn(f"{float(count):g}", found)

    @PROFILE
    @given(st.text(max_size=200))
    def test_masking_preserves_every_offset(self, text):
        self.assertEqual(len(quantities_module.mask_identifiers(text)), len(text))

    @PROFILE
    @given(st.text(max_size=200))
    def test_quantity_extraction_never_raises(self, text):
        for offset, value in quantities_module.quantity_positions(text):
            self.assertGreaterEqual(offset, 0)
            self.assertTrue(value)


# ----------------------------------------------------------- citation markers

citation_ids = st.integers(min_value=1, max_value=999)
words = st.text("abcdefghijklmnopqrstuvwxyz", min_size=3, max_size=10)


class CitationMarkerProperties(unittest.TestCase):
    @PROFILE
    @given(citation_ids, words)
    def test_a_standalone_marker_is_read_as_a_citation(self, citation, word):
        sentence = f"The {word} was confirmed by the body [{citation}]."
        self.assertEqual(
            recovery_module._citation_ids(sentence, {citation}),
            [citation],
        )

    @PROFILE
    @given(citation_ids, words)
    def test_a_marker_glued_to_a_word_is_not_a_citation(self, citation, word):
        # "[1]00Start Certification.pdf" is a numbered attachment list in
        # retrieved mail, not a citation the model wrote.
        sentence = f"The attachment list begins [{citation}]{word}"
        self.assertEqual(recovery_module._citation_ids(sentence, {citation}), [])

    @PROFILE
    @given(citation_ids, citation_ids)
    def test_a_marker_outside_the_bundle_is_never_recovered(self, citation, other):
        valid = {other} - {citation}
        sentence = f"Reported by the certification body [{citation}]."
        self.assertNotIn(citation, recovery_module._citation_ids(sentence, valid))

    @PROFILE
    @given(st.text(max_size=200), st.sets(citation_ids, max_size=5))
    def test_recovery_never_invents_a_citation(self, text, valid):
        for claim in recovery_module.recover_claims(text, valid):
            self.assertTrue(set(claim["citations"]).issubset(valid))

    @PROFILE
    @given(st.text(max_size=200), st.sets(citation_ids, max_size=5))
    def test_the_ledgers_marker_fallback_stays_inside_the_bundle(self, text, valid):
        found = ledger_module._citations(
            ledger_module._STANDALONE_CITATION.findall(text), set(valid)
        )
        self.assertTrue(set(found).issubset(valid))


# ---------------------------------------------------------- sentence splitting

sentence_bodies = st.lists(
    st.text("abcdefghijklmnopqrstuvwxyz ", min_size=5, max_size=40),
    min_size=1,
    max_size=4,
)


class SentenceSplittingProperties(unittest.TestCase):
    @PROFILE
    @given(st.text(max_size=300))
    def test_splitting_neither_loses_nor_invents_text(self, text):
        joined = "".join(recovery_module._split_sentences(text))
        # The parts are contiguous from the start, so the only thing splitting
        # may drop is a trailing run of whitespace.
        self.assertTrue(text.startswith(joined))
        self.assertEqual(text[len(joined) :].strip(), "")

    @PROFILE
    @given(sentence_bodies)
    def test_every_sentence_is_a_substring_of_the_original(self, bodies):
        text = ". ".join(body.strip() or "x" for body in bodies) + "."
        for part in recovery_module._split_sentences(text):
            self.assertIn(part.strip(), text)

    @PROFILE
    @given(st.sampled_from(sorted(recovery_module._ABBREVIATIONS)), words)
    def test_an_abbreviation_never_ends_a_sentence(self, abbreviation, word):
        text = f"Steven will intervene ({abbreviation}. {word} outreach) to accelerate it."
        self.assertEqual(len(recovery_module._split_sentences(text)), 1)

    @PROFILE
    @given(st.text(max_size=300), st.sets(citation_ids, min_size=1, max_size=4))
    def test_a_recovered_claim_is_always_text_that_was_written(self, text, valid):
        for claim in recovery_module.recover_claims(text, valid):
            # Whitespace is normalized; no word is added.
            for token in claim["text"].split():
                self.assertIn(token, text)


# ------------------------------------------------- malformed structured output

json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-1000, max_value=1000)
    | st.floats(allow_nan=False, allow_infinity=False, width=32)
    | st.text(max_size=20),
    lambda children: st.lists(children, max_size=3)
    | st.dictionaries(st.text(max_size=8), children, max_size=3),
    max_leaves=8,
)


class StructuredOutputProperties(unittest.TestCase):
    @PROFILE
    @given(json_values)
    def test_any_response_shape_is_reported_rather_than_raised(self, payload):
        normalized, status = schema_module.parse_answer(payload)
        self.assertIn(status, {schema_module.STRUCTURED_OK, schema_module.STRUCTURED_INVALID})
        if status == schema_module.STRUCTURED_OK:
            self.assertIsInstance(normalized, dict)
            self.assertEqual(
                set(normalized),
                {"answer", "claims", "conflicts", "uncertainty", "insufficient_evidence"},
            )
        else:
            self.assertIsNone(normalized)

    @PROFILE
    @given(st.text(max_size=40), st.lists(json_values, max_size=3))
    def test_a_validated_response_always_has_integer_citations(self, answer, claims):
        normalized, status = schema_module.parse_answer({"answer": answer, "claims": claims})
        if status != schema_module.STRUCTURED_OK:
            return
        for claim in normalized["claims"]:
            for citation in claim["citations"]:
                self.assertIsInstance(citation, int)

    @PROFILE
    @given(
        st.sampled_from(["evidence", "advisory", "ideation"]),
        st.lists(st.text(max_size=12), max_size=3),
    )
    def test_the_generated_schema_is_self_contained(self, mode, _noise):
        schema = schema_module.answer_schema(mode)
        serialized = repr(schema)
        self.assertNotIn("$ref", serialized)
        self.assertNotIn("$defs", serialized)
        claim = schema["properties"]["claims"]["items"]
        self.assertEqual(
            tuple(claim["properties"]["type"]["enum"]), schema_module.claim_types(mode)
        )


#: Response objects shaped like the ones synthesis actually returns.
responses = st.fixed_dictionaries(
    {
        "answer": st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=60),
        "claims": st.lists(
            st.fixed_dictionaries(
                {
                    "id": st.text("abc123", min_size=1, max_size=4),
                    "type": st.sampled_from(["fact", "synthesis", "recommendation"]),
                    "text": st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=40),
                    "citations": st.lists(citation_ids, max_size=3),
                }
            ),
            max_size=3,
        ),
        "insufficient_evidence": st.booleans(),
    }
)


class TruncatedResponseProperties(unittest.TestCase):
    """A response cut off mid-write is salvaged, never invented."""

    @PROFILE
    @given(responses, st.integers(min_value=1, max_value=400))
    def test_repair_never_invents_a_key(self, response, cut):
        import json

        serialized = json.dumps(response)
        repaired = repair_truncated_json(serialized[:cut])
        if repaired is None:
            return
        self.assertTrue(set(repaired).issubset(set(response)))
        for key, value in repaired.items():
            if isinstance(value, str):
                self.assertEqual(value, response[key])
            if isinstance(value, bool):
                self.assertEqual(value, response[key])

    @PROFILE
    @given(responses, st.integers(min_value=1, max_value=400))
    def test_a_repaired_claim_is_a_claim_that_was_being_written(self, response, cut):
        import json

        serialized = json.dumps(response)
        repaired = repair_truncated_json(serialized[:cut])
        if repaired is None or not isinstance(repaired.get("claims"), list):
            return
        self.assertLessEqual(len(repaired["claims"]), len(response["claims"]))
        for index, claim in enumerate(repaired["claims"]):
            original = response["claims"][index]
            for key, value in claim.items():
                if isinstance(value, (str, bool)):
                    self.assertEqual(value, original[key])

    @PROFILE
    @given(st.text(max_size=200))
    def test_repair_of_arbitrary_text_never_raises(self, text):
        repaired = repair_truncated_json(text)
        self.assertTrue(repaired is None or isinstance(repaired, dict))

    @PROFILE
    @given(responses)
    def test_a_complete_response_is_left_to_the_ordinary_parser(self, response):
        import json

        self.assertIsNone(repair_truncated_json(json.dumps(response)))


if __name__ == "__main__":
    unittest.main()

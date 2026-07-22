from fsq_agent.config import settings
from fsq_agent.schema.semantic_layer import SemanticLayer

UNIT = {
    "description": "Trading data.",
    "keywords": ["asset", "price"],
    "tables": [
        {
            "name": "Assets",
            "description": "One row per tradable asset.",
            "columns": [
                {"name": "Id", "type": "integer", "description": "Primary key"},
                {"name": "Symbol", "type": "text", "description": "TODO"},
                {"name": "Rank", "type": "text"},
                {"name": "PasswordHash", "type": "text", "description": "secret"},
            ],
        }
    ],
    "joins": ['"A"."Id" = "B"."AId"'],
}


def render() -> str:
    return SemanticLayer(units={"market": UNIT}).retrieve("asset prices")


def test_placeholder_descriptions_are_omitted():
    """TODO markers belong in the YAML, never in the prompt."""
    assert "TODO" not in render()


def test_real_descriptions_are_kept():
    out = render()
    assert "Primary key" in out
    assert "One row per tradable asset." in out


def test_column_without_description_still_listed():
    """Dropping the description must not drop the column."""
    out = render()
    assert '"Rank" (text)' in out
    # ...and it should not leave a dangling colon behind.
    assert '"Rank" (text):' not in out


def test_sensitive_columns_never_rendered():
    assert "PasswordHash" not in render()
    assert "secret" not in render()


def test_identifiers_are_double_quoted_for_postgres():
    assert 'Table "Assets"' in render()
    assert '"Symbol" (text)' in render()


def test_keyword_match_selects_only_relevant_units():
    layer = SemanticLayer(units={"market": UNIT, "other": {"keywords": ["zzz"]}})
    assert "Business unit: other" not in layer.retrieve("show me asset prices")


def test_no_keyword_match_falls_back_to_all_units():
    """Deliberate: including everything beats silently guessing wrong."""
    layer = SemanticLayer(units={"market": UNIT, "other": {"keywords": ["zzz"]}})
    out = layer.retrieve("something entirely unrelated")
    assert "Business unit: market" in out
    assert "Business unit: other" in out


def test_denylist_is_lower_cased():
    assert "passwordhash" in settings.sensitive_column_set

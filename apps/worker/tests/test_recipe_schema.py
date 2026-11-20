"""Recipe JSON Schema (apps/web/src/lib/recipe.schema.json) on the worker side: the
shared case list, the documented examples, and every worker entry point."""
import json
from pathlib import Path

import pytest

from ats_worker import config, db, recipe_schema
from ats_worker.fetch import fetch_company
from ats_worker.pipeline import run_fetch

CASES = json.loads((Path(__file__).parent / "fixtures" / "recipe-cases.json").read_text())


@pytest.mark.parametrize("case", CASES["valid"], ids=lambda c: f"{c['source']}/{c['slug']}")
def test_watchlist_shaped_recipes_validate(case):
    assert recipe_schema.errors(case["source"], case["recipe"]) == []


@pytest.mark.parametrize("case", CASES["invalid"], ids=lambda c: f"{c['source']}-{c['error']}")
def test_invalid_recipe_is_rejected_naming_the_key(case):
    errs = recipe_schema.errors(case["source"], case["recipe"])
    assert errs, case
    assert any(case["error"] in e for e in errs), errs


def test_misspelled_key_message_names_it():
    with pytest.raises(ValueError, match="item_pth"):
        recipe_schema.check("custom", {"url": "https://a.example.com/j", "item_pth": "jobs",
                                       "fields": {"title": "t"}})


@pytest.mark.parametrize("source", ["custom", "browser"])
def test_schema_examples_validate(source):
    examples = recipe_schema.SCHEMA["$defs"][source]["examples"]
    assert examples
    for ex in examples:
        assert recipe_schema.errors(source, ex) == []


def test_non_recipe_source_is_not_checked():
    assert recipe_schema.errors("greenhouse", None) == []


def test_recipe_source_without_a_mapping_is_an_error():
    assert recipe_schema.errors("custom", None)


def test_fetch_company_refuses_invalid_recipe_before_any_request():
    calls = []

    class Sess:
        def get(self, *a, **k):
            calls.append(a)
            raise AssertionError("no request expected")

        post = get

    with pytest.raises(ValueError, match="item_pth"):
        fetch_company("custom", "acme", "Acme", session=Sess(),
                      recipe={"url": "https://a.example.com/j", "item_pth": "x",
                              "fields": {"title": "t"}})
    assert calls == []


def test_invalid_stored_recipe_skips_that_board_only(db_path, capsys):
    """An invalid stored recipe is a per-board error, never a crash of the pass."""
    seen = []

    def fetch_fn(source, slug, name, recipe=None, keep=None):
        seen.append(slug)
        if source in config.RECIPE_SOURCES:
            return fetch_company(source, slug, name, recipe=recipe, keep=keep)
        return []

    companies = [
        {"source": "custom", "slug": "bad", "name": "Bad",
         "recipe": {"url": "https://a.example.com/j", "item_pth": "x", "fields": {}}},
        {"source": "greenhouse", "slug": "good", "name": "Good", "recipe": None},
    ]
    run_fetch(db.connect(db_path), companies, None, now="2026-11-20T00:00:00Z",
              fetch_fn=fetch_fn)
    out = capsys.readouterr().out
    assert seen == ["bad", "good"]
    assert "custom/bad: skipped after error: invalid custom recipe" in out
    assert "item_pth" in out


def test_config_seed_rejects_invalid_recipe(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "companies:\n"
        "  - source: custom\n"
        "    slug: acme\n"
        "    name: Acme\n"
        "    recipe: {url: 'https://a.example.com/j', item_pth: jobs, fields: {title: t}}\n")
    with pytest.raises(config.ConfigError, match="item_pth"):
        config.load_config(str(cfg))

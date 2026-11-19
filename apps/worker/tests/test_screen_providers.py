"""The screen provider registry: invariants the rest of the worker relies on."""
import subprocess
import sys
from pathlib import Path

from ats_worker import run, usage
from ats_worker.screen_providers import PROVIDERS, RETIRED


def test_registry_imports_stdlib_only():
    # doctor lists the rows on a checkout with missing deps, so importing the registry
    # must not pull in any adapter dependency.
    code = ("import sys, ats_worker.screen_providers; "
            "bad = {'requests', 'pycountry', 'bs4', 'yaml'} & set(sys.modules); "
            "assert not bad, bad")
    subprocess.run([sys.executable, "-c", code], check=True, cwd=Path(__file__).parents[1])


def test_quota_rows_have_a_usage_fetcher():
    assert {n for n, p in PROVIDERS.items() if p.quota} == set(usage._FETCHERS)


def test_cli_choices_are_the_registry_and_retired_names_are_gone():
    assert run.SCREEN_BACKENDS == tuple(PROVIDERS)
    assert not set(RETIRED) & set(PROVIDERS)


def test_only_the_api_backend_is_metered_and_the_default_is_free():
    assert [n for n, p in PROVIDERS.items() if p.paid] == ["api"]
    assert not PROVIDERS[run.DEFAULT_SCREEN_BACKEND].paid

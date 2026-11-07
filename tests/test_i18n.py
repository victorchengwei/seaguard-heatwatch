import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from heatwatch.reminders import TEXT as REMINDER_TEXT
from heatwatch.rules import ACTIONS, HYDRATION, SCHEDULE

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def load():
    js = "const i=require(process.argv[1]);console.log(JSON.stringify({L:i.LANGS,K:i.KEYS,T:i.T}));"
    out = subprocess.run(["node", "-e", js, str(ROOT / "static" / "i18n.js")],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_twelve_languages_all_phrases_present():
    d = load()
    assert len(d["L"]) == 12 and set(d["L"]) == set(d["T"])
    for lang, row in d["T"].items():
        assert len(row) == len(d["K"]), lang
        assert all(isinstance(s, str) and s.strip() for s in row), lang


def test_numbers_identical_in_every_language():
    """Safety numbers (minutes, ml, litres) must never change in translation."""
    d = load()
    num = re.compile(r"\d+(?:\.\d+)?")
    for i, key in enumerate(d["K"]):
        en = sorted(num.findall(d["T"]["en"][i]))
        for lang, row in d["T"].items():
            assert sorted(num.findall(row[i])) == en, (lang, key)


def test_rtl_languages_marked():
    d = load()
    assert {k for k, v in d["L"].items() if v["dir"] == "rtl"} == {"ar", "ur"}
    assert all(v["status"] == "ai-draft" for k, v in d["L"].items() if k != "en")


def test_english_source_matches_rules_engine():
    """Every message the server and the watch send has a translation key."""
    en = set(load()["T"]["en"])
    for text in list(ACTIONS.values()) + list(HYDRATION.values()) + list(SCHEDULE.values()) + list(REMINDER_TEXT.values()):
        assert text in en, text

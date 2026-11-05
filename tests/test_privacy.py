import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from heatwatch.privacy import aggregate, crew_board


def test_small_cells_suppressed():
    out = aggregate(["GREEN"] * 9 + ["RED"] * 2)
    assert out["levels"]["RED"] == "<5" and out["levels"]["GREEN"] == 9


def test_small_group_fully_suppressed():
    assert aggregate(["RED", "GREEN"])["total"] == "<5"


def test_board_shows_colour_only():
    row = crew_board({"W1": "AMBER"})[0]
    assert set(row) == {"worker", "level"}

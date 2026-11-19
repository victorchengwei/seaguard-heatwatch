"""Live command centre (v0.17): weather feed, fail-safe, forecast and privacy."""
import pytest
from fastapi.testclient import TestClient

from heatwatch import live


def fake_open_meteo(temp=30.0, rh=50.0, rad=600.0, start="2026-07-15T07"):
    times = [f"2026-07-15T{h:02d}:00" for h in range(7, 20)]
    temps = [temp + i for i in range(len(times))]  # warming through the day
    return {"timezone_abbreviation": "GST",
            "current": {"time": start + ":15", "temperature_2m": temp, "relative_humidity_2m": rh,
                        "wind_speed_10m": 3.0, "shortwave_radiation": rad},
            "hourly": {"time": ["2026-07-15T06:00"] + times, "temperature_2m": [temp] + temps,
                       "relative_humidity_2m": [rh] * (len(times) + 1),
                       "wind_speed_10m": [3.0] * (len(times) + 1),
                       "shortwave_radiation": [rad] * (len(times) + 1)}}


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    live._CACHE.clear()
    yield
    live._CACHE.clear()


def test_live_weather_parsed_and_past_hours_dropped(monkeypatch):
    monkeypatch.setattr(live, "FETCH", lambda url: fake_open_meteo())
    w = live.site_weather(live.SITES[0], now=1000.0)
    assert w["source"] == "live" and not w["stale"]
    assert w["hourly"][0]["time"] == "2026-07-15T07:00"  # 06:00 dropped (before current hour)


def test_cache_avoids_refetch(monkeypatch):
    calls = []
    monkeypatch.setattr(live, "FETCH", lambda url: calls.append(url) or fake_open_meteo())
    live.site_weather(live.SITES[0], now=1000.0)
    live.site_weather(live.SITES[0], now=1000.0 + live.CACHE_TTL_S - 1)
    assert len(calls) == 1


def test_feed_failure_uses_last_reading_marked_stale(monkeypatch):
    monkeypatch.setattr(live, "FETCH", lambda url: fake_open_meteo())
    live.site_weather(live.SITES[0], now=1000.0)

    def boom(url):
        raise OSError("network down")
    monkeypatch.setattr(live, "FETCH", boom)
    w = live.site_weather(live.SITES[0], now=1000.0 + live.CACHE_TTL_S + 5)
    assert w["stale"] and "last reading" in w["source"]


def test_no_reading_at_all_uses_labelled_stale_fallback(monkeypatch):
    def boom(url):
        raise OSError("network down")
    monkeypatch.setattr(live, "FETCH", boom)
    w = live.site_weather(live.SITES[2], now=1000.0)
    assert w["source"] == "fallback" and w["stale"] and w["note"]


def test_feed_failure_never_lowers_a_level(monkeypatch):
    monkeypatch.setattr(live, "FETCH", lambda url: fake_open_meteo(temp=33))
    ok = live.snapshot("live", now=5000.0)
    live._CACHE.clear()
    live._CACHE.update({s["id"]: (live._parse(fake_open_meteo(temp=33)), 0.0) for s in live.SITES})

    def boom(url):
        raise OSError("network down")
    monkeypatch.setattr(live, "FETCH", boom)
    bad = live.snapshot("live", now=5000.0)
    for s_ok, s_bad in zip(ok["sites"], bad["sites"]):
        for c_ok, c_bad in zip(s_ok["crews"], s_bad["crews"]):
            assert c_bad["forecast"][0]["level"] >= c_ok["forecast"][0]["level"] - 0  # stale adds margin


def test_proactive_intervention_before_limit(monkeypatch):
    monkeypatch.setattr(live, "FETCH", lambda url: fake_open_meteo(temp=26, rh=45))
    snap = live.snapshot("live", now=5000.0)
    ivs = [c["intervention"] for s in snap["sites"] for c in s["crews"] if c["intervention"]]
    ahead = [i for i in ivs if i["when"] != "now"]
    assert ahead, "warming forecast should produce at least one proactive intervention"
    for i in ahead:
        assert i["breach_at"] > i["when"]  # act 30 min before the limit is crossed
        assert "before the limit is crossed" in i["text"]


def test_heatwave_what_if_is_stricter(monkeypatch):
    monkeypatch.setattr(live, "FETCH", lambda url: fake_open_meteo(temp=28))
    a = live.snapshot("live", now=5000.0)
    b = live.snapshot("heatwave", heat_delta=6, now=5000.0)
    lv = lambda s: [c["forecast"][0]["level"] for x in s["sites"] for c in x["crews"]]
    assert all(y >= x for x, y in zip(lv(a), lv(b))) and sum(lv(b)) > sum(lv(a))


def test_replay_builds_from_dawn_to_noon():
    dawn = live.snapshot("replay", replay_hour=6)
    noon = live.snapshot("replay", replay_hour=13)
    assert dawn["counts"][1] + dawn["counts"][2] > 0
    assert noon["counts"][4] > dawn["counts"][4]


def test_privacy_watches_send_level_and_reason_only():
    snap = live.snapshot("replay", replay_hour=9)
    for s in snap["sites"]:
        for c in s["crews"]:
            for w in c["watches"]:
                assert set(w) == {"watch", "level", "reasons"}
                assert all(r in live.WATCH_CODES for r in w["reasons"])
    text = str(snap).lower()
    for word in ("heart_rate\":", "core_est", "bpm", "age\":"):
        assert word not in text


def test_labels_say_not_a_diagnosis_and_simulated():
    snap = live.snapshot("replay", replay_hour=9)
    assert "not a medical diagnosis" in snap["labels"]["medical"]
    assert "SIMULATED" in snap["labels"]["workers"]


def test_api_and_page(monkeypatch):
    monkeypatch.setattr(live, "FETCH", lambda url: fake_open_meteo())
    from app import app
    c = TestClient(app)
    r = c.get("/api/live?mode=heatwave&heat=4")
    assert r.status_code == 200 and r.json()["heat_delta"] == 4
    assert c.get("/api/live?heat=99").status_code == 422
    page = c.get("/command")
    assert page.status_code == 200 and "Live Command Centre" in page.text


# ---------------------------------------------------------------- on-site sensors (15 s)

def _crew(snap, site_id, crew):
    s = next(x for x in snap["sites"] if x["id"] == site_id)
    return s, next(c for c in s["crews"] if c["crew"] == crew)


@pytest.fixture
def no_ext():
    live._EXT.clear()
    yield
    live._EXT.clear()


def test_wbgt_formulas_outdoor_and_indoor():
    tnwb, out = live.wbgt_from(35.0, 40.0, 50.0, indoor=False, solar=1.0)
    assert abs(out - (0.7 * tnwb + 0.2 * 50.0 + 0.1 * 35.0)) <= 0.1
    tnwb_i, ind = live.wbgt_from(35.0, 40.0, 38.0, indoor=True, solar=0.0)
    assert abs(ind - (0.7 * tnwb_i + 0.3 * 38.0)) <= 0.1


def test_sensor_reading_changes_every_15_seconds(monkeypatch, no_ext):
    monkeypatch.setattr(live, "FETCH", lambda url: fake_open_meteo(temp=33))
    a = live.snapshot("live", now=15 * 1000)
    b = live.snapshot("live", now=15 * 1001)
    ra = a["sites"][0]["sensors"][0]
    rb = b["sites"][0]["sensors"][0]
    assert ra["tick"] != rb["tick"] and ra != rb
    assert a["refresh_s"] == 15


def test_shaded_crew_without_station_uses_model_only(monkeypatch, no_ext):
    monkeypatch.setattr(live, "FETCH", lambda url: fake_open_meteo(temp=33))
    _, c = _crew(live.snapshot("live", now=15000.0), "khalifa", "Crew D")
    assert c["station"] is None and any("No sensor at this work spot" in r for r in c["reasons"])


def test_real_station_can_only_make_it_stricter(monkeypatch, no_ext):
    monkeypatch.setattr(live, "FETCH", lambda url: fake_open_meteo(temp=30, rh=40))
    now = 20000.0
    base = live.snapshot("live", now=now)
    _, before = _crew(base, "khalifa", "Crew A")
    # a cool (even faulty) real reading cannot lower the level below the weather model
    live.ingest_reading("KHALIFA-01", {"temp_c": 15, "rh_pct": 30, "wbgt_c": 10}, now=now)
    _, cool = _crew(live.snapshot("live", now=now), "khalifa", "Crew A")
    model_only = live.crew_status(live.SITES[0]["crews"][0]["crew"], 30 + live.SITE_OFFSET_C["khalifa"] * 0,
                                  40, solar=min(1.0, 600 / live.FULL_SUN_W_M2))["level"]
    assert cool["forecast"][0]["level"] >= model_only
    # a hot real reading raises it
    live.ingest_reading("KHALIFA-01", {"temp_c": 44, "rh_pct": 45, "globe_c": 58, "wbgt_c": 34.5}, now=now)
    _, hot = _crew(live.snapshot("live", now=now), "khalifa", "Crew A")
    assert hot["level"] == 4 and any("real station" in r for r in hot["reasons"])


def test_silent_real_station_marks_site_stale(monkeypatch, no_ext):
    monkeypatch.setattr(live, "FETCH", lambda url: fake_open_meteo(temp=30))
    live.ingest_reading("KHALIFA-01", {"temp_c": 30, "rh_pct": 40}, now=1000.0)
    snap = live.snapshot("live", now=1000.0 + live.SENSOR_TTL_S + 30)
    _, c = _crew(snap, "khalifa", "Crew A")
    assert any("silent for over 2 min" in r for r in c["reasons"])


def test_ingest_validates(no_ext):
    with pytest.raises(ValueError):
        live.ingest_reading("NOPE-01", {"temp_c": 30, "rh_pct": 40})
    with pytest.raises(ValueError):
        live.ingest_reading("KHALIFA-01", {"temp_c": 99, "rh_pct": 40})
    with pytest.raises(ValueError):
        live.ingest_reading("KHALIFA-01", {"temp_c": 30})
    r = live.ingest_reading("OFFSHORE-ER", {"temp_c": 45, "rh_pct": 30, "globe_c": 48})
    assert r["accepted"] and r["wbgt_c"] > 30


def test_sensor_endpoint_token(monkeypatch, no_ext):
    from app import app
    c = TestClient(app)
    monkeypatch.delenv("SENSOR_TOKEN", raising=False)
    assert c.post("/api/sensor/KHALIFA-01", json={"temp_c": 30, "rh_pct": 40}).status_code == 503
    monkeypatch.setenv("SENSOR_TOKEN", "s3cret")
    assert c.post("/api/sensor/KHALIFA-01", json={"temp_c": 30, "rh_pct": 40},
                  headers={"X-Sensor-Token": "wrong"}).status_code == 401
    assert c.post("/api/sensor/KHALIFA-01", json={"temp_c": 99, "rh_pct": 40},
                  headers={"X-Sensor-Token": "s3cret"}).status_code == 422
    ok = c.post("/api/sensor/khalifa-01", json={"temp_c": 38, "rh_pct": 45, "globe_c": 52},
                headers={"X-Sensor-Token": "s3cret"})
    assert ok.status_code == 200 and ok.json()["accepted"]


def test_layers_listed_with_honest_status():
    snap = live.snapshot("replay", replay_hour=9)
    names = [l["layer"] for l in snap["layers"]]
    assert "On-site WBGT station" in names and "Weather satellite" in names
    sat = next(l for l in snap["layers"] if l["layer"] == "Weather satellite")
    assert sat["status"].startswith("roadmap")

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app import app

c = TestClient(app)


def test_health():
    assert c.get("/health").json() == {"status": "ok"}


def test_assess_returns_level_and_reasons():
    r = c.post("/api/assess", json={"temp_c": 36, "rh_pct": 55, "workload": "heavy"}).json()
    assert r["level"] == 4 and r["reasons"]


def test_unwell_via_api():
    r = c.post("/api/assess", json={"temp_c": 20, "rh_pct": 40, "feels_unwell": True}).json()
    assert r["level"] == 4 and r["escalate"]


def test_worker_page_served():
    assert "HeatWatch" in c.get("/").text


def test_supervisor_demo_crew_level_only():
    r = c.get("/api/supervisor/demo?hour=6").json()
    assert len(r["crews"]) == 4 and "Synthetic" in r["data_note"]
    for crew in r["crews"]:
        assert set(crew) == {"crew", "location", "size", "level", "label", "action", "schedule", "effective_wbgt", "twl", "oshad_zone", "reasons"}


def test_planner_finds_cool_window():
    r = c.get("/api/supervisor/demo").json()
    assert r["plans"][0]["window"] is not None


def test_morning_safer_than_afternoon():
    m = c.get("/api/supervisor/demo?hour=6").json()["crews"][0]["level"]
    a = c.get("/api/supervisor/demo?hour=13").json()["crews"][0]["level"]
    assert m < a


def test_alerts_flow_no_plain_ok_and_escalation():
    sid = "test-session-1"
    c.post("/api/supervisor/alerts/reset", json={"session": sid, "hour": 0, "minute": 0})
    r = c.post("/api/supervisor/alerts/sync", json={"session": sid, "hour": 13, "minute": 0}).json()
    assert r["alerts"], "a hot hour should open alerts"
    first = r["alerts"][0]
    bad = c.post("/api/supervisor/alerts/decide", json={"session": sid, "alert_id": first["id"], "action": "ok", "minute": 1})
    assert bad.status_code == 400
    ok = c.post("/api/supervisor/alerts/decide", json={"session": sid, "alert_id": first["id"],
                                                     "action": first["allowed_actions"][0]["id"], "minute": 3}).json()
    assert ok["adherence"]["acted"] == 1
    later = c.post("/api/supervisor/alerts/sync", json={"session": sid, "hour": 13, "minute": 15}).json()
    assert later["adherence"]["escalated"] == len(later["alerts"]) - 1
    other = c.post("/api/supervisor/alerts/sync", json={"session": "test-session-2", "hour": 6, "minute": 0}).json()
    assert other["adherence"]["acted"] == 0  # sessions are separate


def test_assess_returns_oshad_zone_with_wind():
    r = c.post("/api/assess", json={"temp_c": 40, "rh_pct": 45, "sun": True, "wind_ms": 1.0,
                                    "workload": "light"}).json()
    assert r["oshad_zone"] in ("Unrestricted", "Acclimatisation", "Buffer", "Withdrawal")
    assert r["twl"] > 0 and r["oshad_rules"]


def test_worker_page_has_watch_face_and_brand_selector():
    html = c.get("/").text
    assert 'id="face"' in html and 'id="dev"' in html and 'id="lang"' in html
    assert "MAN DOWN" in c.get("/i18n.js").text


def test_control_centre_and_navigation():
    html = c.get("/control").text
    assert "Human in command" in html and "AI-generated concept image" in html and "decided by" in html
    assert c.get("/img/control_concept.jpg").status_code == 200
    assert c.get("/img/../app.py").status_code == 404 and c.get("/img/other.jpg").status_code == 404
    for page in ("/", "/supervisor", "/control"):
        assert 'href="/control"' in c.get(page).text


def test_site_map_assets_bundled_with_licence():
    assert c.get("/vendor/leaflet/leaflet.js").status_code == 200
    assert c.get("/vendor/leaflet/LICENSE").status_code == 404  # only whitelisted files are served
    assert "BSD 2-Clause" in (pathlib.Path(__file__).resolve().parents[1] / "static" / "vendor" / "leaflet" / "LICENSE").read_text()
    html = c.get("/control").text
    assert 'id="map"' in html and "OpenStreetMap" in html and "CARTO" in html and "synthetic" in html


def test_judge_guide_links_open():
    html = c.get("/judges").text
    assert "3-minute judge guide" in html and "synthetic" in html
    for url in ("/?t=32&rh=50&wind=2", "/?t=45&rh=40&wind=0.5&wl=light", "/?sc=man_down&play=1&lang=ar",
                "/supervisor?hour=13", "/control?hour=9&live=1"):
        assert url.replace("&", "&") in html and c.get(url).status_code == 200


def test_withdrawal_demo_conditions():
    r = c.post("/api/assess", json={"temp_c": 45, "rh_pct": 40, "sun": True, "wind_ms": 0.5, "workload": "light"}).json()
    assert r["level"] == 4 and r["oshad_zone"] == "Withdrawal" and "permit" in r["schedule"]

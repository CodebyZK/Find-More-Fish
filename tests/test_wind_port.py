from urllib.parse import parse_qs, urlparse

import pytest

from backend import great_lakes_wind as wind


def test_direction_and_speed():
    value = wind.vector(3, 4, 8)
    assert value["speedMetersPerSecond"] == 5
    assert value["gustMetersPerSecond"] == 8
    assert value["directionDegrees"] == pytest.approx(216.8699, abs=0.001)
    assert value["travelDegrees"] == pytest.approx(36.8699, abs=0.001)
    assert wind.vector(0, 0, 0)["directionDegrees"] is None
    assert wind.vector(0, -5, 7)["directionDegrees"] == 0


def test_filter_is_regional_with_correct_height():
    query = parse_qs(urlparse(wind.filter_url(0, 48, "UGRD", "10_m_above_ground")).query)
    assert query["file"] == ["gfs.t00z.pgrb2.0p25.f048"]
    assert query["lev_10_m_above_ground"] == ["on"]
    assert query["var_UGRD"] == ["on"]
    assert query["leftlon"] == ["-94"]
    assert query["rightlon"] == ["-75"]


def test_forecast_offsets_and_run_fallback(monkeypatch):
    calls = []
    def load(cycle, hour):
        calls.append((cycle, hour))
        if len(calls) == 1:
            raise RuntimeError("Run unavailable")
        return {"points": [], "metadata": {"validTime": "test"}}
    monkeypatch.setattr(wind, "_hour", load)
    assert wind.forecast(48, now=12 * 3600)["metadata"]["forecastHour"] == 48
    assert calls == [(6 * 3600, 54), (0, 60)]


def test_wind_routes_and_unavailable_response(fish, monkeypatch):
    from backend import great_lakes_animation as animation, great_lakes_service as service

    monkeypatch.setattr(wind, "forecast", lambda hour, now=None: {"points": [], "metadata": {"forecastHour": hour}})
    response = fish.client.get("/api/great-lakes/wind?forecastHour=12")
    assert response.status_code == 200 and response.json["metadata"]["forecastHour"] == 12
    def fail(hour, now=None):
        raise RuntimeError("upstream error")
    monkeypatch.setattr(wind, "forecast", fail)
    response = fish.client.get("/api/great-lakes/wind")
    assert response.status_code == 503 and response.headers["Cache-Control"] == "no-store"
    assert fish.client.get("/api/great-lakes/wind-value?latitude=bad&longitude=0").status_code == 400
    calls = []
    monkeypatch.setattr(service, "animation_offsets", lambda now=None: (0, 2, 5, 8))
    monkeypatch.setattr(animation, "frame_payload", lambda layer, hour, depth=0.0, *, version=None: calls.append((layer, hour, version)) or {"points": [], "metadata": {"available": True}})
    animated = fish.client.get("/api/great-lakes/wind?forecastHour=7&animation=1&data=gfs%7C2026-10-10T21%3A00%3A00Z%7Cdraw%3A2")
    assert animated.status_code == 200 and animated.json["metadata"]["available"] is True
    assert calls == [("wind", 7.0, "gfs|2026-10-10T21:00:00Z|draw:2")]
    assert fish.client.get("/api/great-lakes/wind?forecastHour=soon&animation=1").status_code == 400

    monkeypatch.setattr(animation, "index", lambda layer, depth: {"layer": layer, "ready": True, "frames": []})
    assert fish.client.get("/api/great-lakes/animation/wind").json["layer"] == "wind"


def test_model_points_and_source_identity(fish, monkeypatch):
    from backend import great_lakes_cache as cache
    monkeypatch.setattr(wind, "forecast", lambda hour: {"points": [{"latitude": 43, "longitude": -78}, {"latitude": 41, "longitude": -90}]})
    response = fish.client.get("/api/great-lakes/model-points?kind=wind&south=42&west=-79&north=44&east=-77")
    assert response.status_code == 200 and response.json["points"] == [43, -78]
    assert response.json["models"][0]["model"] == "GFS"



def test_wind_index_and_frame_share_base_valid_time(monkeypatch):
    from backend import great_lakes_animation as animation, great_lakes_service as service
    calls = []
    def forecast(hour, now=None):
        calls.append((hour, now))
        return {"points": [], "metadata": {"run": "20261010t12z", "validTime": "2026-10-10T16:00:00Z", "available": True}}
    monkeypatch.setattr(wind, "forecast", forecast)
    monkeypatch.setattr(service, "animation_offsets", lambda now=None: (0, 2, 5))
    index = animation.index("wind")
    assert index["ready"] and index["frames"][1]["validTime"] == "2026-10-10T18:00:00Z"
    animation.frame_payload("wind", 2, version=index["version"])
    assert calls[-1] == (2, animation._wind_anchor(index["version"]))

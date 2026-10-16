import math
from array import array

import pytest

from backend import great_lakes_service as service, great_lakes_target_temperature as target
from backend.great_lakes_render import ScalarGrid
from backend.great_lakes_volumes import Volume


def test_multiple_crossings_and_flat_band():
    assert target.crossings([0, 10, 20], [15, 5, 15], 10) == [
        {"topMeters": 5, "bottomMeters": 5}, {"topMeters": 15, "bottomMeters": 15}]
    assert target.crossings([0, 10, 20, 30], [15, 10, 10, 5], 10) == [{"topMeters": 10, "bottomMeters": 20}]
    assert target.crossings([0, 10], [10, 5], 10) == [{"topMeters": 0, "bottomMeters": 0}]


def test_no_extrapolation_no_gap_bridging_or_below_bottom():
    assert target.crossings([0, 10], [15, 14], 10) == []
    assert target.crossings([0, 10, 20], [15, math.nan, 5], 10) == []
    assert target.crossings([0, 10, 20], [15, -999, 5], 10) == []
    assert target.crossings([0, 10, 20], [15, 12, 5], 10, bottom=12) == []


def test_grid_selection_and_transparent_nonmatches(monkeypatch):
    volume = Volume("temperature", "LOOFS", "run", 0, 2, 2, 1, 1, [43, 44], [-79, -78],
                    array("B", [1, 1, 1, 0]), [0, 10, 20],
                    {"temp": array("f", [15, 17, 13, 15, 5, 14, math.nan, 5, 15, 13, 5, 15])})
    monkeypatch.setattr(service, "_model_volume", lambda *args: ({"id": "run", "cycleEpoch": 0}, 0, "path", {"temperature": "temp"}, volume))
    monkeypatch.setattr(service, "_volume_bottom_depths", lambda *args: [30] * 4)
    monkeypatch.setattr(service, "_regular_grid_dimensions", lambda *args: (2, 2, [0, 10, 20]))
    monkeypatch.setattr(service, "_water_mask_or_none", lambda *args: None)
    shallow, metadata = target._grid("LOOFS", 0, 10, "shallowest")
    deep, _ = target._grid("LOOFS", 0, 10, "deepest")
    assert shallow["grid"].values == [5, 0, 0, 0]
    assert deep["grid"].values == [15, 0, 0, 0]
    assert shallow["grid"].valid == [True, False, False, False]
    assert shallow["noData"] == [False, True, True, False]
    assert metadata["available"] and metadata["matchingCells"] == 1
    assert metadata["minSurfaceTemperatureC"] == 13
    assert metadata["maxSurfaceTemperatureC"] == 17
    monkeypatch.setattr(service, "MODELS", ("LOOFS",))
    result = target.point(0, 10, 43, -79)
    assert len(result["crossings"]) == 2


def test_raster_bounds_fit_matching_depths_across_available_models(monkeypatch):
    monkeypatch.setattr(service, "MODELS", ("LOOFS", "LEOFS"))
    rendered = []

    def grid(model, *_):
        values = [5.0, 0.0, 18.0] if model == "LOOFS" else [9.0, 0.0, 27.0]
        min_surface = 3.0 if model == "LOOFS" else 1.0
        max_surface = 18.0 if model == "LOOFS" else 21.0
        valid = [True, False, True]
        return ({"model": model, "validTime": "now", "grid": ScalarGrid(values, valid, 1, 3, 1, 1), "extra": {}},
                {"model": model, "available": True, "matchingCells": 2,
                 "minSurfaceTemperatureC": min_surface, "maxSurfaceTemperatureC": max_surface})

    monkeypatch.setattr(target, "_grid", grid)
    monkeypatch.setattr(service, "_render_rasters", lambda inputs, stops, low, high, resolution:
                        rendered.append((low, high)) or [])
    result = target._build(0, 10, "shallowest", 256)

    assert rendered == [(5.0, 27.0)]
    assert result["metadata"]["minDepthMeters"] == 5.0
    assert result["metadata"]["maxDepthMeters"] == 27.0
    assert result["metadata"]["minSurfaceTemperatureC"] == 1.0
    assert result["metadata"]["maxSurfaceTemperatureC"] == 21.0


@pytest.mark.parametrize("query", ["targetC=nan", "targetC=inf", "targetC=-1", "targetC=31", "targetC=bad", "selection=bad", "animation=1"])
def test_bad_target_requests(fish, query):
    assert fish.client.get("/api/great-lakes/target-temperature?" + query).status_code == 400


def test_target_parameters_and_partial_availability(fish, monkeypatch):
    calls = []
    def raster(hour, temperature, selection):
        calls.append((hour, temperature, selection))
        return {"rasters": [], "metadata": {"models": [{"available": False}]}}
    monkeypatch.setattr(target, "rasters", raster)
    response = fish.client.get("/api/great-lakes/target-temperature?forecastHour=6&targetC=9&selection=deepest")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert calls == [(6, 9, "deepest")]

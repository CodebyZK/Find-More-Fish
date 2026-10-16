from __future__ import annotations

from array import array

from conftest import make_app
from backend import great_lakes_service as service
from backend import great_lakes_upwelling as upwelling
from backend import great_lakes_volumes as volumes

ROWS, COLUMNS = 20, 30


def _lake(surface_c: float = 18.0, depth: float = 40.0):
    """A rectangular lake: land around the edge, open water inside."""
    wet = [0 < row < ROWS - 1 and 0 < column < COLUMNS - 1 for row in range(ROWS) for column in range(COLUMNS)]
    surface = [surface_c if ok else None for ok in wet]
    bottoms = [depth if ok else None for ok in wet]
    return wet, surface, bottoms


def _patch(values: list, rows: range, columns: range, value) -> None:
    for row in rows:
        for column in columns:
            values[row * COLUMNS + column] = value


def _score_kinds(result: dict) -> set[str]:
    return {"upwelling" if value < 0 else "downwelling" for value in result["score"] if value is not None}


def _scores(surface, previous, thermocline, bottoms, *args, **kwargs):
    # These summer fixtures assume stable offshore stratification.
    kwargs.setdefault("stratified", [depth is not None and depth >= 10 for depth in bottoms])
    return upwelling.scores(surface, previous, thermocline, bottoms, *args, **kwargs)


def test_cold_water_against_a_shore_is_upwelling() -> None:
    wet, surface, bottoms = _lake()
    _patch(surface, range(1, 6), range(1, 12), 18.0 - 3.0)  # 5.4 °F colder along the north shore
    near = upwelling.near_shore_cells(wet, ROWS, COLUMNS, 2)

    result = _scores(surface, None, None, bottoms, ROWS, COLUMNS, 8, 8, 4, near)

    marked = [cell for cell, value in enumerate(result["score"]) if value is not None]
    assert _score_kinds(result) == {"upwelling"}
    assert all(1 <= cell // COLUMNS <= 5 for cell in marked)
    strongest = min(value for value in result["score"] if value is not None)
    assert -upwelling.SCORE_LIMIT <= strongest <= -2.0


def test_a_lake_cooling_all_over_is_not_upwelling() -> None:
    # A cold front: every spot 4 °F cooler than yesterday, but no colder than its surroundings.
    wet, surface, bottoms = _lake(16.0)
    previous = [None if value is None else 18.2 for value in surface]

    result = _scores(surface, previous, None, bottoms, ROWS, COLUMNS, 8, 8)

    assert _score_kinds(result) == set()


def test_cooling_over_the_day_strengthens_a_weak_cold_patch() -> None:
    wet, surface, bottoms = _lake()
    _patch(surface, range(1, 6), range(1, 12), 18.0 - 1.1)
    previous = [None if value is None else 18.0 for value in surface]

    assert _score_kinds(_scores(surface, None, None, bottoms, ROWS, COLUMNS, 8, 8)) == set()
    assert _score_kinds(_scores(surface, previous, None, bottoms, ROWS, COLUMNS, 8, 8)) == {"upwelling"}


def test_warm_water_piled_against_a_shore_with_a_deeper_thermocline_is_downwelling() -> None:
    wet, surface, bottoms = _lake()
    thermocline = [10.0 if ok else None for ok in wet]
    _patch(thermocline, range(14, 19), range(15, 29), 28.0)  # 18 m (59 ft) deeper along the south shore

    result = _scores(surface, None, thermocline, bottoms, ROWS, COLUMNS, 8, 8, 4, upwelling.near_shore_cells(wet, ROWS, COLUMNS, 2))

    assert _score_kinds(result) == {"downwelling"}


def test_shallow_water_and_small_or_offshore_patches_are_left_out() -> None:
    wet, surface, bottoms = _lake()
    _patch(bottoms, range(1, 6), range(1, 12), 4.0)  # a shallow bay
    _patch(surface, range(1, 6), range(1, 12), 15.0)
    _patch(surface, range(9, 12), range(13, 17), 15.0)  # a cold eddy in the middle of the lake
    _patch(surface, range(15, 17), range(25, 27), 15.0)  # a cold speck by the shore
    near = upwelling.near_shore_cells(wet, ROWS, COLUMNS, 2)

    result = _scores(surface, None, None, bottoms, ROWS, COLUMNS, 8, 8, 6, near)

    assert _score_kinds(result) == set()


def test_box_mean_and_shore_distance() -> None:
    values = [float(index) for index in range(9)]
    assert upwelling.box_mean(values, [True] * 9, 3, 3, 1, 1)[4] == 4.0
    assert upwelling.box_mean(values, [index != 8 for index in range(9)], 3, 3, 1, 1)[8] == (4 + 5 + 7) / 3
    wet, _, _ = _lake()
    near = upwelling.near_shore_cells(wet, ROWS, COLUMNS, 2)
    assert near[2 * COLUMNS + 15] and not near[10 * COLUMNS + 15] and not near[0]


def test_the_day_before_is_the_older_run_at_the_same_forecast_hour() -> None:
    path = "NOAA/LOOFS/MODELS/2026/10/01/loofs.t06z.20261001.regulargrid.f005.nc"
    assert upwelling.previous_day_path(path) == "NOAA/LOOFS/MODELS/2026/09/30/loofs.t06z.20260930.regulargrid.f005.nc"
    assert upwelling.previous_day_path("nonsense") is None


def test_uniform_cooling_does_not_promote_an_existing_cold_patch() -> None:
    _, surface, bottoms = _lake()
    _patch(surface, range(1, 6), range(1, 12), 16.9)
    previous = [value + 2 if value is not None else None for value in surface]
    before = _scores(surface, surface, None, bottoms, ROWS, COLUMNS, 8, 8)
    after = _scores(surface, previous, None, bottoms, ROWS, COLUMNS, 8, 8)
    assert after["score"] == before["score"]
    assert all(abs(value) < 1e-9 for value in after["relativeChange"] if value is not None)
    assert all(abs(value + 2) < 1e-9 for value in after["change"] if value is not None)


def test_subsurface_displacement_detects_both_directions_without_surface_change() -> None:
    wet, surface, bottoms = _lake()
    near = upwelling.near_shore_cells(wet, ROWS, COLUMNS, 2)
    for background, coastal, kind in [(28.0, 10.0, "upwelling"), (10.0, 28.0, "downwelling")]:
        thermocline = [background if ok else None for ok in wet]
        _patch(thermocline, range(1, 6), range(1, 12), coastal)
        found = _scores(surface, surface, thermocline, bottoms, ROWS, COLUMNS, 8, 8, 4, near)
        assert _score_kinds(found) == {kind}
        assert all(value == 1 for value in found["confidence"] if value is not None)


def test_warm_surface_and_local_warming_cannot_trigger_downwelling() -> None:
    wet, surface, bottoms = _lake()
    previous = surface.copy()
    _patch(surface, range(1, 6), range(1, 12), 24.0)
    near = upwelling.near_shore_cells(wet, ROWS, COLUMNS, 2)
    # A strong warm patch, even warming faster than surrounding water, must not
    # qualify with absent, unchanged, or insufficiently depressed thermoclines.
    for coastal_depth in (None, 10.0, 12.0):
        thermocline = [10.0 if ok else None for ok in wet]
        _patch(thermocline, range(1, 6), range(1, 12), coastal_depth)
        found = _scores(surface, previous, thermocline, bottoms, ROWS, COLUMNS, 8, 8, 4, near)
        assert "downwelling" not in _score_kinds(found)
        assert found["score"][2 * COLUMNS + 3] is None
        assert found["confidence"][2 * COLUMNS + 3] is None


def test_downwelling_does_not_require_day_before_or_surface_warming() -> None:
    wet, surface, bottoms = _lake()
    thermocline = [10.0 if ok else None for ok in wet]
    _patch(thermocline, range(1, 6), range(1, 12), 28.0)
    found = _scores(surface, None, thermocline, bottoms, ROWS, COLUMNS, 8, 8, 4,
                    upwelling.near_shore_cells(wet, ROWS, COLUMNS, 2))
    assert found["score"][2 * COLUMNS + 3] > 0
    assert found["confidence"][2 * COLUMNS + 3] == 1
    assert found["anomaly"][2 * COLUMNS + 3] == 0


def test_no_stratified_background_means_no_event() -> None:
    wet, surface, bottoms = _lake(4.0)
    _patch(surface, range(1, 6), range(1, 12), 1.0)
    found = upwelling.scores(surface, None, None, bottoms, ROWS, COLUMNS, 8, 8,
                            near_shore=upwelling.near_shore_cells(wet, ROWS, COLUMNS, 2), stratified=[False] * len(wet))
    assert not _score_kinds(found)
    assert not any(found["assessed"])


def test_full_upwelling_can_lose_its_local_thermocline() -> None:
    wet, surface, bottoms = _lake()
    thermocline = [20.0 if ok else None for ok in wet]
    stable = wet.copy()
    _patch(surface, range(1, 6), range(1, 12), 8.0)
    _patch(thermocline, range(1, 6), range(1, 12), None)
    _patch(stable, range(1, 6), range(1, 12), False)
    found = _scores(surface, None, thermocline, bottoms, ROWS, COLUMNS, 8, 8, 4,
                    upwelling.near_shore_cells(wet, ROWS, COLUMNS, 2), stratified=stable)
    assert "upwelling" in _score_kinds(found)
    assert found["score"][2 * COLUMNS + 3] < 0


def test_conflicting_surface_and_subsurface_evidence_is_not_labeled() -> None:
    wet, surface, bottoms = _lake()
    thermocline = [10.0 if ok else None for ok in wet]
    _patch(surface, range(1, 6), range(1, 12), 12.0)
    _patch(thermocline, range(1, 6), range(1, 12), 28.0)
    found = _scores(surface, None, thermocline, bottoms, ROWS, COLUMNS, 8, 8)
    assert found["score"][2 * COLUMNS + 3] is None


def test_agreeing_surface_and_subsurface_evidence_is_supported() -> None:
    wet, surface, bottoms = _lake()
    thermocline = [28.0 if ok else None for ok in wet]
    _patch(surface, range(1, 6), range(1, 12), 12.0)
    _patch(thermocline, range(1, 6), range(1, 12), 10.0)
    found = _scores(surface, None, thermocline, bottoms, ROWS, COLUMNS, 8, 8)
    assert found["confidence"][2 * COLUMNS + 3] == 2


def test_water_at_the_grid_edge_is_not_a_shore() -> None:
    assert not any(upwelling.near_shore_cells([True] * 25, 5, 5, 2))
    assert not any(upwelling.near_shore_cells([True] * 25, 5, 5, 1, 1, 2))


def test_shore_distance_respects_unequal_grid_spacing() -> None:
    wet = [False, True, True, True, True]
    assert upwelling.near_shore_cells(wet, 1, 5, 1, 1, 4, reach_km=10) == [False, True, True, False, False]


def test_reference_excludes_the_cell_and_needs_enough_support() -> None:
    values = [18.0] * 25
    values[12] = 5.0
    assert upwelling.reference_mean(values, [True] * 25, 5, 5, 2, 2)[12] == 18.0
    assert upwelling.reference_mean(values, [index == 12 for index in range(25)], 5, 5, 2, 2)[12] is None


def test_density_check_rejects_mixed_and_inverted_profiles() -> None:
    volume = _volume()
    cells = volume.cells
    bottoms = [40.0] * cells
    assert any(upwelling._stratified_cells(volume, "temp", bottoms))
    for upper, lower in [(4.0, 4.0), (1.0, 4.0), (5.0, 0.0)]:
        volume.variables["temp"] = array("f", [upper] * cells + [lower] * cells)
        assert not any(upwelling._stratified_cells(volume, "temp", bottoms))


def test_previous_surface_prefers_the_same_forecast_run(monkeypatch) -> None:
    volume = _volume()
    path = "NOAA/LOOFS/MODELS/2026/10/05/loofs.t06z.20261005.regulargrid.f048.nc"
    earlier = path.replace("f048", "f024")
    run = {"id": "20261005t06z", "files": {24: earlier, 48: path}}
    requested = []
    def fetch(url, expression):
        requested.append(url)
        return {"temp": (None, [18.0] * volume.cells)}
    monkeypatch.setattr(upwelling.gl_cache, "fetch_dods", fetch)
    assert upwelling._previous_surface("LOOFS", run, 48, path, volume, "temp") == [18.0] * volume.cells
    assert requested == [f"{service.THREDDS}/dodsC/{earlier}"]


def _volume() -> volumes.Volume:
    wet, surface, _ = _lake()
    _patch(surface, range(1, 6), range(1, 12), 15.0)
    levels = [surface, [None if value is None else 8.0 for value in surface]]
    values = array("f", [float("nan") if value is None else value for level in levels for value in level])
    return volumes.Volume("temperature", "LOOFS", "20261005t06z", 5, ROWS, COLUMNS, 1, 1,
                          [43.0 + 0.01 * row for row in range(ROWS)], [-78.0 + 0.013 * column for column in range(COLUMNS)],
                          array("B", wet), [0.0, 30.0], {"temp": values})


def test_layer_and_point_lookup(monkeypatch, tmp_path) -> None:
    volume = _volume()
    run = {"id": "20261005t06z", "cycleEpoch": 1791180000.0, "files": {5: "NOAA/LOOFS/MODELS/2026/10/05/loofs.t06z.20261005.regulargrid.f005.nc"}}
    path = run["files"][5]
    monkeypatch.setattr(service, "MODELS", ("LOOFS",))
    monkeypatch.setattr(service, "_model_volume", lambda kind, model, hour: (run, 5, path, {"temperature": "temp"}, volume))
    monkeypatch.setattr(service, "_thermocline_depths", lambda *args: [None] * volume.cells)
    monkeypatch.setattr(service, "_volume_bottom_depths", lambda model, vol: [40.0] * vol.cells)
    monkeypatch.setattr(service, "_regular_grid_dimensions", lambda p: (ROWS, COLUMNS, [0.0, 30.0]))
    monkeypatch.setattr(service, "_water_mask_or_none", lambda *args: None)
    monkeypatch.setattr(service, "_data_key", lambda models, hour: (("LOOFS", run["id"], 5),))
    fetched = []

    def no_day_before(url, expression):
        fetched.append(url)
        raise OSError("NOAA unreachable")

    monkeypatch.setattr(upwelling.gl_cache, "fetch_dods", no_day_before)

    value = upwelling.upwelling_value(0, 43.03, -77.96, ("LOOFS",))
    assert value["available"] and value["kind"] == "upwelling" and value["evidenceIndex"] >= upwelling.MIN_SCORE
    assert value["confidence"] == "possible" and value["assessment"] == "assessed"
    assert value["comparedWithDayBefore"] is False and fetched == [f"{service.THREDDS}/dodsC/NOAA/LOOFS/MODELS/2026/10/04/loofs.t06z.20261004.regulargrid.f005.nc"]
    assert round(value["surfaceC"], 1) == 15.0 and value["surroundingC"] > 15.0
    open_lake = upwelling.upwelling_value(0, 43.12, -77.75, ("LOOFS",))
    assert open_lake["available"] and open_lake["kind"] is None

    payload = upwelling.upwelling_rasters(0, 128, ("LOOFS",))
    assert payload["metadata"]["minScore"] == -upwelling.SCORE_LIMIT and payload["metadata"]["maxScore"] == upwelling.SCORE_LIMIT
    assert payload["metadata"]["scoreUnits"] == "dimensionless"
    model = payload["metadata"]["models"][0]
    assert model["available"] and model["upwellingCells"] > 0 and model["downwellingCells"] == 0 and model["comparedWithDayBefore"] is False
    assert payload["rasters"][0]["imageUrl"].startswith(("data:image/", "/api/"))

    client = make_app(tmp_path).client
    assert client.get("/api/great-lakes/upwelling-value?forecastHour=0&latitude=43.03&longitude=-77.96&models=LOOFS").json["kind"] == "upwelling"
    assert client.get("/api/great-lakes/history/point/upwelling?time=2026-10-05T03:00:00Z&latitude=43.03&longitude=-77.96").json == {"available": False, "savedMapOnly": True}

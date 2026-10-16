"""Depths of a chosen isotherm, interpolated only between valid adjacent levels."""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import great_lakes_service as service
from .great_lakes_render import GridAxes, ScalarGrid


TARGET_TEMPERATURE_RENDER_VERSION = 4


def crossings(depths, temperatures, target, bottom=None):
    """Return every crossing or constant-temperature interval; never bridge gaps."""
    matches = []
    previous = None
    for depth, temperature in zip(depths, temperatures):
        if not math.isfinite(temperature) or not -5 <= temperature <= 45 or (bottom is not None and depth > bottom):
            previous = None
            continue
        if temperature == target:
            matches.append((float(depth), float(depth)))
        if previous is not None:
            d0, t0 = previous
            if t0 == target and temperature == target:
                matches.append((float(d0), float(depth)))
            elif (t0 - target) * (temperature - target) < 0:
                value = d0 + (target - t0) * (depth - d0) / (temperature - t0)
                matches.append((value, value))
        previous = (depth, temperature)
    merged = []
    for top, bottom_depth in sorted(matches):
        if merged and top <= merged[-1][1] + 1e-6:
            merged[-1] = (merged[-1][0], max(bottom_depth, merged[-1][1]))
        else:
            merged.append((top, bottom_depth))
    return [{"topMeters": top, "bottomMeters": bottom_depth} for top, bottom_depth in merged]


def _grid(model, forecast_hour, target, selection):
    run, hour, path, variables, volume = service._model_volume("temperature", model, forecast_hour)
    temperatures = volume.variables[variables["temperature"]]
    surface_values = volume.level(variables["temperature"], volume.nearest_level(0.0))
    surface_temperatures = [float(temperature) for temperature, wet in zip(surface_values, volume.wet)
                            if wet and math.isfinite(temperature) and -5 <= temperature <= 45]
    bottoms = service._volume_bottom_depths(model, volume)
    values, valid = [], []
    for cell in range(volume.cells):
        matches = crossings(volume.depths, (temperatures[level * volume.cells + cell] for level in range(len(volume.depths))), target,
                            bottoms[cell] if bottoms else None) if volume.wet[cell] else []
        values.append((matches[-1]["bottomMeters"] if selection == "deepest" else matches[0]["topMeters"]) if matches else 0.0)
        valid.append(bool(matches))
    ny, nx, _ = service._regular_grid_dimensions(path)
    wet = [bool(value) for value in volume.wet]
    metadata = {"model": model, "available": True, "run": run["id"], "selectedForecastHour": hour,
                "validTime": service._valid_time_text(run, hour), "matchingCells": sum(valid),
                "minSurfaceTemperatureC": min(surface_temperatures) if surface_temperatures else None,
                "maxSurfaceTemperatureC": max(surface_temperatures) if surface_temperatures else None}
    return {"model": model, "validTime": metadata["validTime"],
            "grid": ScalarGrid(values, valid, volume.rows, volume.columns, volume.y_stride, volume.x_stride),
            "axes": GridAxes.from_axes(volume.latitude_axis, volume.longitude_axis, volume.y_stride, volume.x_stride),
            "water": service._water_mask_or_none(model, path, ny, nx) or service._coarse_water_mask(wet, volume.rows, volume.columns, volume.y_stride, volume.x_stride),
            "noData": [water and not ok for water, ok in zip(wet, valid)], "extra": {}}, metadata


def rasters(forecast_hour, target, selection="shallowest", resolution=512):
    key = (f"target-temperature-v{TARGET_TEMPERATURE_RENDER_VERSION}", service._data_key(service.MODELS, forecast_hour), forecast_hour, target, selection, resolution, service._cache_bucket())
    return service._shared_payload(_memory, key, lambda: _build(forecast_hour, target, selection, resolution), 12)


_memory = {}


def _build(forecast_hour, target, selection, resolution):
    inputs, models = [], []
    with ThreadPoolExecutor(max_workers=4) as executor:
        jobs = {model: executor.submit(_grid, model, forecast_hour, target, selection) for model in service.MODELS}
        for model, job in jobs.items():
            try:
                grid, metadata = job.result()
                if any(grid["grid"].valid):
                    inputs.append(grid)
                models.append(metadata)
            except Exception as error:
                models.append({"model": model, "available": False, "error": str(error)})
    matching_depths = [value for item in inputs for value, valid in zip(item["grid"].values, item["grid"].valid) if valid]
    surface_ranges = [(item["minSurfaceTemperatureC"], item["maxSurfaceTemperatureC"])
                      for item in models if item.get("available")
                      and item.get("minSurfaceTemperatureC") is not None
                      and item.get("maxSurfaceTemperatureC") is not None]
    minimum = min(matching_depths) if matching_depths else None
    maximum = max(matching_depths) if matching_depths else None
    return {"rasters": service._render_rasters(inputs, service.THERMOCLINE_COLOR_STOPS, minimum, maximum, resolution) if inputs else [],
            "metadata": {"models": models, "forecastHour": forecast_hour, "targetC": target, "selection": selection,
                         "minDepthMeters": minimum, "maxDepthMeters": maximum,
                         "minSurfaceTemperatureC": min((low for low, _ in surface_ranges), default=None),
                         "maxSurfaceTemperatureC": max((high for _, high in surface_ranges), default=None),
                         "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}}


def point(forecast_hour, target, latitude, longitude):
    errors = []
    for model in service.MODELS:
        try:
            run, hour, _, variables, volume = service._model_volume("temperature", model, forecast_hour)
            cell = service._nearest_wet_cell(volume, latitude, longitude)
            if cell is None:
                continue
            bottoms = service._volume_bottom_depths(model, volume)
            matches = crossings(volume.depths, volume.profile(variables["temperature"], cell), target, bottoms[cell] if bottoms else None)
            return {"available": True, "model": model, "targetC": target, "crossings": matches,
                    "validTime": service._valid_time_text(run, hour)}
        except Exception as error:
            errors.append(str(error))
    return {"available": False, "crossings": [], "errors": errors}

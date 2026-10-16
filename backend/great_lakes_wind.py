"""NOAA GFS 0.25-degree, 10 m wind and surface gust forecasts for the Great Lakes."""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from . import great_lakes_cache as cache
from . import grib2

SOURCE = "NOAA GFS · 10 m wind · 0.25° grid"
WIND_DATA_VERSION = 2
FIELDS = {"u": ("UGRD", "10_m_above_ground"), "v": ("VGRD", "10_m_above_ground"), "gust": ("GUST", "surface")}


def filter_url(cycle, hour, variable, level):
    date = datetime.fromtimestamp(cycle, timezone.utc)
    params = {"file": f"gfs.t{date:%H}z.pgrb2.0p25.f{hour:03d}", "dir": f"/gfs.{date:%Y%m%d}/{date:%H}/atmos",
              f"var_{variable}": "on", f"lev_{level}": "on", "subregion": "",
              "leftlon": -94, "rightlon": -75, "toplat": 50, "bottomlat": 40}
    return "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?" + urlencode(params)


def vector(u, v, gust):
    speed = math.hypot(u, v)
    return {"u": u, "v": v, "speedMetersPerSecond": speed, "gustMetersPerSecond": gust,
            "directionDegrees": (math.degrees(math.atan2(-u, -v)) + 360) % 360 if speed > 0.01 else None,
            "travelDegrees": (math.degrees(math.atan2(u, v)) + 360) % 360}


def _hour(cycle, hour):
    date = datetime.fromtimestamp(cycle, timezone.utc)
    path = cache.path_for("wind", f"{date:%Y%m%d%H}-f{hour:03d}-v{WIND_DATA_VERSION}.json")
    saved = cache.read_json(path)
    if isinstance(saved, dict):
        return saved
    with cache.resource_lock("wind", (cycle, hour)):
        saved = cache.read_json(path)
        if isinstance(saved, dict):
            return saved
        messages = {name: grib2.decode(cache.http_get(filter_url(cycle, hour, variable, level), timeout=25))
                    for name, (variable, level) in FIELDS.items()}
        grid = messages["u"].grid
        if any(message.grid != grid for message in messages.values()):
            raise RuntimeError("NOAA wind fields have different grids")
        points = []
        for cell, (u, v, gust) in enumerate(zip(*(messages[name].values for name in FIELDS))):
            if not all(math.isfinite(value) for value in (u, v, gust)) or gust < 0:
                continue
            latitude, longitude = grid.coordinates(cell % grid.nx, cell // grid.nx)
            if 40 <= latitude <= 50 and -94 <= longitude <= -75:
                points.append({"latitude": latitude, "longitude": longitude, **vector(u, v, gust)})
        if not points:
            raise RuntimeError("NOAA returned no valid Great Lakes wind cells")
        payload = {"points": points, "metadata": {"source": SOURCE, "run": f"{date:%Y%m%d}t{date:%H}z",
                   "runTime": date.isoformat().replace("+00:00", "Z"),
                   "validTime": datetime.fromtimestamp(cycle + hour * 3600, timezone.utc).isoformat().replace("+00:00", "Z")}}
        cache.write_json(path, payload)
        # Keep at most three days; this cache has no historical UI contract.
        for old in path.parent.glob("*-v*.json"):
            if time.time() - old.stat().st_mtime > 3 * 86400:
                old.unlink(missing_ok=True)
        return payload


def forecast(forecast_hour, now=None):
    now = time.time() if now is None else now
    # GFS cycles are six-hourly. Allow four hours for publication, then fall back one run.
    latest = math.floor((now - 4 * 3600) / (6 * 3600)) * 6 * 3600
    for back in range(2):
        cycle = latest - back * 6 * 3600
        hour = max(0, round((now - cycle) / 3600)) + forecast_hour
        try:
            payload = _hour(cycle, hour)
            return {**payload, "metadata": {**payload["metadata"], "forecastHour": forecast_hour, "available": True}}
        except Exception as error:
            last_error = error
    raise RuntimeError("NOAA wind forecast is temporarily unavailable") from last_error


def point(forecast_hour, latitude, longitude):
    payload = forecast(forecast_hour)
    if not (40 <= latitude <= 50 and -94 <= longitude <= -75):
        return {"available": False}
    nearest = min(payload["points"], key=lambda p: (p["latitude"] - latitude) ** 2 + ((p["longitude"] - longitude) * math.cos(math.radians(latitude))) ** 2)
    return {**nearest, **payload["metadata"], "available": True}


def model_points(bounds, limit=12000):
    south, west, north, east = bounds
    payload = forecast(0)
    selected = [point for point in payload["points"] if south <= point["latitude"] <= north and west <= point["longitude"] <= east]
    too_many = len(selected) > limit
    return {"kind": "wind", "count": len(selected), "limit": limit, "tooMany": too_many,
            "models": [{"model": "GFS", "available": True, "pointsInView": len(selected)}],
            "points": [] if too_many else [coordinate for point in selected for coordinate in (point["latitude"], point["longitude"])]}

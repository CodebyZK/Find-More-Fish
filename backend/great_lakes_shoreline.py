"""Trace model lake boundaries from NOAA's native FVCOM triangle meshes."""

from __future__ import annotations

import math

from . import great_lakes_cache as cache


def trace_rings(latitudes, longitudes, connectivity, faces: int) -> tuple:
    """Trace every outer shore and island ring from mesh edges used once.

    NOAA's ``nv`` connectivity is a 1-based, three-by-face array. Triangles
    are oriented with water on the left; shared edges are internal water.
    """
    nodes = len(latitudes)
    if len(longitudes) != nodes or len(connectivity) != 3 * faces:
        raise ValueError("Incomplete NOAA mesh coordinates/connectivity")
    if any(not math.isfinite(value) for value in (*latitudes, *longitudes)):
        raise ValueError("Invalid NOAA mesh coordinates")

    boundary, internal = {}, set()
    for face in range(faces):
        a, b, c = (int(connectivity[corner * faces + face]) - 1 for corner in range(3))
        if min(a, b, c) < 0 or max(a, b, c) >= nodes or len({a, b, c}) != 3:
            raise ValueError("Invalid NOAA triangle node indices")
        cross = ((longitudes[b] - longitudes[a]) * (latitudes[c] - latitudes[a])
                 - (latitudes[b] - latitudes[a]) * (longitudes[c] - longitudes[a]))
        if cross == 0:
            raise ValueError("Degenerate NOAA triangle")
        if cross < 0:
            b, c = c, b
        for start, end in ((a, b), (b, c), (c, a)):
            key = tuple(sorted((start, end)))
            if key in internal:
                raise ValueError("Non-manifold NOAA mesh edge")
            if key in boundary:
                if boundary.pop(key) != (end, start):
                    raise ValueError("Overlapping NOAA triangles")
                internal.add(key)
            else:
                boundary[key] = (start, end)

    following = {}
    for start, end in boundary.values():
        if start in following:
            raise ValueError("Branched NOAA shoreline")
        following[start] = end
    rings = []
    while following:
        start = next(iter(following))
        node, ring = start, []
        while True:
            ring.append((float(longitudes[node]), float(latitudes[node])))
            if node not in following:
                raise ValueError("Open NOAA shoreline")
            node = following.pop(node)
            if node == start:
                break
        if len(ring) < 3:
            raise ValueError("Incomplete NOAA shoreline ring")
        rings.append(tuple(ring))
    if not rings:
        raise ValueError("NOAA mesh has no boundary")
    return tuple(sorted(rings, key=lambda ring: abs(signed_area(ring)), reverse=True))


def signed_area(ring) -> float:
    """Signed polygon area, with the origin shifted to reduce cancellation."""
    x0, y0 = ring[0]
    return sum((a[0] - x0) * (b[1] - y0) - (b[0] - x0) * (a[1] - y0)
               for a, b in zip(ring, (*ring[1:], ring[0]))) / 2


def model_rings(model: str, path: str) -> tuple:
    """Read and cache the static coordinates/connectivity for one model mesh."""
    from . import great_lakes_service as service

    fields_path = path.replace(".regulargrid.", ".fields.")
    if ".fields." not in fields_path:
        raise ValueError("NOAA forecast path has no matching FVCOM fields file")
    nodes, faces = service._field_dimensions(fields_path)
    target = cache.path_for("static", model, f"mesh-shoreline-{nodes}-{faces}-v1.json")

    def build():
        arrays = cache.fetch_dods(
            f"{service.THREDDS}/dodsC/{fields_path}",
            f"lat[0:1:{nodes - 1}],lon[0:1:{nodes - 1}],nv[0:1:2][0:1:{faces - 1}]",
        )
        latitudes = arrays["lat"][1]
        longitudes = [service._great_lakes_longitude(value) for value in arrays["lon"][1]]
        return {"rings": trace_rings(latitudes, longitudes, arrays["nv"][1], faces), "sourcePath": fields_path}

    saved = cache.get_or_create_json(
        target,
        build,
        valid=lambda value: isinstance(value, dict) and bool(value.get("rings")),
    )
    return tuple(tuple(tuple(point) for point in ring) for ring in saved["rings"])

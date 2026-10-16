import multiprocessing
import os
import time
from array import array
from pathlib import Path
from unittest.mock import patch
import pytest
from backend import great_lakes_cache as cache, great_lakes_service as service, great_lakes_volumes as volumes, great_lakes_waves as waves, grib2
@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_cache_dir", tmp_path)

def _cache_worker(kind, directory, ready, start, results):
    """Spawned processes have independent memory caches but share the disk cache."""
    cache.configure(directory)
    def build(*args):
        (Path(directory) / f"built-{os.getpid()}").touch()
        time.sleep(.2)
        if kind == "render":
            return {"metadata": {"models": [{"model": "LOOFS", "available": True}]}, "rasters": []}
        if kind == "waves":
            grid = grib2.RegularGrid(2, 2, 43, -79, 43.1, -78.9, .1, .1, 0x40)
            arrays = {name: array("f", [1] * 4) for name in waves.WAVE_VARIABLES}
            cache.write_record(waves._disk_path("run", 0), {"grid": grid.to_header()}, arrays)
            return waves.WaveHour("run", 0, grid, arrays["height"], arrays["period"], arrays["direction"])
        volume = volumes.Volume("temperature", "LOOFS", "run", 0, 2, 2, 1, 1, [43, 43.1], [-79, -78.9], array("B", [1] * 4), [0], {"temp": array("f", [15] * 4)})
        cache.write_record(volumes._disk_path("temperature", "LOOFS", "run", 0, 1, 1),
                           {"rows": 2, "columns": 2, "yStride": 1, "xStride": 1, "latitudeAxis": volume.latitude_axis,
                            "longitudeAxis": volume.longitude_axis, "depths": volume.depths}, {"wet": volume.wet, **volume.variables})
        return volume
    ready.put(True)
    start.wait(5)
    try:
        if kind == "render":
            value = service._shared_payload({}, ("audit", 0), build, 4)
            results.put(value["metadata"]["models"][0]["available"])
        elif kind == "waves":
            with patch.object(waves, "_download", build):
                results.put(waves.load_wave_hour({"id": "run"}, 0).height[0] == 1)
        else:
            with patch.object(volumes, "_download", build):
                results.put(volumes.load_volume("temperature", "LOOFS", "run", 0, "unused", 2, 2, [0], ["temp"]).variables["temp"][0] == 15)
    except Exception as error:
        results.put(repr(error))


@pytest.mark.parametrize("kind", ["volume", "waves", "render"])
def test_cache_misses_are_built_once_across_processes(tmp_path, kind):
    context = multiprocessing.get_context("spawn")
    ready, results, start = context.Queue(), context.Queue(), context.Event()
    processes = [context.Process(target=_cache_worker, args=(kind, str(tmp_path), ready, start, results)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        for _ in processes:
            assert ready.get(timeout=10) is True
        start.set()
        for _ in processes:
            assert results.get(timeout=10) is True
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        assert len(list(tmp_path.glob("built-*"))) == 1
    finally:
        start.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
        ready.close()
        results.close()


def test_forecast_lock_files_remain_bounded_and_waits_have_a_deadline(tmp_path):
    for forecast in range(600):
        with cache.resource_lock("audit", ("forecast", forecast)):
            pass
    assert len(list(cache.path_for("locks", "audit").glob("*.lock"))) <= 256
    with cache.resource_lock("audit", "same-resource"):
        with pytest.raises(TimeoutError):
            with cache.resource_lock("audit", "same-resource", timeout=.01):
                pytest.fail("second lock holder entered")

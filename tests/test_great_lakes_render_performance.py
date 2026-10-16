import pytest
from backend import great_lakes_render as render

def _axes(rows: int, columns: int) -> render.GridAxes:
    # 0.01° cells starting at 43 N, 80 W.
    latitudes = [43 + row * 0.01 for row in range(rows) for _ in range(columns)]
    longitudes = [-80 + column * 0.01 for _ in range(rows) for column in range(columns)]
    return render.GridAxes.from_samples(latitudes, longitudes, rows, columns, 1, 1)

def _reference_fill(values, valid, rows, columns, layers, fallback):
    """The original per-cell implementation, kept as the specification."""
    known = bytearray(1 if item else 0 for item in valid)
    filled = [value if item else 0.0 for value, item in zip(values, valid)]
    for _ in range(layers):
        updates = {}
        for index in range(rows * columns):
            if known[index]:
                continue
            row, column = divmod(index, columns)
            neighbours = [
                filled[r * columns + c]
                for r in range(max(0, row - 1), min(rows, row + 2))
                for c in range(max(0, column - 1), min(columns, column + 2))
                if known[r * columns + c]
            ]
            if neighbours:
                updates[index] = sum(neighbours) / len(neighbours)
        for index, value in updates.items():
            filled[index] = value
            known[index] = 1
    return [value if known[index] else fallback for index, value in enumerate(filled)]

@pytest.mark.parametrize("mode", ["F", "L"])
@pytest.mark.parametrize("replicate", [True, False])
def test_padding_preserves_edges_and_corners_exactly(mode, replicate):
    for rows, columns in ((1, 1), (1, 4), (4, 1), (3, 5)):
        values = [index + 0.25 if mode == "F" else index for index in range(rows * columns)]
        for pad in (0, 1, 3):
            expected = []
            for y in range(rows + 2 * pad):
                for x in range(columns + 2 * pad):
                    inside = pad <= y < rows + pad and pad <= x < columns + pad
                    row, column = min(rows - 1, max(0, y - pad)), min(columns - 1, max(0, x - pad))
                    expected.append(values[row * columns + column] if inside or replicate else 0)
            image = render._padded_image(mode, values, rows, columns, pad, replicate)
            assert list(image.getdata()) == expected

def test_fill_reuses_only_validity_and_keeps_each_frames_values():
    render._fill_plan.cache_clear()
    rows, columns, layers = 3, 5, 2
    valid = [index % 3 == 0 for index in range(rows * columns)]
    for offset in (0, 20):
        values = [float(index + offset) for index in range(rows * columns)]
        expected = _reference_fill(values, valid, rows, columns, layers, -99.0)
        actual = render.fill_invalid(values, valid, rows, columns, layers, -99.0)
        assert actual == pytest.approx(expected, abs=1e-5)
    assert render._fill_plan.cache_info().hits == 1
    valid[1] = True
    expected = _reference_fill(values, valid, rows, columns, layers, -99.0)
    assert render.fill_invalid(values, valid, rows, columns, layers, -99.0) == pytest.approx(expected, abs=1e-5)
    assert render._fill_plan.cache_info().misses == 2

def test_shoreline_cache_distinguishes_depth_masks_and_projection():
    render._shoreline_alpha.cache_clear()
    rows, columns = 64, 128
    axes = _axes(rows, columns)
    surface = render.WaterMask(rows, columns, 1, 1, bytes([255] * rows * columns))
    deep = render.WaterMask(rows, columns, 1, 1, bytes(255 if column < columns // 2 else 0
                                                  for _ in range(rows) for column in range(columns)))
    surface_alpha = render._shoreline_alpha(axes, surface, 128)
    assert render._shoreline_alpha(axes, surface, 128).tobytes() == surface_alpha.tobytes()
    deep_alpha = render._shoreline_alpha(axes, deep, 128)
    point = (deep_alpha.width - 5, deep_alpha.height // 2)
    assert surface_alpha.getpixel(point) == 255 and deep_alpha.getpixel(point) == 0
    assert render._shoreline_alpha(axes, surface, 64).width == 256
    moved = render.GridAxes(60, axes.latitude_step, axes.longitude0, axes.longitude_step)
    assert render._shoreline_alpha(moved, surface, 128).height != surface_alpha.height
    info = render._shoreline_alpha.cache_info()
    assert info.hits == 1 and info.misses == 4

def test_mixed_water_does_not_modify_cached_shoreline():
    rows, columns = 8, 16
    axes = _axes(rows, columns)
    water = render.WaterMask(rows, columns, 1, 1, bytes([255] * rows * columns))
    grid = render.ScalarGrid([10.0] * rows * columns, [True] * rows * columns, rows, columns, 1, 1)
    baseline = render.render_overlay(grid, axes, water, render.TEMPERATURE_COLOR_STOPS, 0, 30, 64)
    no_data = [column >= columns // 2 for _ in range(rows) for column in range(columns)]
    for mixed_color in (None, render.THERMOCLINE_MIXED_COLOR):
        render.render_overlay(grid, axes, water, render.TEMPERATURE_COLOR_STOPS, 0, 30, 64, no_data, mixed_color)
        assert render.render_overlay(grid, axes, water, render.TEMPERATURE_COLOR_STOPS, 0, 30, 64) == baseline

def test_large_render_caches_are_bounded():
    render._fill_plan.cache_clear()
    render._shoreline_alpha.cache_clear()
    for index in range(10):
        valid = [False] * 12
        valid[index] = True
        render.fill_invalid([1.0] * 12, valid, 3, 4)
        water = render.WaterMask(3, 4, 1, 1, bytes(255 if item else 0 for item in valid))
        render._shoreline_alpha(_axes(3, 4), water, 64)
    assert render._fill_plan.cache_info().currsize == 8
    assert render._shoreline_alpha.cache_info().currsize == 8

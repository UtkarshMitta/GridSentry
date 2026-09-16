"""Distance / footprint-overlap geometry against hand-built polygons."""
from __future__ import annotations

import pytest
from conftest import LAT, LON, esri_square

import geodata


def test_distance_zero_when_site_inside_polygon():
    assert geodata.nearest_distance_m(LAT, LON, esri_square(LAT, LON, 0, 0, 100)) == 0.0


def test_distance_to_polygon_east():
    # Square centred 500 m east, half-side 100 m → west edge 400 m away.
    d = geodata.nearest_distance_m(LAT, LON, esri_square(LAT, LON, 500, 0, 100))
    assert d == pytest.approx(400, abs=2)


def test_site_in_polygon_hole_is_outside():
    """A site on an island inside a ring-shaped wetland is not 'in' the wetland."""
    outer = esri_square(LAT, LON, 0, 0, 300)["rings"][0]
    hole = list(reversed(esri_square(LAT, LON, 0, 0, 100)["rings"][0]))
    d = geodata.nearest_distance_m(LAT, LON, {"rings": [outer, hole]})
    assert d == pytest.approx(100, abs=2)


def test_footprint_overlap_catches_corner_polygon():
    """Inside the square footprint but outside its inscribed circle."""
    geom = esri_square(LAT, LON, 450, 450, 20)
    assert geodata.nearest_distance_m(LAT, LON, geom) > 500  # old half-width test missed it
    assert geodata.footprint_overlaps(LAT, LON, 500, geom)


def test_footprint_overlap_false_when_outside():
    assert not geodata.footprint_overlaps(LAT, LON, 500, esri_square(LAT, LON, 700, 0, 50))


def test_footprint_overlap_when_polygon_encloses_footprint():
    assert geodata.footprint_overlaps(LAT, LON, 500, esri_square(LAT, LON, 0, 0, 5000))


def test_footprint_overlap_edge_crossing_without_vertices_inside():
    """A long thin strip (e.g. a stream) crossing the footprint."""
    kx = geodata._m_per_deg_lon(LAT)
    ring = [
        [LON - 2000 / kx, LAT - 10 / 111_320], [LON + 2000 / kx, LAT - 10 / 111_320],
        [LON + 2000 / kx, LAT + 10 / 111_320], [LON - 2000 / kx, LAT + 10 / 111_320],
        [LON - 2000 / kx, LAT - 10 / 111_320],
    ]
    assert geodata.footprint_overlaps(LAT, LON, 500, {"rings": [ring]})


def test_esri_multipart_becomes_multipolygon():
    """Two clockwise outer rings must not be rendered as a polygon + hole."""
    a = list(reversed(esri_square(LAT, LON, -300, 0, 50)["rings"][0]))  # clockwise = esri outer
    b = list(reversed(esri_square(LAT, LON, 300, 0, 50)["rings"][0]))
    gj = geodata._to_geojson({"rings": [a, b]})
    assert gj["type"] == "MultiPolygon"
    assert len(gj["coordinates"]) == 2

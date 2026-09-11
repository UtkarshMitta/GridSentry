"""Land Status Gate: ownership (PAD-US) + buildability (NLCD) + coverage."""
from __future__ import annotations


import land_status
from conftest import jur


# Real PAD-US attributes returned for these points (recorded 2026-09).
OKEFENOKEE = [
    {"attributes": {"Own_Type": "FED", "Mang_Name": "FWS", "Mang_Type": "FED", "Des_Tp": "NWR",
                    "Loc_Ds": "NWR", "Unit_Nm": "Okefenokee National Wildlife Refuge", "GAP_Sts": "1"}},
    {"attributes": {"Own_Type": "DESG", "Mang_Name": "FWS", "Mang_Type": "FED", "Des_Tp": "WA",
                    "Loc_Ds": "WILDERNESS AREA", "Unit_Nm": "Okefenokee National Wildlife Refuge.Wilderness Area",
                    "GAP_Sts": "1"}},
]
GRAND_CANYON = [
    {"attributes": {"Own_Type": "FED", "Mang_Name": "NPS", "Mang_Type": "FED", "Des_Tp": "NP",
                    "Loc_Ds": "National Park", "Unit_Nm": "Grand Canyon National Park", "GAP_Sts": "1"}},
    {"attributes": {"Own_Type": "DESG", "Mang_Name": "NPS", "Mang_Type": "FED", "Des_Tp": "WSA",
                    "Loc_Ds": "Proposed", "Unit_Nm": "Grand Canyon Proposed or Recommended Wilderness Area",
                    "GAP_Sts": "2"}},
]


def stub(monkeypatch, padus, cover):
    async def q(lat, lon):
        return padus

    async def c(lat, lon, acreage):
        return cover

    monkeypatch.setattr(land_status, "_query_padus", q)
    monkeypatch.setattr(land_status, "_sample_footprint_cover", c)


async def test_national_park_wins_over_wilderness_study(monkeypatch):
    stub(monkeypatch, GRAND_CANYON, [42] * 25)
    s = await land_status.check(36.212, -111.9781, 300)
    assert not s.developable and s.category == "federal_protected"
    assert s.designation_code == "NP" and s.unit_name == "Grand Canyon National Park"


async def test_refuge_wilderness_keeps_designation_code(monkeypatch):
    stub(monkeypatch, OKEFENOKEE, [90] * 25)
    s = await land_status.check(30.8, -82.3, 300)
    assert s.category == "federal_protected"
    assert s.designation_code == "WA" and s.manager_code == "FWS"


async def test_dense_urban_core_trips(monkeypatch):
    stub(monkeypatch, [], [24] * 20 + [23] * 5)
    s = await land_status.check(40.7426, -73.9898, 300)
    assert s.category == "urban_built" and s.verified and s.high_intensity_fraction == 1.0


async def test_open_water_trips(monkeypatch):
    stub(monkeypatch, [], [11] * 20 + [95] * 5)
    s = await land_status.check(43.5, -87.0, 300)
    assert s.category == "open_water"


async def test_farmland_is_developable(monkeypatch):
    stub(monkeypatch, [], [82] * 18 + [43] * 7)
    s = await land_status.check(42.9, -74.3, 300)
    assert s.developable and s.dominant_cover == "Cultivated Crops"


async def test_offline_urban_fallback(monkeypatch):
    stub(monkeypatch, None, None)
    s = await land_status.check(40.7426, -73.9898, 300)
    assert s.category == "urban_built" and not s.verified


def test_outside_coverage_status():
    s = land_status.outside_coverage(jur(state=None, code=None, verified=False, in_coverage=False))
    assert not s.developable and s.category == "outside_coverage"

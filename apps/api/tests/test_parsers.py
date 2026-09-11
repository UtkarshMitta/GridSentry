"""Parsers for each live federal service, fed recorded / trimmed real payloads."""
from __future__ import annotations

import copy

import httpx
import pytest
import respx

import geodata
import land_status
from conftest import LAT, LON, esri_square, load_fixture



# --- IPaC -------------------------------------------------------------------

async def _species(payload, lat=38.47, lon=-98.66):
    with respx.mock:
        respx.post(geodata.IPAC_URL).mock(return_value=httpx.Response(200, json=payload))
        async with httpx.AsyncClient() as client:
            return await geodata._fetch_species(client, lat, lon, 400)


async def test_ipac_designated_critical_habitat_is_detected():
    """Recorded response for Cheyenne Bottoms, KS (whooping crane critical habitat)."""
    habs = {h.common_name: h for h in await _species(load_fixture("ipac_cheyenne_bottoms.json"))}
    assert habs["Whooping crane"].basis == "critical_habitat"
    assert habs["Piping Plover"].basis == "ipac_species_list"
    assert habs["Monarch butterfly"].currently_listed is False  # proposed threatened


async def test_ipac_proposed_critical_habitat_is_distinguished():
    payload = copy.deepcopy(load_fixture("ipac_cheyenne_bottoms.json"))
    for ch in payload["resources"]["crithabs"]:
        ch["type"] = "Proposed"
    habs = {h.common_name: h for h in await _species(payload)}
    assert habs["Whooping crane"].basis == "proposed_critical_habitat"


async def test_ipac_nonessential_experimental_population_not_treated_as_listed():
    """ESA §10(j): NEP populations are treated as proposed for §7 purposes."""
    habs = await _species(load_fixture("ipac_fairbanks.json"), 64.84, -147.72)
    bison = next(h for h in habs if h.common_name == "Wood Bison")
    assert bison.currently_listed is False


async def test_ipac_failure_returns_none():
    with respx.mock:
        respx.post(geodata.IPAC_URL).mock(return_value=httpx.Response(503))
        async with httpx.AsyncClient() as client:
            assert await geodata._fetch_species(client, LAT, LON, 400) is None


# --- FEMA NFHL --------------------------------------------------------------

def _fema_feature(zone, subty, geom):
    return {"attributes": {"FLD_ZONE": zone, "ZONE_SUBTY": subty}, "geometry": geom}


async def test_fema_zone_classification():
    inside = esri_square(LAT, LON, 0, 0, 100)
    payload = {"features": [
        _fema_feature("A", None, inside),
        _fema_feature("X", "0.2 PCT ANNUAL CHANCE FLOOD HAZARD", esri_square(LAT, LON, 400, 0, 50)),
        _fema_feature("D", None, esri_square(LAT, LON, -400, 0, 50)),
        _fema_feature("X", "AREA OF MINIMAL FLOOD HAZARD", inside),
        _fema_feature("OPEN WATER", None, inside),
    ]}
    with respx.mock:
        route = respx.get(geodata.FEMA_URL).mock(return_value=httpx.Response(200, json=payload))
        async with httpx.AsyncClient() as client:
            zones = await geodata._fetch_flood(client, LAT, LON, 300)
        assert "maxAllowableOffset" in route.calls[0].request.url.params  # payload generalized
    by_zone = {z.zone: z for z in zones}
    assert set(by_zone) == {"A", "X", "D"}
    assert by_zone["A"].sfha and by_zone["A"].overlaps_footprint
    assert not by_zone["X"].sfha
    assert not by_zone["D"].sfha


# --- PAD-US nearby protected areas ------------------------------------------

async def test_padus_protected_labels_gap_and_overlap():
    payload = {"features": [{
        "attributes": {"Unit_Nm": "Harriman State Park", "Des_Tp": "SP", "Loc_Ds": "State Park",
                       "Mang_Name": "SPR", "Mang_Type": "STAT", "GAP_Sts": "2"},
        "geometry": esri_square(LAT, LON, 0, 0, 2000),
    }, {
        "attributes": {"Unit_Nm": "OCS Block", "Des_Tp": "OCS", "Loc_Ds": None,
                       "Mang_Name": "BOEM", "Mang_Type": "FED", "GAP_Sts": "4"},
        "geometry": esri_square(LAT, LON, 3000, 0, 100),
    }]}
    with respx.mock:
        respx.get(geodata.PADUS_URL).mock(return_value=httpx.Response(200, json=payload))
        async with httpx.AsyncClient() as client:
            lands = {p.name: p for p in await geodata._fetch_protected(client, LAT, LON, 300)}
    park = lands["Harriman State Park"]
    assert park.overlaps_footprint and park.gap_status == "2"
    assert park.manager != "SPR"  # human-readable, not the raw PAD-US code
    ocs = lands["OCS Block"]
    assert ocs.designation != "OCS" and not ocs.overlaps_footprint


# --- NWI state-wetland flag ---------------------------------------------------

@pytest.mark.parametrize(
    "state, acres, cls, expected",
    [
        ("NY", 15, "PEM1E", True),
        ("NY", 15, "PFO1A", True),
        ("NY", 5, "PEM1E", False),     # under the ECL Art. 24 size threshold
        ("NY", 15, "R4SBC", False),    # riverine streambed is not a freshwater wetland
        ("NY", 40, "L1UBHh", False),   # a lake is not a freshwater wetland
        ("NJ", 1, "PSS1C", True),
        ("NJ", 1, "R2UBH", False),
        (None, 50, "PEM1E", False),    # jurisdiction unknown/unverified → no state claim
    ],
)
def test_wetland_state_flag(state, acres, cls, expected):
    flagged, _ = geodata._wetland_state_class(state, acres, cls)
    assert flagged is expected


async def test_nwi_live_wetlands_carry_live_provenance_label():
    payload = {"features": [{
        "attributes": {"Wetlands.ATTRIBUTE": "PEM1E", "Wetlands.WETLAND_TYPE": "Freshwater Emergent Wetland",
                       "Wetlands.ACRES": 20.0},
        "geometry": esri_square(LAT, LON, 0, 0, 50),
    }]}
    with respx.mock:
        respx.get(geodata.NWI_URL).mock(return_value=httpx.Response(200, json=payload))
        async with httpx.AsyncClient() as client:
            [w] = await geodata._fetch_wetlands(client, LAT, LON, 300, "NY")
    assert "live" in w.source
    assert w.crosses_footprint and w.state_protected


# --- NLCD ---------------------------------------------------------------------

@pytest.mark.parametrize("palette, expected", [(82, 82), (0, None), (250, None)])
async def test_nlcd_nodata_is_not_a_land_cover_class(palette, expected):
    body = {"type": "FeatureCollection", "features": [{"properties": {"PALETTE_INDEX": palette}}]}
    with respx.mock:
        respx.get(land_status.NLCD_WMS_URL).mock(return_value=httpx.Response(200, json=body))
        async with httpx.AsyncClient() as client:
            assert await land_status._nlcd_point(client, LAT, LON) == expected


# --- layer deadline -------------------------------------------------------------

async def test_slow_layer_is_marked_unavailable(monkeypatch):
    """httpx timeouts are per-read; a trickling server must not stall a run."""
    import asyncio

    async def slow(*_a, **_k):
        await asyncio.sleep(5)
        return []

    async def fast(*_a, **_k):
        return []

    monkeypatch.setattr(geodata, "LAYER_DEADLINE", 0.05)
    monkeypatch.setattr(geodata, "_fetch_wetlands", slow)
    monkeypatch.setattr(geodata, "_fetch_species", fast)
    monkeypatch.setattr(geodata, "_fetch_flood", fast)
    monkeypatch.setattr(geodata, "_fetch_protected", fast)
    data = await geodata.fetch_all(LAT, LON, 300, "NY")
    assert data["provenance"]["wetlands"] == "unavailable"
    assert data["provenance"]["species"] == "live"

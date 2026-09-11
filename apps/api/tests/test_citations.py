"""Citation knowledge-base integrity."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import land_status
from agents import critic, legal

API = Path(__file__).resolve().parents[1]


def test_every_referenced_citation_id_exists():
    """Scan agent source for citation ids used in citation_ids/cite(...) lists."""
    src = (API / "agents" / "legal.py").read_text() + (API / "agents" / "critic.py").read_text()
    ids = set()
    for block in re.findall(r"citation_ids=\[([^\]]*)\]", src) + re.findall(r"cite\(([^)]*)\)", src):
        ids |= set(re.findall(r'"([a-z0-9]+(?:-[a-z0-9]+)+)"', block))
    for cites in list(legal.STATE_WETLAND_CITES.values()) + [legal.GENERIC_WETLAND_CITES]:
        ids |= set(cites)
    for code in land_status.BARRED_DESIGNATIONS:
        for mgr in ("NPS", "FWS", "BLM", "USFS", None):
            ids |= set(legal.federal_cites(code, mgr))
    missing = ids - set(legal.CITATIONS)
    assert not missing, f"undefined citation ids: {missing}"


def test_no_rescinded_or_nonexistent_authorities():
    # CEQ's NEPA regulations (40 CFR 1500-1508) were removed effective 2025-04-11;
    # 54 U.S.C. § 101905 does not exist.
    for c in legal.CITATIONS.values():
        assert "1501" not in c.label and "part-1501" not in c.url, c.id
        assert "101905" not in c.label + c.url, c.id
        assert c.url.startswith("https://"), c.id
        assert "nj.gov/dep/landuse/fww.html" not in c.url, c.id


def test_no_rescinded_cfr_in_generated_prose():
    src = (API / "agents" / "legal.py").read_text()
    assert "1501.3" not in src and "1501.4" not in src


@pytest.mark.parametrize(
    "code, manager, must, must_not",
    [
        ("NP", "NPS", {"nps-organic", "nps-100902"}, set()),
        ("WA", "FWS", {"wilderness-act", "nwrs-improvement"}, {"nps-organic"}),
        ("WA", "USFS", {"wilderness-act"}, {"nps-organic", "nwrs-improvement"}),
        ("NWR", "FWS", {"nwrs-improvement"}, {"nps-organic"}),
        ("NM", "BLM", {"antiquities", "flpma"}, {"nps-organic"}),
        ("NM", "NPS", {"antiquities", "nps-organic"}, {"flpma"}),
    ],
)
def test_federal_cites_match_managing_agency(code, manager, must, must_not):
    got = set(legal.federal_cites(code, manager))
    assert must <= got and not (must_not & got)


def test_critic_vegetated_helper_shared_with_legal():
    assert critic.is_vegetated_wetland("PEM1E") and not critic.is_vegetated_wetland("PUBHx")

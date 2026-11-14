"""Luna Multiplayer status parsing and failure behaviour (no live KSP server)."""

from __future__ import annotations

from beacon.services import luna


def test_luna_payload_parses_players_vessels_and_settings():
    payload = [
        {
            "CurrentState": {
                "CurrentPlayers": [
                    {"Username": "Dorbldoo"},
                    {"Name": "ecoeric"},
                ],
                "CurrentVessels": [{"VesselName": "A"}, {"VesselName": "B"}],
                "BytesUsed": 151982080,
            },
            "GeneralSettings": {
                "ServerName": "Eric's Kerbin Station",
                "Description": "Stock KSP",
                "GameMode": "Sandbox",
                "MaxPlayers": 10,
                "HasPassword": True,
                "ModControl": False,
            },
            "WarpSettings": {"WarpMode": "Subspace"},
        }
    ]
    parsed = luna._parse_payload(payload)
    assert parsed["server_name"] == "Eric's Kerbin Station"
    assert parsed["players"] == ["Dorbldoo", "ecoeric"]
    assert parsed["vessels"] == 2
    assert parsed["players_max"] == 10
    assert parsed["has_password"] is True
    assert parsed["mod_control"] is False
    assert parsed["warp_mode"] == "Subspace"
    assert parsed["server_memory_bytes"] == 151982080


def test_luna_status_unavailable_is_structured(env):
    result = luna.status(env)
    assert result.available is False
    assert result.online is False
    assert result.state in {"stopped", "process-only"}
    assert result.error

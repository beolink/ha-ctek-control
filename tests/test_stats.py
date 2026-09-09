"""What the anonymous daily report may contain (stats_extra.py).

Runs standalone, no Home Assistant and no pytest needed:

    python3 tests/test_stats.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "custom_components", "ctek_ccu"))

import stats_extra  # noqa: E402


def _extra(**kw):
    args = {"connectors": 1, "max_current_a": 16, "control_enabled": True,
            "charging_allowed": True, "backend_connected": True,
            "nanogrid": False, "rfid": None, "had_error": False}
    args.update(kw)
    return stats_extra.build_extra(**args)


def test_report_holds_only_the_agreed_keys():
    extra = _extra()
    assert set(extra) == {"models", "features", "metrics", "errors"}
    assert extra["models"] == ["ctek_ccu"]
    assert set(extra["features"]) == {"control", "charging_allowed", "backend",
                                      "nanogrid", "rfid"}


def test_rating_is_reported_not_consumption():
    extra = _extra(max_current_a=32, connectors=2)
    assert extra["metrics"] == {"charger_a": 32, "connectors": 2}
    # Charged energy and session counts are deliberately absent.
    assert not any(k.endswith("_kwh_day") for k in extra["metrics"])


def test_firmware_shapes_of_yes_are_all_understood():
    for yes in (True, 1, "true", "YES", "connected", "on"):
        assert _extra(nanogrid=yes)["features"]["nanogrid"] is True
    for no in (False, 0, "false", "no", "", None, "disconnected"):
        assert _extra(nanogrid=no)["features"]["nanogrid"] is False


def test_a_serial_shaped_string_is_not_mistaken_for_a_yes():
    assert _extra(rfid="CCU-1234567")["features"]["rfid"] is False


def test_features_are_booleans_and_metrics_are_numbers():
    extra = _extra()
    for value in extra["features"].values():
        assert isinstance(value, bool)
    for value in extra["metrics"].values():
        assert isinstance(value, (int, float)) and not isinstance(value, bool)


def test_an_unconfigured_rating_is_left_out_rather_than_sent_as_zero():
    assert _extra(max_current_a=0, connectors=0)["metrics"] == {}


def test_firmware_is_reported_when_it_looks_like_a_version():
    assert _extra(firmware="2.1.4")["firmware"] == "2.1.4"
    assert _extra(firmware="v2.1.4")["firmware"] == "2.1.4"
    assert _extra(firmware="R1.4.7")["firmware"] == "R1.4.7"


def test_anything_that_is_not_a_version_is_left_out():
    # Samma API svarar med serienumret, och en förväxling där får inte bli
    # ett flottregister.
    for junk in (None, "", "Laddaren i garaget", "CCU nr 3 hos Andreas", True, {}):
        assert "firmware" not in _extra(firmware=junk)


def test_a_failed_write_is_counted_never_its_message():
    assert _extra(had_error=True)["errors"] == 1
    assert _extra(had_error=False)["errors"] == 0


if __name__ == "__main__":
    test_report_holds_only_the_agreed_keys()
    test_rating_is_reported_not_consumption()
    test_firmware_shapes_of_yes_are_all_understood()
    test_a_serial_shaped_string_is_not_mistaken_for_a_yes()
    test_features_are_booleans_and_metrics_are_numbers()
    test_an_unconfigured_rating_is_left_out_rather_than_sent_as_zero()
    test_firmware_is_reported_when_it_looks_like_a_version()
    test_anything_that_is_not_a_version_is_left_out()
    test_a_failed_write_is_counted_never_its_message()
    print("All statistics tests passed.")

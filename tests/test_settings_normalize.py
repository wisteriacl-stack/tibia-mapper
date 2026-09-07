"""Prueba solo settings_store._normalize_settings(), una funcion pura sin I/O.

Deliberadamente NO se llaman get_settings()/save_settings()/update_settings():
settings_store.SETTINGS_PATH apunta al settings.json real del proyecto (no hay
override de ruta para tests), y estas funciones leen/escriben ese archivo.
"""

from settings_store import DEFAULT_SETTINGS, _normalize_settings


def test_out_of_range_values_are_clamped():
    result = _normalize_settings({"validation_similarity_threshold": 5.0})
    assert result["validation_similarity_threshold"] == 1.0

    result = _normalize_settings({"validation_similarity_threshold": -3.0})
    assert result["validation_similarity_threshold"] == 0.0


def test_missing_keys_take_default_value():
    result = _normalize_settings({})
    assert result["battle_similarity_threshold"] == DEFAULT_SETTINGS["battle_similarity_threshold"]
    assert result["tibia_window_title"] == DEFAULT_SETTINGS["tibia_window_title"]
    assert result["health_monitor_enabled"] == DEFAULT_SETTINGS["health_monitor_enabled"]


def test_none_data_uses_all_defaults():
    result = _normalize_settings(None)
    assert result["battle_poll_seconds"] == DEFAULT_SETTINGS["battle_poll_seconds"]


def test_regions_normalize_width_height_to_minimum_one():
    result = _normalize_settings({
        "battle_event_region": {"x": 10, "y": 20, "width": 0, "height": -5},
    })
    region = result["battle_event_region"]
    assert region["width"] == 1
    assert region["height"] == 1
    assert region["x"] == 10
    assert region["y"] == 20


def test_dxgi_output_idx_never_negative():
    result = _normalize_settings({"dxgi_output_idx": -1})
    assert result["dxgi_output_idx"] == 0


def test_validation_failure_continues_defaults_to_false():
    result = _normalize_settings({})
    assert result["validation_failure_continues"] is False


def test_capture_backend_defaults_to_dxgi_and_rejects_unknown_values():
    assert _normalize_settings({})["capture_backend"] == "dxgi"
    assert _normalize_settings({"capture_backend": "obs_camera"})["capture_backend"] == "obs_camera"
    assert _normalize_settings({"capture_backend": "algo_invalido"})["capture_backend"] == "dxgi"


def test_obs_ws_password_defaults_to_empty_string():
    result = _normalize_settings({})
    assert result["obs_ws_password"] == ""
    assert result["obs_ws_host"] == "localhost"
    assert result["obs_ws_port"] == 4455

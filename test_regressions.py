"""Focused regression tests for previously identified runtime failures."""

import requests

import fetch_project_pluto_test_data
import neocp_explorer


def test_app_version_matches_patch_release():
    assert neocp_explorer.APP_VERSION == "3.1.1"


def test_service_get_identifies_app_and_retries_temporary_failure(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.headers = {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(str(self.status_code))

    calls = []
    responses = [FakeResponse(503), FakeResponse(200)]

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return responses.pop(0)

    monkeypatch.setattr(neocp_explorer.requests, "get", fake_get)
    monkeypatch.setattr(neocp_explorer.time, "sleep", lambda _seconds: None)

    response = neocp_explorer._service_get(
        "https://example.invalid/service",
        timeout=10,
    )

    assert response.status_code == 200
    assert len(calls) == 2
    assert calls[0][1]["headers"] == neocp_explorer.HTTP_HEADERS


class _FakeRoot:
    def __init__(self):
        self.callbacks = []

    def after(self, _delay, callback, *args):
        self.callbacks.append((callback, args))

    def run_callbacks(self):
        for callback, args in self.callbacks:
            callback(*args)


def test_compact_elements_support_negative_semi_major_axis():
    compact = neocp_explorer.extract_compact_orbital_elements(
        "a -1.234\n"
        "e 1.200\n"
        "Incl. 3.0\n"
    )

    assert "a        : -1.234 AU" in compact


def test_fixture_generator_uses_production_element_center():
    assert fetch_project_pluto_test_data.BASE_PARAMS["element_center"] == 0


def test_neocp_request_error_survives_deferred_callback(monkeypatch):
    class DummyApp:
        def __init__(self):
            self.root = _FakeRoot()
            self.error_message = None

        def _neocp_load_error(self, message):
            self.error_message = message

    def fail_request(*_args, **_kwargs):
        raise requests.exceptions.ConnectTimeout("MPC unavailable")

    app = DummyApp()
    monkeypatch.setattr(neocp_explorer.requests, "get", fail_request)

    neocp_explorer.NEOTrackerApp._fetch_neocp_data(app)
    app.root.run_callbacks()

    assert app.error_message == "MPC unavailable"


def test_cdc_slew_error_survives_deferred_callback(monkeypatch):
    class Entry:
        def get(self):
            return "99942"

    class StatusBar:
        def config(self, **_kwargs):
            pass

    class DummyApp:
        root = _FakeRoot()
        status_bar = StatusBar()
        target_object_entry = Entry()
        target_object_placeholder = "Object designation"

        def _selected_ephemeris_row(self):
            return {
                "RA": "10 00 00",
                "Dec": "-20 00 00",
                "UTC": "2026-07-18 22:00",
                "Alt": "35.0",
            }

        def _selected_ephemeris_altitude(self, row):
            return float(row["Alt"])

    class ImmediateThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()

    errors = []

    def fail_slew(*_args, **_kwargs):
        raise neocp_explorer.CartesDuCielError("CdC unavailable")

    app = DummyApp()
    monkeypatch.setattr(neocp_explorer, "CDC_AVAILABLE", True)
    monkeypatch.setattr(neocp_explorer, "slew_telescope_via_cdc", fail_slew)
    monkeypatch.setattr(neocp_explorer.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(neocp_explorer.messagebox, "askyesno", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        neocp_explorer.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
    )

    neocp_explorer.NEOTrackerApp.slew_selected_ephemeris_via_cdc(app)
    app.root.run_callbacks()

    assert errors == [("Cartes du Ciel slew failed", "CdC unavailable")]


def test_submit_captures_widget_values_before_worker_starts(monkeypatch):
    class Entry:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

    class DummyApp:
        _processing = False
        target_object_entry = Entry("  99942  ")
        obs_code_entry = Entry(" X93 ")
        eph_steps_entry = Entry("3")
        step_size_var = Entry("30m")

        def validate_entries(self):
            return True

        def process_submission(self, *_args):
            raise AssertionError("The fake thread must not execute the worker")

    started = {}

    class FakeThread:
        def __init__(self, *, target, args, daemon):
            started.update(target=target, args=args, daemon=daemon)

        def start(self):
            started["started"] = True

    app = DummyApp()
    monkeypatch.setattr(neocp_explorer.threading, "Thread", FakeThread)

    neocp_explorer.NEOTrackerApp.submit(app)

    assert started["args"] == ("99942", "X93", 3, "30m")
    assert started["daemon"] is True
    assert started["started"] is True
    assert app._processing is True

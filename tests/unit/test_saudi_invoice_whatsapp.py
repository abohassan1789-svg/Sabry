"""Unit tests for the «حفظ وإرسال واتساب» helpers (Saudi + Egyptian aware).

Covers the pure, OS-free parts of the feature: multi-country phone
normalisation, the WhatsApp Desktop deep link, the desktop-open fallback to
WhatsApp Web, and the Ctrl+V keystroke helper. The full save→export→send UI
flow needs a live DB + QtWebEngine and is exercised manually.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import whatsapp_service
from app.services.whatsapp_service import normalize_saudi_or_egyptian_phone


@pytest.mark.parametrize(
    ("raw_phone", "expected"),
    [
        # Saudi local + international forms.
        ("0512345678", "966512345678"),
        ("512345678", "966512345678"),
        ("966512345678", "966512345678"),
        ("+966 51 234 5678", "966512345678"),
        ("00966512345678", "966512345678"),
        # Egyptian local + international forms (auto-detected too).
        ("01012345678", "201012345678"),
        ("1012345678", "201012345678"),
        ("201012345678", "201012345678"),
        ("+20 (10) 1234-5678", "201012345678"),
        # A full foreign number is trusted as-is.
        ("971501234567", "971501234567"),
        # Arabic-Indic numerals are converted to ASCII, not rejected.
        ("٠١٠١٢٣٤٥٦٧٨", "201012345678"),  # ٠١٠١٢٣٤٥٦٧٨
        ("٠٥١٢٣٤٥٦٧٨", "966512345678"),        # ٠٥١٢٣٤٥٦٧٨
        # Invisible BiDi/format characters that ride along on copy-paste
        # (directional isolates/marks, zero-width space) are stripped.
        ("508561398⁩", "966508561398"),          # real DB value: local + POP DIRECTIONAL ISOLATE
        ("⁦+966 51 234 5678⁩", "966512345678"),  # wrapped in a directional isolate (LRI…PDI)
        ("‏0512345678‎", "966512345678"),   # RLM prefix + LRM suffix
        ("0512345678​", "966512345678"),         # trailing zero-width space
    ],
)
def test_normalize_saudi_or_egyptian_phone_accepts_supported_formats(raw_phone, expected):
    assert normalize_saudi_or_egyptian_phone(raw_phone) == expected


@pytest.mark.parametrize(
    "raw_phone",
    [
        None,
        "",
        " +()-[]{} ",
        "‎‏⁩",   # only invisible BiDi characters -> nothing left
        "12345",            # too short to be any mobile
        "0512",             # truncated Saudi
        "05123ABCD9",       # real letters are still invalid
    ],
)
def test_normalize_saudi_or_egyptian_phone_rejects_invalid_numbers(raw_phone):
    with pytest.raises(ValueError):
        normalize_saudi_or_egyptian_phone(raw_phone)


def test_build_whatsapp_desktop_url_uses_scheme_and_encodes_message():
    url = whatsapp_service.build_whatsapp_desktop_url("0512345678")

    assert url == (
        "whatsapp://send?phone=966512345678&"
        "text=%D8%A7%D9%84%D8%B3%D9%84%D8%A7%D9%85%20%D8%B9%D9%84%D9%8A%D9%83%D9%85"
    )


def test_build_whatsapp_web_url_uses_web_host_and_encodes_message():
    url = whatsapp_service.build_whatsapp_web_url("0512345678")

    assert url == (
        "https://web.whatsapp.com/send?phone=966512345678&"
        "text=%D8%A7%D9%84%D8%B3%D9%84%D8%A7%D9%85%20%D8%B9%D9%84%D9%8A%D9%83%D9%85"
    )


def test_open_whatsapp_web_multi_opens_browser_for_saudi_number(monkeypatch):
    opened = []
    monkeypatch.setattr(
        whatsapp_service.webbrowser,
        "open",
        lambda target, new=0: opened.append((target, new)) or True,
    )

    url = whatsapp_service.open_whatsapp_web_multi("0512345678", "مرحبا")

    assert url.startswith("https://web.whatsapp.com/send?phone=966512345678")
    assert opened and opened[0][0] == url


def test_open_whatsapp_web_multi_raises_when_browser_rejects_launch(monkeypatch):
    monkeypatch.setattr(whatsapp_service.webbrowser, "open", lambda *a, **k: False)

    with pytest.raises(RuntimeError, match="WhatsApp Web"):
        whatsapp_service.open_whatsapp_web_multi("0512345678")


def test_open_whatsapp_desktop_launches_protocol(monkeypatch):
    launched = []
    monkeypatch.setattr("os.startfile", lambda target: launched.append(target), raising=False)

    url = whatsapp_service.open_whatsapp_desktop("0512345678", "مرحبا")

    assert url.startswith("whatsapp://send?phone=966512345678")
    assert launched == [url]


def test_open_whatsapp_desktop_falls_back_to_web_when_no_client(monkeypatch):
    def no_handler(target):
        raise OSError("no protocol handler")

    opened = []
    monkeypatch.setattr("os.startfile", no_handler, raising=False)
    monkeypatch.setattr(
        whatsapp_service.webbrowser,
        "open",
        lambda target, new=0: opened.append((target, new)) or True,
    )

    url = whatsapp_service.open_whatsapp_desktop("0512345678")

    assert url.startswith("https://web.whatsapp.com/send?phone=966512345678")
    assert opened and opened[0][0] == url


def test_press_ctrl_v_sends_control_and_v_key_events(monkeypatch):
    events = []
    fake_user32 = SimpleNamespace(keybd_event=lambda *args: events.append(args))
    monkeypatch.setattr(
        whatsapp_service,
        "ctypes",
        SimpleNamespace(windll=SimpleNamespace(user32=fake_user32)),
        raising=False,
    )

    whatsapp_service.press_ctrl_v()

    assert events == [
        (0x11, 0, 0, 0),        # Ctrl down
        (0x56, 0, 0, 0),        # V down
        (0x56, 0, 0x0002, 0),   # V up
        (0x11, 0, 0x0002, 0),   # Ctrl up
    ]


def test_type_digits_sends_a_key_press_per_digit(monkeypatch):
    events = []
    fake_user32 = SimpleNamespace(keybd_event=lambda *args: events.append(args))
    monkeypatch.setattr(
        whatsapp_service,
        "ctypes",
        SimpleNamespace(windll=SimpleNamespace(user32=fake_user32)),
        raising=False,
    )

    whatsapp_service.type_digits("9-6 5")  # only the digits are typed

    assert events == [
        (0x39, 0, 0, 0), (0x39, 0, 0x0002, 0),   # 9
        (0x36, 0, 0, 0), (0x36, 0, 0x0002, 0),   # 6
        (0x35, 0, 0, 0), (0x35, 0, 0x0002, 0),   # 5
    ]


def test_press_escape_sends_escape_key_events(monkeypatch):
    events = []
    fake_user32 = SimpleNamespace(keybd_event=lambda *args: events.append(args))
    monkeypatch.setattr(
        whatsapp_service,
        "ctypes",
        SimpleNamespace(windll=SimpleNamespace(user32=fake_user32)),
        raising=False,
    )

    whatsapp_service.press_escape()

    assert events == [
        (0x1B, 0, 0, 0),
        (0x1B, 0, 0x0002, 0),
    ]


def test_press_whatsapp_web_search_sends_ctrl_alt_slash(monkeypatch):
    events = []
    fake_user32 = SimpleNamespace(keybd_event=lambda *args: events.append(args))
    monkeypatch.setattr(
        whatsapp_service,
        "ctypes",
        SimpleNamespace(windll=SimpleNamespace(user32=fake_user32)),
        raising=False,
    )

    whatsapp_service.press_whatsapp_web_search()

    assert events == [
        (0x11, 0, 0, 0),        # Ctrl down
        (0x12, 0, 0, 0),        # Alt down
        (0xBF, 0, 0, 0),        # / down
        (0xBF, 0, 0x0002, 0),   # / up
        (0x12, 0, 0x0002, 0),   # Alt up
        (0x11, 0, 0x0002, 0),   # Ctrl up
    ]


def test_focus_window_by_title_returns_false_without_keywords():
    # No keywords -> nothing to match, and it must never raise.
    assert whatsapp_service.focus_window_by_title() is False
    assert whatsapp_service.focus_window_by_title("", None) is False


def test_press_ctrl_v_wraps_windows_input_errors(monkeypatch):
    def fail_key_event(*args):
        raise OSError("input unavailable")

    fake_user32 = SimpleNamespace(keybd_event=fail_key_event)
    monkeypatch.setattr(
        whatsapp_service,
        "ctypes",
        SimpleNamespace(windll=SimpleNamespace(user32=fake_user32)),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="Ctrl\\+V"):
        whatsapp_service.press_ctrl_v()

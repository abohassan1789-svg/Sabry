"""Helpers for opening WhatsApp (Web or Desktop) from the CRM."""

from __future__ import annotations

import ctypes
import os
import re
import unicodedata
import webbrowser
from urllib.parse import quote


_FORMATTING_CHARACTERS = re.compile(r"[\s+\-()\[\]{}]")

# Arabic-Indic (٠-٩) and Extended Arabic-Indic / Persian-Urdu (۰-۹) digits
# mapped to their ASCII equivalents, so a number typed or pasted with Arabic
# numerals still resolves to a WhatsApp-dialable ASCII number.
_ARABIC_DIGIT_TRANSLATION = {
    **{0x0660 + i: str(i) for i in range(10)},
    **{0x06F0 + i: str(i) for i in range(10)},
}


def _clean_phone_text(phone: str | None) -> str:
    """Return raw phone text ready for validation.

    Copy-pasting a number from an RTL context (WhatsApp, a browser, a PDF)
    silently drags along invisible Unicode BiDi control characters — most
    commonly the directional isolates ``U+2066``–``U+2069`` and the marks
    ``U+200E``/``U+200F``/``U+061C`` — plus the occasional zero-width space.
    They are not whitespace and survive :data:`_FORMATTING_CHARACTERS`, so the
    later ASCII-digit check would reject an otherwise-valid number. This drops
    every Unicode format character (category ``Cf``) and converts Arabic-Indic
    digits to ASCII first.
    """
    if phone is None:
        return ""
    text = str(phone).translate(_ARABIC_DIGIT_TRANSLATION)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
_INTERNATIONAL_MOBILE = re.compile(r"201[0125][0-9]{8}")
_SAUDI_INTERNATIONAL_MOBILE = re.compile(r"9665[0-9]{8}")
DEFAULT_MESSAGE = "السلام عليكم"
WHATSAPP_WEB_URL = "https://web.whatsapp.com/send"
WHATSAPP_DESKTOP_URL = "whatsapp://send"
_VK_RETURN = 0x0D
_VK_CONTROL = 0x11
_VK_MENU = 0x12        # Alt
_VK_ESCAPE = 0x1B
_VK_V = 0x56
_VK_OEM_2 = 0xBF       # the "/" key (US layout) — WhatsApp Web search shortcut
_KEYEVENTF_KEYUP = 0x0002


def normalize_egyptian_phone(phone: str | None) -> str:
    """Return an Egyptian mobile number in WhatsApp's international format."""
    if phone is None:
        raise ValueError("Phone number is required.")

    compact = _FORMATTING_CHARACTERS.sub("", _clean_phone_text(phone))
    if not compact:
        raise ValueError("Phone number is required.")

    if re.fullmatch(r"01[0125][0-9]{8}", compact):
        compact = f"2{compact}"
    elif re.fullmatch(r"1[0125][0-9]{8}", compact):
        compact = f"20{compact}"

    if not _INTERNATIONAL_MOBILE.fullmatch(compact):
        raise ValueError("Invalid Egyptian mobile number.")
    return compact


def build_whatsapp_url(phone: str | None, message: str = DEFAULT_MESSAGE) -> str:
    """Build a WhatsApp Web URL that prefills, but does not send, a message."""
    normalized_phone = normalize_egyptian_phone(phone)
    encoded_message = quote(message, safe="")
    return f"{WHATSAPP_WEB_URL}?phone={normalized_phone}&text={encoded_message}"


def open_whatsapp_web(phone: str | None, message: str = DEFAULT_MESSAGE) -> str:
    """Open WhatsApp Web in the default browser and return the opened URL."""
    url = build_whatsapp_url(phone, message)
    try:
        opened = webbrowser.open(url, new=2)
    except Exception as exc:
        raise RuntimeError("Unable to open WhatsApp Web in the default browser.") from exc
    if not opened:
        raise RuntimeError("Unable to open WhatsApp Web in the default browser.")
    return url


def press_enter_key() -> None:
    """Press Enter in the foreground Windows application."""
    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(_VK_RETURN, 0, 0, 0)
        user32.keybd_event(_VK_RETURN, 0, _KEYEVENTF_KEYUP, 0)
    except Exception as exc:
        raise RuntimeError("Unable to press the Enter key.") from exc


def press_ctrl_v() -> None:
    """Send Ctrl+V to the foreground Windows application.

    Used to paste a file that was placed on the clipboard (Explorer-style) into
    the focused WhatsApp chat, which attaches it as a document/media.
    """
    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(_VK_CONTROL, 0, 0, 0)
        user32.keybd_event(_VK_V, 0, 0, 0)
        user32.keybd_event(_VK_V, 0, _KEYEVENTF_KEYUP, 0)
        user32.keybd_event(_VK_CONTROL, 0, _KEYEVENTF_KEYUP, 0)
    except Exception as exc:
        raise RuntimeError("Unable to press Ctrl+V.") from exc


def type_digits(text: str) -> None:
    """Type the ASCII digits in ``text`` into the foreground app as keystrokes.

    Used to fill WhatsApp Web's search box with the customer's number **without
    the clipboard** — pasting text is flaky when the sender app is in the
    background (the clipboard has not propagated yet), whereas key events land
    reliably. Non-digit characters are skipped.
    """
    try:
        user32 = ctypes.windll.user32
        for ch in str(text):
            if "0" <= ch <= "9":
                vk = 0x30 + (ord(ch) - ord("0"))
                user32.keybd_event(vk, 0, 0, 0)
                user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)
    except Exception as exc:
        raise RuntimeError("Unable to type the number.") from exc


def press_escape() -> None:
    """Send Esc to the foreground app (used to reset WhatsApp Web to the chat list)."""
    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(_VK_ESCAPE, 0, 0, 0)
        user32.keybd_event(_VK_ESCAPE, 0, _KEYEVENTF_KEYUP, 0)
    except Exception as exc:
        raise RuntimeError("Unable to press Esc.") from exc


def press_whatsapp_web_search() -> None:
    """Send Ctrl+Alt+/ — WhatsApp Web's shortcut to focus the chat-search box.

    Lets us reuse an already-open WhatsApp Web tab: focus search, type the
    customer's number, open the existing chat — no page reload, no new tab.
    """
    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(_VK_CONTROL, 0, 0, 0)
        user32.keybd_event(_VK_MENU, 0, 0, 0)
        user32.keybd_event(_VK_OEM_2, 0, 0, 0)
        user32.keybd_event(_VK_OEM_2, 0, _KEYEVENTF_KEYUP, 0)
        user32.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, 0)
        user32.keybd_event(_VK_CONTROL, 0, _KEYEVENTF_KEYUP, 0)
    except Exception as exc:
        raise RuntimeError("Unable to open WhatsApp Web search.") from exc


def focus_window_by_title(*keywords: str) -> bool:
    """Bring the first visible top-level window whose title contains any keyword
    (case-insensitive) to the foreground. Windows-only; returns whether a
    matching window was found and focused. Never raises."""
    keys = tuple(k.lower() for k in keywords if k)
    if not keys:
        return False
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found: dict[str, int] = {}

        proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.lower()
            if any(key in title for key in keys):
                found["hwnd"] = hwnd
                return False  # stop enumerating
            return True

        user32.EnumWindows(proc_type(_callback), 0)
        hwnd = found.get("hwnd")
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE (un-minimise if needed)
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception:  # noqa: BLE001 — best-effort; caller falls back to opening a URL
        return False


def focus_whatsapp_web_window() -> bool:
    """Foreground an already-open WhatsApp Web browser window (its active tab must
    be WhatsApp). Returns whether one was found and focused."""
    return focus_window_by_title("whatsapp", "واتساب")


def normalize_saudi_or_egyptian_phone(phone: str | None) -> str:
    """Return a mobile number in WhatsApp's international format (digits only).

    Auto-detects Saudi and Egyptian numbers and accepts numbers that are already
    in international form:

    * Saudi local ``05XXXXXXXX`` / ``5XXXXXXXX``  -> ``9665XXXXXXXX``
    * Saudi international ``9665XXXXXXXX``         -> unchanged
    * Egyptian local ``01[0125]XXXXXXXX`` / ``1[0125]XXXXXXXX`` -> ``20…``
    * Egyptian international ``201[0125]XXXXXXXX`` -> unchanged
    * Any other already-international number (11–15 digits) is trusted as-is,
      so a customer saved with a full foreign number still works.

    A leading ``+`` or ``00`` international prefix and spaces / dashes / brackets
    are stripped first; Arabic-Indic numerals are converted to ASCII and invisible
    Unicode BiDi/format characters (copy-paste artefacts) are removed via
    :func:`_clean_phone_text`. Raises :class:`ValueError` for empty or unusable input.
    """
    if phone is None:
        raise ValueError("Phone number is required.")

    compact = _FORMATTING_CHARACTERS.sub("", _clean_phone_text(phone))
    if compact.startswith("00"):
        compact = compact[2:]
    if not compact:
        raise ValueError("Phone number is required.")
    # ASCII digits only. ``_clean_phone_text`` has already converted Arabic-Indic
    # numerals to ASCII and stripped invisible BiDi/format characters, so anything
    # left that is not a digit (e.g. real letters) is a genuinely invalid number.
    if not re.fullmatch(r"[0-9]+", compact):
        raise ValueError("Invalid mobile number.")

    # Already international.
    if _SAUDI_INTERNATIONAL_MOBILE.fullmatch(compact):
        return compact
    if _INTERNATIONAL_MOBILE.fullmatch(compact):
        return compact

    # Saudi local forms.
    if re.fullmatch(r"05[0-9]{8}", compact):
        return "966" + compact[1:]
    if re.fullmatch(r"5[0-9]{8}", compact):
        return "966" + compact

    # Egyptian local forms.
    if re.fullmatch(r"01[0125][0-9]{8}", compact):
        return "2" + compact
    if re.fullmatch(r"1[0125][0-9]{8}", compact):
        return "20" + compact

    # Some other, already-complete international number — trust it.
    if 11 <= len(compact) <= 15:
        return compact

    raise ValueError("Invalid mobile number.")


def build_whatsapp_desktop_url(phone: str | None, message: str = DEFAULT_MESSAGE) -> str:
    """Build a ``whatsapp://send`` deep link (opens the WhatsApp Desktop client)."""
    normalized_phone = normalize_saudi_or_egyptian_phone(phone)
    encoded_message = quote(message, safe="")
    return f"{WHATSAPP_DESKTOP_URL}?phone={normalized_phone}&text={encoded_message}"


def build_whatsapp_web_url(phone: str | None, message: str = DEFAULT_MESSAGE) -> str:
    """Build a WhatsApp Web ``send`` URL (Saudi + Egyptian aware).

    The Saudi/Egyptian twin of :func:`build_whatsapp_url` (which is Egyptian
    only, kept for the customers screen).
    """
    normalized_phone = normalize_saudi_or_egyptian_phone(phone)
    encoded_message = quote(message, safe="")
    return f"{WHATSAPP_WEB_URL}?phone={normalized_phone}&text={encoded_message}"


def open_whatsapp_web_multi(phone: str | None, message: str = DEFAULT_MESSAGE) -> str:
    """Open the customer's chat in WhatsApp Web (default browser) and return the URL.

    Saudi + Egyptian aware. Raises :class:`RuntimeError` if the browser cannot
    be launched.
    """
    url = build_whatsapp_web_url(phone, message)
    try:
        opened = webbrowser.open(url, new=2)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Unable to open WhatsApp Web in the default browser.") from exc
    if not opened:
        raise RuntimeError("Unable to open WhatsApp Web in the default browser.")
    return url


def open_whatsapp_desktop(phone: str | None, message: str = DEFAULT_MESSAGE) -> str:
    """Open the customer's chat in the WhatsApp Desktop client and return the URL.

    Falls back to WhatsApp Web in the default browser when no desktop client is
    registered for the ``whatsapp:`` protocol, so the flow still works on a
    machine without the desktop app installed.
    """
    url = build_whatsapp_desktop_url(phone, message)
    try:
        os.startfile(url)  # type: ignore[attr-defined]  # Windows-only protocol launch
    except OSError:
        return open_whatsapp_web_multi(phone, message)
    return url

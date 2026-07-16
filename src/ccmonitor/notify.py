"""Desktop notifications for usage events.

Sound is played via the Windows-only stdlib ``winsound`` (no extra dependency,
and it's already a Windows app). Everything degrades to silence if the sound
can't be played — a missing chime must never break the overlay.
"""

from __future__ import annotations

import threading


def play_reset_sound() -> None:
    """Play a short rising chime for a session reset, off the UI thread.

    We synthesize the tones with ``winsound.Beep`` rather than playing the themed
    ``SystemAsterisk`` sound: that themed event is *silent* when the user's Windows
    sound scheme has it set to "(None)", which is the likely reason the alert
    "wasn't playing". Beep is audible regardless of the sound scheme. Runs on a
    daemon thread because Beep is synchronous (blocks for the tone's duration)."""
    threading.Thread(target=_play_chime, daemon=True).start()


def _play_chime() -> None:
    try:
        import winsound
    except Exception:
        return
    try:
        for freq, dur_ms in ((784, 140), (1047, 220)):  # G5 -> C6, a rising "ta-da"
            winsound.Beep(freq, dur_ms)
    except Exception:
        # Beep can fail on hardware/VMs without a beep device — fall back to the
        # themed system sound as a best effort (may be silent if disabled).
        try:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except Exception:
            pass

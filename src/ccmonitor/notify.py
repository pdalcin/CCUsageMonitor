"""Desktop notifications for usage events.

Sound is played via the Windows-only stdlib ``winsound`` (no extra dependency,
and it's already a Windows app). Everything degrades to silence if the sound
can't be played — a missing chime must never break the overlay.
"""

from __future__ import annotations


def play_reset_sound() -> None:
    """Play a short, pleasant system chime asynchronously (never blocks the UI)."""
    try:
        import winsound

        # SND_ASYNC returns immediately; SND_ALIAS plays the themed system sound.
        winsound.PlaySound(
            "SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC
        )
    except Exception:
        # No winsound (non-Windows), no audio device, or a themed-sound override
        # that fails — a notification chime is best-effort, so swallow it.
        pass

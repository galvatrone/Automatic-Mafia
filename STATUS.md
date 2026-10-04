# Status

## Adversarial Review

Scope: desktop-local two-window boundary, local persistence, camera/game separation.

Checks performed:

- `GameStore` phase sequence: commissioner, result, hidden, mafia.
- `public_view()` removes role-only highlights before the board renders.
- Board cards use `game_status` only for elimination styling; camera `status` is not rendered.
- Camera worker registration error path was fixed for NumPy portrait truth-value handling and guarded per detection result.
- Qt app starts under `QT_QPA_PLATFORM=offscreen` for a bounded smoke run.
- Sequential role onboarding was exercised with mafia group selection, don restriction, single-role steps, civilians, and timer countdown.
- Warning dialogs and Qt palette surfaces were explicitly themed dark; board timer now exposes a 30-second countdown and speaker.
- Closing board is handled as hide-only; closing control stops the worker.

Known limitation:

- A real screenshot run was blocked by the environment's missing/blocked Qt xcb dependencies (`xcb-cursor`).
- Offscreen screenshots were generated for both windows, but they are not evidence of real-screen color/DPI layout.

Repair prompt:

> Inspect `automatic_mafia/ui/qt_app.py` and prove that `BoardWindow.refresh()` cannot receive raw roles, face IDs, confidence, track IDs, or camera status. Then run the app with a real X11/Wayland display and verify both windows at 1366x768 and 1920x1080, including moving the board to a second monitor and closing/reopening it.

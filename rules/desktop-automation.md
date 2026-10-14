---
id: desktop-automation
domain: security
non_standard: true
name: Desktop & GUI Automation Safety
description: Input safety protocols for desktop and game automation — coordinate clamping, window focus verification, closed-loop visual validation, headless display guards. Activate when writing scripts that inject mouse/keyboard inputs, manipulate OS windows, or automate graphical software (PyAutoGUI, xdotool, pynput, pygetwindow, game bots, screen automation, clicking, key injection).
trigger: model_decision
enforcement: advisory
---
# Desktop & GUI Automation Safety

> **Role**: Mechanical safety protocols for scripts that inject mouse/keyboard inputs into external graphical applications. These complement `providence.md §10`'s prohibition on guessing UI controls.

## 1. Window Focus Verification
- **Assert Before Acting**: Before every burst of input injection (mouse moves, key presses), verify the target window is focused using `pygetwindow`, `xdotool getactivewindow`, or equivalent.
- **Abort on Focus Loss**: If the active window does not match the expected target, abort immediately. Never continue injecting inputs into an unknown window.
- **Multi-Monitor Safety**: When calculating coordinates, account for monitor offsets. Verify the target window's monitor before injecting.

## 2. Coordinate Clamping
- **Safe Boundaries**: Clamp all mouse coordinates to `[1, dimension - 2]` to prevent automation library fail-safes (e.g., PyAutoGUI's corner pause, OS hot corners).
- **Resolution Verification**: Before first input, capture and log the target window's actual resolution. Never assume resolution matches development environment.
- **Relative Coordinates**: Prefer window-relative coordinates over absolute screen coordinates. Calculate offsets from the window's top-left corner.
- **Coordinate Grounding**: Pixel bounding boxes, ROI slices, and brightness thresholds must reference existing calibrated constants (e.g., from `config.py`, `hud_reader.py`) or be derived from a fresh screenshot analysis. Fabricating coordinates from memory or assumption is strictly prohibited.

## 3. Closed-Loop State Transitions
- **No Blind Toggles**: Never use open-loop binary toggles (e.g., blind Spacebar for pause/unpause). The agent cannot know the current state without checking.
- **Visual Assertion**: Before issuing any state-changing input, capture a screenshot and verify the current state. After the input, capture another screenshot and verify the transition occurred.
- **Retry with Backoff**: If visual assertion fails after an input, retry with exponential backoff (max 3 attempts). Do not enter infinite retry loops.

## 4. Headless & Display Environment
- **DISPLAY Variable**: When running on Linux, verify `$DISPLAY` is set and points to a valid X11 display before importing GUI libraries.
- **Xvfb Fallback**: For headless environments, configure Xvfb with explicit resolution: `Xvfb :99 -screen 0 1920x1080x24`.
- **Xauthority**: Handle `Xlib.error.XauthError` by checking `$XAUTHORITY` and `~/.Xauthority` existence before attempting X11 connections.

## 5. Testing Integration
- **Mock by Default**: Per `testing.md` Hardware & External System Mocking — tests asserting on `xdotool`, `pygetwindow`, `pyautogui`, or OS window managers must include mock fixtures.
- **No Live GUI in CI**: Never run automation scripts against live displays in CI/CD. Use mocked window managers or recorded screenshots.

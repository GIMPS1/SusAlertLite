# Changelog
All notable changes to SusAlert Lite will be documented in this file.

The format is based on Keep a Changelog, and this project follows semantic-style versioning.

---

## [4.6.11] – 2026-01-27

### Added
- MSBT-style on-screen announcement overlay (transparent, borderless)
- Countdown announcements for upcoming mechanics
- Anchor presets and custom drag positioning for overlay
- In-app banner alerts (NOW and COUNTDOWN modes)
- Demo mode for testing without RuneScape running
- Built-in Help / User Guide window
- Portable ZIP release system

### Changed
- Default MSBT font size set to 30px
- Main window width slightly increased for cleaner layout
- Default banner alerts disabled
- Default banner mode set to COUNTDOWN
- MSBT default position set to lower center of screen
- Improved mechanic naming and rotation order

### Fixed
- Incorrect Croesus mechanic rotation order
- Energy Fungus (MID) button not appearing consistently
- Settings panel resizing bugs
- MSBT overlay positioning issues
- Gear icon not opening settings
- Demo mode start/stop issues
- Various stability issues in monitoring loop

---

## [4.6.0] – 2026-01-25

### Added
- MID (Energy Fungus) mechanic handling
- Bright highlighted “MID cleared” resume button
- Manual timer offset adjustment (+ / - buttons)
- Persistent offset saving to config.json

### Fixed
- Rotation desync due to latency/UI delay
- Encounter state not resetting cleanly

---

## [4.5.0] – 2026-01-24

### Added
- Borderless draggable window
- Always-on-top toggle
- Saved window position between sessions
- Dark themed UI

### Fixed
- App closing unexpectedly after UI changes
- Detection loop crashes

---

## [4.4.0] – 2026-01-23

### Added
- One-time screen region selector for Croesus timer
- Template-based visual detection of encounter start
- Automatic monitoring after setup
- Basic countdown timer and mechanic display
- Sound alert on mechanic trigger

---

## [4.3.0] – Early Prototype

### Added
- Initial proof-of-concept timer watcher
- Simple mechanic rotation tracking

---

## Planned

- Multi-rotation cycle support
- Optional sound variations per mechanic
- Additional visual customisation options
- Performance optimisations

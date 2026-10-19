# Speech Coach HUD Bridge

Speech Coach HUD is a display-only Web plugin. It never calls `gm.audio.*`, so
it never contends with Memo+ (Moments, Encounters, recaps, native captions)
for the glasses microphone.

It connects to an on-device evaluator daemon over a loopback WebSocket
(`ws://127.0.0.1:8765`). The daemon is responsible for sourcing speech text
(for example, by reading MemoMind's own live-caption text through an Android
Accessibility Service) and judging it against the user's stated purpose and
values. When the daemon flags a violation, it sends:

```json
{ "cue": "Back to serving others.", "durationMs": 2500 }
```

The plugin opens a display page, draws the cue text, and closes the page again
after `durationMs`, handing the HUD back to Memo+'s normal display. No audio
permission is declared or required.

## Permissions

- `display` — draw the transient cue.
- `network` — reach the loopback evaluator daemon.

## Build

From `PhoneSDK`:

```sh
node tools/sync-example-sdk.mjs
node tools/build-mmpkg.mjs examples/hud-bridge dist/hud-bridge-1.0.0.mmpkg
```

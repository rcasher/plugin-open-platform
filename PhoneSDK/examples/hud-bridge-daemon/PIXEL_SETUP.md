# Pixel setup walkthrough — Speech Coach HUD

Two independent pieces go on: the **plugin** (installed into the MemoMind app)
and the **daemon** (running in the Pixel's Linux VM).

## Part 1 — Install the hud-bridge plugin into MemoMind

This happens from your Mac, using Desktop Studio, over the same LAN as the Pixel.

1. Open `Studio/macos/gm-plugin-studio-desktop.dmg` (first time only — install it).
2. Launch Desktop Studio, use **Import workspace** in the top toolbar, and
   point it at the `plugin-open-platform` repo root. It auto-discovers
   `PhoneSDK/examples/hud-bridge/manifest.json`.
3. Select the `hud-bridge` plugin in the Web plugin selector — no glasses
   `.gmp` pairing needed, it's display-only.
4. Studio shows a QR code (`mmapp+tcp://<your-mac-lan-ip>:18765`).
5. On the Pixel, open MemoMind's debug/developer install entry point and scan
   that QR. It downloads and sideloads `hud-bridge` as a `.mmpkg` directly —
   you don't need to hand it the pre-built
   `PhoneSDK/dist/hud-bridge-1.0.0.mmpkg`, Studio packages on the fly.

Leave the plugin installed but don't worry about it loading cleanly yet — it
won't have anything to connect to until Part 2 is running.

## Part 2 — Coach daemon on the Pixel itself

Everything here runs in Android 16's built-in Linux Terminal (Debian VM), on
the Pixel, no laptop involved:

```sh
# 1. Open the Linux Terminal app on the Pixel

# 2. Install Ollama and pull the judge model
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:1b
ollama serve &

# 3. Get the daemon code onto the Pixel (easiest: git clone this repo, or copy just the folder)
cd ~
git clone <your-repo-url> plugin-open-platform   # or scp/copy just hud-bridge-daemon/ over
cd plugin-open-platform/PhoneSDK/examples/hud-bridge-daemon

# 4. Install deps and run
pip install -r requirements.txt
python3 coach_daemon.py -v
```

You should see:
```
caption endpoint: http://127.0.0.1:8090/caption
hud-bridge endpoint: ws://127.0.0.1:8765
```

Leave this running. `-v` gives you debug logs so you can watch captions and
cue decisions live.

**Note on networking:** the Linux Terminal VM forwards ports its processes
bind on `127.0.0.1` back to the Pixel host's `localhost` (same mechanism as
ChromeOS Crostini). That's what lets the MemoMind app's WebView (running on
the host OS) reach `ws://127.0.0.1:8765` and `http://127.0.0.1:8090` inside
the VM. If the plugin's "Daemon" status never flips to connected, that
forwarding is the first thing to check — there's no laptop in the loop here,
but you can confirm from inside the VM with `curl 127.0.0.1:8090/caption` and
separately check whether Android's Linux Terminal settings expose a
port-forwarding toggle.

## Part 3 — Wire up a caption source

The daemon doesn't read anything itself — something has to POST MemoMind's
live-caption text to it. Simplest path is MacroDroid:

1. Install MacroDroid on the Pixel.
2. New macro, trigger: **Notification/Accessibility → text changed**, scoped
   to the MemoMind app.
3. Action: **HTTP Request** — POST to `http://127.0.0.1:8090/caption`, JSON
   body `{"text": "<captured text>", "final": false}`.

This needs the MemoMind app's live-caption text to be exposed as a readable
accessibility node — if it isn't yet, that's a MemoMind-side prerequisite,
not a daemon one.

## Part 4 — Tune it to you

Edit `coach_config.json` before your first real run:
- `purpose` and `values` — what you actually want the coach checking against.
- `cooldown_seconds` (default 20s) — raise it if it nags.
- `idle_seconds` (default 1.5s) — how long a caption must sit still before judging.

## Part 5 — Smoke test

With the daemon running and the plugin open in MemoMind:
1. Check the plugin's on-screen status shows **Bridge: connected** and
   **Daemon: connected**.
2. From the Linux Terminal, manually fire a test caption:
   ```sh
   curl -X POST http://127.0.0.1:8090/caption -H "Content-Type: application/json" \
     -d '{"text":"say something that violates your stated values","final":true}'
   ```
3. Watch the daemon log for a judge call and, if it flags a violation,
   confirm the cue actually flashes on the glasses HUD and clears itself
   after `cue_duration_ms`.

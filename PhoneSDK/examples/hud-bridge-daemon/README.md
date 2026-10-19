# Coach Daemon

The evaluation half of the Speech Coach pipeline. Pairs with the
[`hud-bridge`](../hud-bridge) Web plugin. Runs entirely on the Pixel itself —
no laptop, no mic access, so Memo+ keeps the glasses microphone.

```
MemoMind live captions          coach_daemon.py                 hud-bridge plugin
 (Accessibility/MacroDroid) --> POST /caption  --> Ollama   --> ws://127.0.0.1:8765 --> gm.display
        reads on-screen caption text    local llama3.2:1b judges        cue flashed for 2.5s,
        text, no mic access             against purpose/values          then HUD returns to Memo+
```

This is not a PhoneSDK plugin and must not be packaged into a `.mmpkg` — it
runs as a plain Python process, not inside the App's WebView.

## Setup (Pixel, Android 16 Linux Terminal / Debian VM)

1. Open the Linux Terminal app (Android 16's built-in Debian VM).
2. Install Ollama and pull the model:
   ```sh
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull llama3.2:1b
   ollama serve &
   ```
3. Install Python deps and run the daemon:
   ```sh
   cd hud-bridge-daemon
   pip install -r requirements.txt
   python3 coach_daemon.py -v
   ```
4. Edit `coach_config.json` to set your own `purpose` and `values`.

## Caption source contract

Anything that can see MemoMind's live-caption text and issue an HTTP request
can feed the daemon — no code changes needed on this side. Point it at:

```
POST http://127.0.0.1:8080/caption
Content-Type: application/json

{"text": "the latest recognized caption text", "final": false}
```

- Send the **full current caption text** on every update, not a delta — this
  matches how most caption UIs expose text (replacing it as speech
  continues), and how an Accessibility Service reads a text node.
- `final` is optional. Omit it and the daemon evaluates once the text stops
  changing for `idle_seconds` (default 1.5s). Set it to `true` if your
  capture method can detect the utterance actually finished, to evaluate
  sooner.
- A MacroDroid flow: trigger on "Notification/Accessibility text changed"
  for the MemoMind app, action "HTTP Request" (POST, URL above, JSON body
  built from the captured text).

## Tuning

All in `coach_config.json`:

- `purpose` / `values` — what the coach checks speech against.
- `cooldown_seconds` — minimum gap between HUD cues, so it doesn't nag.
- `idle_seconds` — how long a caption must sit still before it's judged settled.
- `cue_duration_ms` — how long the HUD cue stays up (forwarded to hud-bridge).

## Safety

Both servers bind to `127.0.0.1` only — never expose `caption_host`/`ws_host`
to `0.0.0.0` or a LAN address, since neither endpoint authenticates callers.

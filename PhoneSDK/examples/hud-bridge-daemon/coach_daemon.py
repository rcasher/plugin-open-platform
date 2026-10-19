#!/usr/bin/env python3
"""Speech Coach evaluator daemon. Pairs with the hud-bridge Web plugin.

Two loopback-only servers:
  - HTTP  caption_host:caption_port  receives POST /caption from whatever
          is reading MemoMind's live-caption text (see README).
  - WS    ws_host:ws_port            the hud-bridge plugin connects here and
          receives {"cue": ..., "durationMs": ...} messages.

A local Ollama instance judges each settled caption against the configured
purpose/values and the daemon broadcasts a cue when it flags a violation.
"""

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

LOG = logging.getLogger("coach_daemon")

DEFAULT_CONFIG = {
    "purpose": "Stay encouraging and on-topic.",
    "values": [],
    "caption_host": "127.0.0.1",
    "caption_port": 8090,
    "ws_host": "127.0.0.1",
    "ws_port": 8765,
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "llama3.2:1b",
    "idle_seconds": 1.5,
    "cooldown_seconds": 20,
    "cue_duration_ms": 2500,
}

JUDGE_PROMPT = """You are a silent speech coach. The speaker's stated purpose:
{purpose}

The speaker's values, in priority order:
{values}

They just said:
"{text}"

Judge only this utterance against the purpose and values above. Reply with a
single line of JSON and nothing else: {{"violation": true or false, "cue": a
short second-person coaching cue under 8 words, empty string if no violation}}.
"""


class Daemon:
    def __init__(self, config):
        self.config = config
        self.clients = set()
        self.caption_text = ""
        self.caption_version = 0
        self.last_cue_at = float("-inf")  # time.monotonic() can start near 0, so 0.0 would collide
        self.eval_task = None
        self.session = None

    async def handle_caption(self, request):
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON body"}, status=400)
        text = body.get("text")
        if not isinstance(text, str):
            return web.json_response({"error": "text must be a string"}, status=400)
        final = bool(body.get("final", False))
        self.caption_text = text
        self.caption_version += 1
        LOG.debug("caption update (final=%s): %r", final, text)
        if self.eval_task and not self.eval_task.done():
            self.eval_task.cancel()
        self.eval_task = asyncio.ensure_future(
            self._schedule_evaluation(self.caption_version, text, final)
        )
        return web.json_response({"ok": True})

    async def _schedule_evaluation(self, version, text, final):
        delay = 0.05 if final else float(self.config["idle_seconds"])
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if version != self.caption_version:
            return  # superseded by a newer caption before it settled
        await self._evaluate(text)

    async def _evaluate(self, text):
        text = text.strip()
        if len(text) < 3:
            return
        now = time.monotonic()
        cooldown = float(self.config["cooldown_seconds"])
        if now - self.last_cue_at < cooldown:
            LOG.debug("skipping evaluation, cooldown has %.1fs left",
                      cooldown - (now - self.last_cue_at))
            return
        try:
            verdict = await self._judge(text)
        except Exception as error:  # noqa: BLE001 - daemon must survive a bad Ollama reply
            LOG.warning("judge call failed: %s", error)
            return
        if not verdict or not verdict.get("violation"):
            return
        cue = str(verdict.get("cue") or "").strip()
        if not cue:
            return
        self.last_cue_at = now
        await self.broadcast(cue)

    async def _judge(self, text):
        prompt = JUDGE_PROMPT.format(
            purpose=self.config["purpose"],
            values="\n".join(f"- {value}" for value in self.config["values"]) or "- (none stated)",
            text=text,
        )
        payload = {
            "model": self.config["ollama_model"],
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        url = f"{self.config['ollama_url'].rstrip('/')}/api/generate"
        async with self.session.post(url, json=payload) as response:
            response.raise_for_status()
            body = await response.json()
        raw = body.get("response", "")
        return _extract_json_object(raw)

    async def broadcast(self, cue):
        message = json.dumps({"cue": cue, "durationMs": self.config["cue_duration_ms"]})
        LOG.info("cue: %s", cue)
        stale = []
        for client in self.clients:
            try:
                await client.send_str(message)
            except ConnectionResetError:
                stale.append(client)
        for client in stale:
            self.clients.discard(client)

    async def ws_handler(self, request):
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self.clients.add(ws)
        LOG.info("hud-bridge plugin connected (%d total)", len(self.clients))
        try:
            async for message in ws:
                if message.type == WSMsgType.ERROR:
                    LOG.warning("websocket error: %s", ws.exception())
        finally:
            self.clients.discard(ws)
            LOG.info("hud-bridge plugin disconnected (%d total)", len(self.clients))
        return ws


def _extract_json_object(raw):
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None


def load_config(path):
    config = dict(DEFAULT_CONFIG)
    if path.exists():
        config.update(json.loads(path.read_text(encoding="utf-8")))
    return config


async def run(config):
    daemon = Daemon(config)
    daemon.session = ClientSession(timeout=ClientTimeout(total=30))

    caption_app = web.Application()
    caption_app.router.add_post("/caption", daemon.handle_caption)

    ws_app = web.Application()
    ws_app.router.add_get("/", daemon.ws_handler)

    runner_caption = web.AppRunner(caption_app)
    runner_ws = web.AppRunner(ws_app)
    await runner_caption.setup()
    await runner_ws.setup()
    await web.TCPSite(runner_caption, config["caption_host"], config["caption_port"]).start()
    await web.TCPSite(runner_ws, config["ws_host"], config["ws_port"]).start()

    LOG.info("caption endpoint: http://%s:%s/caption", config["caption_host"], config["caption_port"])
    LOG.info("hud-bridge endpoint: ws://%s:%s", config["ws_host"], config["ws_port"])

    try:
        await asyncio.Event().wait()
    finally:
        await runner_caption.cleanup()
        await runner_ws.cleanup()
        await daemon.session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("coach_config.json"),
        help="path to coach_config.json",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    config = load_config(args.config)
    for host_key in ("caption_host", "ws_host"):
        if config[host_key] not in ("127.0.0.1", "localhost", "::1"):
            raise SystemExit(f"{host_key} must stay loopback-only, got {config[host_key]!r}")

    try:
        asyncio.run(run(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

"""Servidor web: interfaz para el telefono, API de biblioteca, subida de videos y websocket de control."""
import asyncio
import json
import logging
import ssl
import threading
from pathlib import Path

from aiohttp import web, WSMsgType

from .library import disk_free_gb

log = logging.getLogger("server")
WEB = Path(__file__).parent / "web"


class Server:
    def __init__(self, cfg, mixer, library, shows):
        self.cfg, self.mixer, self.library, self.shows = cfg, mixer, library, shows
        self.clients = set()
        self.loop = None

    # llamado desde otros hilos (biblioteca)
    def notify_library(self):
        if self.loop:
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.broadcast_library()))

    async def broadcast(self, payload):
        msg = json.dumps(payload)
        for ws in list(self.clients):
            try:
                await ws.send_str(msg)
            except Exception:
                self.clients.discard(ws)

    def notify_usb(self, text):
        if self.loop:
            async def go():
                await self.broadcast({"type": "usb", "text": text})
                await self.broadcast(self.shows.payload())
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(go()))

    async def broadcast_library(self):
        await self.broadcast({"type": "library", "clips": self.library.list(),
                              "free_gb": disk_free_gb(self.cfg.data_dir)})

    # ---------- handlers ----------
    # ---------- PIN ----------
    def _authed(self, request):
        return not self.cfg.pin or request.cookies.get("vpin") == self.cfg.pin

    @web.middleware
    async def guard(self, request, handler):
        p = request.path
        if (p == "/ws" or p.startswith("/api/")) and p not in ("/api/auth", "/api/pin") and not self._authed(request):
            raise web.HTTPUnauthorized(text="PIN")
        return await handler(request)

    async def auth(self, request):
        return web.json_response({"ok": self._authed(request), "pin": bool(self.cfg.pin)})

    async def set_pin(self, request):
        data = await request.json()
        if not self.cfg.pin or str(data.get("pin", "")) == self.cfg.pin:
            r = web.json_response({"ok": True})
            r.set_cookie("vpin", self.cfg.pin, max_age=10 * 365 * 86400, samesite="Strict")
            return r
        await asyncio.sleep(1)  # frena intentos a ciegas
        return web.json_response({"ok": False})

    async def index(self, request):
        return web.FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})

    async def ws(self, request):
        ws = web.WebSocketResponse(heartbeat=10)
        await ws.prepare(request)
        self.clients.add(ws)
        await ws.send_str(json.dumps({"type": "state", **self.mixer.snapshot()}))
        await ws.send_str(json.dumps({"type": "library", "clips": self.library.list(),
                                      "free_gb": disk_free_gb(self.cfg.data_dir)}))
        await ws.send_str(json.dumps(self.shows.payload()))
        usb = getattr(self, "usb", None)
        if usb and usb.status:
            await ws.send_str(json.dumps({"type": "usb", "text": usb.status}))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                    cmd = data.pop("cmd")
                except Exception:
                    continue
                if cmd == "ping":
                    await ws.send_str(json.dumps({"type": "pong", "t": data.get("t")}))
                    continue
                if cmd.startswith("show_"):
                    if cmd == "show_create":
                        data["live"] = self.mixer.live_settings()
                    changed, load = self.shows.apply(cmd, data)
                    if changed:
                        if load:
                            self.mixer.load_live(load)
                            await self.broadcast({"type": "state", **self.mixer.snapshot()})
                        await self.broadcast(self.shows.payload())
                    continue
                if cmd == "cue" and data.get("clip"):
                    data["fx"] = self.library.get_fx(data["clip"])
                if self.mixer.apply(cmd, data):
                    if cmd == "clipfx":
                        snap = self.mixer.snapshot()
                        d = snap["decks"].get(data.get("deck"), {})
                        if d.get("clip"):
                            self.library.set_fx(d["clip"], d["fx"])
                    self.shows.store_live(self.mixer.live_settings())
                    await self.broadcast({"type": "state", **self.mixer.snapshot()})
        finally:
            self.clients.discard(ws)
        return ws

    async def upload(self, request):
        try:
            return await self._upload(request)
        except Exception as e:
            log.exception("fallo la subida")
            return web.json_response({"results": [{"file": "?", "ok": False,
                                                   "error": f"Error del servidor: {type(e).__name__}: {e}"}]})

    async def _upload(self, request):
        reader = await request.multipart()
        results = []
        while True:
            part = await reader.next()
            if part is None:
                break
            if not part.filename:
                continue
            try:
                cid, dest = self.library.new_upload_path(part.filename)
            except ValueError as e:
                results.append({"file": part.filename, "ok": False, "error": str(e)})
                continue
            size, limit = 0, self.cfg.max_upload_mb * 1024 * 1024
            too_big = False
            with open(dest, "wb") as f:
                while True:
                    chunk = await part.read_chunk(1 << 20)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        too_big = True
                        break
                    f.write(chunk)
            if too_big:
                dest.unlink(missing_ok=True)
                results.append({"file": part.filename, "ok": False,
                                "error": f"Supera {self.cfg.max_upload_mb} MB"})
                continue
            try:
                clip = await asyncio.get_running_loop().run_in_executor(
                    None, self.library.add_uploaded, cid, part.filename, dest)
                if self.shows.add_to_active(clip["id"]):
                    await self.broadcast(self.shows.payload())
                results.append({"file": part.filename, "ok": True, "id": clip["id"]})
            except ValueError as e:
                results.append({"file": part.filename, "ok": False, "error": str(e)})
        return web.json_response({"results": results})

    async def delete_clip(self, request):
        cid = request.match_info["cid"]
        ok = self.library.remove(cid)
        if ok and self.shows.remove_clip(cid):
            await self.broadcast(self.shows.payload())
        if ok and self.mixer.apply("clip_removed", {"clip": cid}):
            await self.broadcast({"type": "state", **self.mixer.snapshot()})
        return web.json_response({"ok": ok})

    async def rename_clip(self, request):
        data = await request.json()
        self.library.rename(request.match_info["cid"], str(data.get("name", "")))
        return web.json_response({"ok": True})

    async def library_json(self, request):
        return web.json_response({"clips": self.library.list()})

    async def ticker(self):
        """Estado periodico (beat, progreso del crossfade) para la UI."""
        last = None
        while True:
            await asyncio.sleep(0.2)
            if not self.clients:
                continue
            snap = self.mixer.snapshot()
            key = (snap["beat"], snap["xfade"], snap["fading"])
            if key != last:
                last = key
                await self.broadcast({"type": "state", **snap})

    # ---------- arranque ----------
    def make_app(self):
        app = web.Application(client_max_size=self.cfg.max_upload_mb * 1024 * 1024 + 10_000_000,
                              middlewares=[self.guard])
        app.router.add_get("/", self.index)
        app.router.add_get("/api/auth", self.auth)
        app.router.add_post("/api/pin", self.set_pin)
        app.router.add_get("/ws", self.ws)
        app.router.add_post("/api/upload", self.upload)
        app.router.add_get("/api/library", self.library_json)
        app.router.add_delete("/api/clips/{cid}", self.delete_clip)
        app.router.add_post("/api/clips/{cid}/rename", self.rename_clip)
        app.router.add_static("/static", WEB)
        app.router.add_static("/thumbs", self.cfg.thumbs_dir)
        return app

    def start_in_thread(self):
        ready = threading.Event()

        def run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            runner = web.AppRunner(self.make_app())
            self.loop.run_until_complete(runner.setup())
            sites = [web.TCPSite(runner, "0.0.0.0", self.cfg.http_port)]
            if self.cfg.cert_file and Path(self.cfg.cert_file).exists():
                sslctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                sslctx.load_cert_chain(self.cfg.cert_file, self.cfg.key_file)
                sites.append(web.TCPSite(runner, "0.0.0.0", self.cfg.https_port, ssl_context=sslctx))
            for s in sites:
                self.loop.run_until_complete(s.start())
            log.info("web en http://0.0.0.0:%d%s", self.cfg.http_port,
                     f" y https :{self.cfg.https_port}" if len(sites) > 1 else "")
            self.loop.create_task(self.ticker())
            ready.set()
            self.loop.run_forever()

        threading.Thread(target=run, daemon=True).start()
        ready.wait(10)

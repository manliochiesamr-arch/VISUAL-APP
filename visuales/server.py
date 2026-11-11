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
        # ?v=<fecha del archivo> en app.js y style.css: el telefono nunca se queda con una version vieja
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for f in ("app.js", "style.css"):
            v = int((WEB / f).stat().st_mtime)
            html = html.replace(f"/static/{f}", f"/static/{f}?v={v}")
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-cache"})

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
                if cmd == "audio":  # espectro del mic del telefono (20 por segundo): no se guarda ni se difunde
                    self.mixer.set_audio(data.get("b"))
                    continue
                if cmd == "textclip":  # edicion de un recurso de texto
                    self.library.set_text(data.get("clip"), data)
                    continue
                if cmd == "cue" and self.library.kind(data.get("clip")) == "text":
                    cmd, data = "text_toggle", {"clip": data["clip"]}
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

    async def new_clip(self, request):
        """Crea un solido de color o un texto y lo suma al show activo."""
        data = await request.json()
        try:
            clip = self.library.create(data.get("kind"), data.get("name"), data.get("text"), data.get("fx"))
        except ValueError as e:
            return web.json_response({"ok": False, "error": str(e)})
        if self.shows.add_to_active(clip["id"]):
            await self.broadcast(self.shows.payload())
        return web.json_response({"ok": True, "clip": clip})

    async def rename_clip(self, request):
        data = await request.json()
        self.library.rename(request.match_info["cid"], str(data.get("name", "")))
        return web.json_response({"ok": True})

    # ---------- red (la aplica install/red.sh como root, vigilando estos archivos) ----------
    def _red_info(self):
        import shutil
        import subprocess
        modo = "auto"
        try:
            modo = (self.cfg.data_dir / "red-modo.txt").read_text().strip() or "auto"
        except OSError:
            pass
        info = {"modo": modo, "disponible": bool(shutil.which("nmcli")), "conexion": None, "conocidos": []}
        if not info["disponible"]:
            return info

        def nm(*args):
            try:
                return subprocess.run(["nmcli", "-t", *args], capture_output=True, text=True, timeout=5).stdout
            except Exception:
                return ""
        st = {}
        for line in nm("-f", "GENERAL.STATE,GENERAL.CONNECTION", "dev", "show", "wlan0").splitlines():
            k, _, v = line.partition(":")
            st[k] = v
        if st.get("GENERAL.STATE", "").startswith("100"):
            info["conexion"] = st.get("GENERAL.CONNECTION") or None
        for line in nm("-f", "NAME,TYPE", "con", "show").splitlines():
            name, _, typ = line.rpartition(":")
            if typ == "802-11-wireless" and name != "visuales-ap":
                info["conocidos"].append(name.replace("\\:", ":"))
        return info

    async def red_get(self, request):
        return web.json_response(await asyncio.get_running_loop().run_in_executor(None, self._red_info))

    async def red_set(self, request):
        data = await request.json()
        ssid = str(data.get("ssid") or "").strip()
        if ssid:
            clave = str(data.get("clave") or "")
            if clave and len(clave) < 8:
                return web.json_response({"ok": False, "error": "La clave del wifi tiene que tener 8 caracteres o más"})
            f = self.cfg.data_dir / "red-wifi-nuevo.txt"
            f.write_text(ssid[:32] + "\n" + clave[:63] + "\n")
            f.chmod(0o600)
        if data.get("modo") in ("auto", "visuales", "wifi"):
            (self.cfg.data_dir / "red-modo.txt").write_text(data["modo"] + "\n")
            log.info("modo de red -> %s", data["modo"])
        return web.json_response({"ok": True})

    # ---------- monitor de la placa ----------
    def _sistema(self):
        import os
        import shutil
        import subprocess
        out = dict(getattr(self, "stats", {}) or {})
        try:  # CPU: diferencia contra la consulta anterior
            vals = [int(x) for x in open("/proc/stat").readline().split()[1:]]
            idle, total = vals[3] + vals[4], sum(vals)
            prev = getattr(self, "_cpu_prev", None)
            self._cpu_prev = (idle, total)
            if prev and total > prev[1]:
                out["cpu"] = round(100 * (1 - (idle - prev[0]) / (total - prev[1])))
        except (OSError, ValueError, IndexError):
            pass
        try:
            mem = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
            out["ram_total"] = round(mem["MemTotal"] / 1024)
            out["ram_usada"] = round((mem["MemTotal"] - mem["MemAvailable"]) / 1024)
        except (OSError, KeyError, ValueError):
            pass
        try:
            out["temp"] = round(int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000, 1)
        except (OSError, ValueError):
            pass
        try:
            out["carga"] = round(os.getloadavg()[0], 2)
            out["nucleos"] = os.cpu_count()
        except OSError:
            pass
        if shutil.which("vcgencmd"):
            try:
                t = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=3).stdout
                v = int(t.strip().split("=")[1], 16)
                out["bajo_voltaje"] = bool(v & 0x1)
                out["frenada"] = bool(v & 0x6)          # velocidad limitada (corriente o temperatura)
                out["bajo_voltaje_antes"] = bool(v & 0x10000)
                out["frenada_antes"] = bool(v & 0x60000)
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                pass
        with self.library.lock:
            out["convirtiendo"] = sum(1 for c in self.library.clips.values() if c["status"] in ("queued", "processing"))
        return out

    async def sistema(self, request):
        return web.json_response(await asyncio.get_running_loop().run_in_executor(None, self._sistema))

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
        app.router.add_post("/api/clips/new", self.new_clip)
        app.router.add_get("/api/red", self.red_get)
        app.router.add_get("/api/sistema", self.sistema)
        app.router.add_post("/api/red", self.red_set)
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
                try:
                    sslctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                    sslctx.load_cert_chain(self.cfg.cert_file, self.cfg.key_file)
                    sites.append(web.TCPSite(runner, "0.0.0.0", self.cfg.https_port, ssl_context=sslctx))
                except (OSError, ssl.SSLError) as e:
                    # sin https solo se pierde el microfono; la web normal tiene que andar igual
                    log.error("certificado https invalido (%s): sigo solo con http", e)
            for s in list(sites):
                try:
                    self.loop.run_until_complete(s.start())
                except OSError as e:
                    log.error("no pude abrir %s: %s", s.name, e)
                    sites.remove(s)
            log.info("web en http://0.0.0.0:%d%s", self.cfg.http_port,
                     f" y https :{self.cfg.https_port}" if len(sites) > 1 else "")
            self.loop.create_task(self.ticker())
            ready.set()
            self.loop.run_forever()

        threading.Thread(target=run, daemon=True).start()
        ready.wait(10)

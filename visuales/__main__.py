"""Punto de entrada: python -m visuales"""
import argparse
import logging
import os
import threading
import time
from pathlib import Path

from .config import Config
from .state import Mixer
from .library import Library
from .server import Server
from .deck import Deck


def control_urls(port):
    import socket
    urls = [f"http://localhost:{port}"]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no envia nada, solo elige la interfaz
        ip = s.getsockname()[0]
        s.close()
        if not ip.startswith("127."):
            urls.append(f"http://{ip}:{port}  (desde el telefono, misma wifi)")
    except Exception:
        pass
    return urls


def port_free(port):
    """True si nadie atiende ese puerto. Se prueba conectando (otra app en localhost) y abriendo
    en todas las interfaces sin reutilizar (en Mac/Windows abrir 0.0.0.0 puede "ganar" igual)."""
    import socket
    with socket.socket() as c:
        c.settimeout(0.3)
        if c.connect_ex(("127.0.0.1", port)) == 0:
            return False
    try:
        with socket.socket() as s:
            s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False


def pick_port(start, tries=20):
    for p in range(start, start + tries):
        if port_free(p):
            return p
    return start


def setup_test(cfg):
    """Modo test en PC/Mac: misma app y misma web, sin las partes que solo existen en la Pi."""
    if cfg.sim_pi3:
        # mismo tamano de trabajo que la Pi 3 (install.sh pone CLIP_H=360 y el render usa 360 lineas)
        if "VISUALES_CLIP_H" not in os.environ:
            cfg.clip_max_h = 360
        if "VISUALES_RENDER_H" not in os.environ:
            cfg.render_h = 360
    if "VISUALES_HTTP_PORT" not in os.environ:
        # en la PC puede haber otra app en 8080: se usa el siguiente libre (8081, 8082...)
        port = pick_port(cfg.http_port)
        if port != cfg.http_port:
            print(f"\n  El puerto {cfg.http_port} esta ocupado por otra app: uso el {port}", flush=True)
        cfg.http_port = port
    if "VISUALES_USB_DIR" not in os.environ:
        # pendrive simulado: una carpeta adentro de esta cuenta como un pendrive enchufado
        cfg.usb_dir = str(cfg.data_dir / "pendrive")
        demo = cfg.data_dir / "pendrive" / "mi-pendrive"
        try:
            demo.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    print("\n  ===== MODO TEST (PC/Mac) =====", flush=True)
    print(f"  Datos: {cfg.data_dir}", flush=True)
    print(f"  Pendrive simulado: copia videos a {Path(cfg.usb_dir) / 'mi-pendrive'}", flush=True)
    if cfg.sim_pi3:
        print("  Imitando la Pi 3: clips y efectos a 360 lineas", flush=True)


def main():
    ap = argparse.ArgumentParser(description="Visuales en vivo para Raspberry Pi")
    ap.add_argument("--window", action="store_true", help="ventana en vez de pantalla completa (pruebas)")
    ap.add_argument("--renderer", choices=["auto", "gl", "gl2", "sdl"])
    ap.add_argument("--data", help="carpeta de datos")
    ap.add_argument("--test", action="store_true", help="modo test en PC/Mac (ventana, sin red ni pendrive reales)")
    ap.add_argument("--pi3", action="store_true", help="en modo test: imitar la Pi 3 (360 lineas)")
    ap.add_argument("--port", type=int, help="puerto de la web (por defecto 8080; en modo test, el primero libre)")
    ap.add_argument("--no-browser", action="store_true", help="en modo test: no abrir el navegador")
    ap.add_argument("--max-seconds", type=float, default=0, help="salir despues de N segundos (pruebas)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    cfg = Config()
    if args.test:
        cfg.test = True
    if args.pi3:
        cfg.sim_pi3 = True
    if args.port:
        cfg.http_port = args.port
        os.environ["VISUALES_HTTP_PORT"] = str(args.port)  # puerto pedido a mano: no buscar otro
    if args.window or cfg.test:
        cfg.fullscreen = False
    if args.renderer:
        cfg.renderer = args.renderer
    if args.data:
        cfg.data_dir = Path(args.data)

    try:
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(cfg.data_dir / "visuales.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(fh)
    except Exception:
        pass
    if cfg.test:
        setup_test(cfg)
    mixer = Mixer()
    server = None
    library = Library(cfg, on_change=lambda: server and server.notify_library())
    from .shows import Shows
    shows = Shows(cfg)
    mixer.load_live(shows.active_live())
    server = Server(cfg, mixer, library, shows)
    server.start_in_thread()
    from . import generators
    from .usb import UsbImporter
    usb = UsbImporter(cfg, library, shows, server.notify_usb)
    server.usb = usb
    usb.start()
    for url in control_urls(cfg.http_port):
        print(f"\n  >>> Control: {url}", flush=True)
    print("  (en la ventana de video: Esc para salir)\n", flush=True)
    if cfg.test and not args.no_browser:
        import webbrowser
        threading.Timer(1.5, webbrowser.open, (f"http://localhost:{cfg.http_port}",)).start()
    os.environ.setdefault("SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS", "0")
    from . import render  # importa pygame recien aca
    import pygame
    renderer = render.create(cfg)
    decks = {k: Deck(k, cfg.fps) for k in "AB"}
    clock = pygame.time.Clock()
    t_start = last = time.monotonic()
    frames, t_stat = 0, t_start
    t_retry = t_start
    running = True
    while running:
        for ev in (pygame.event.get() if pygame.display.get_init() else ()):
            if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_q)):
                running = False
        now = time.monotonic()
        dt, last = now - last, now
        s = mixer.tick()
        generators.set_audio(s["audio"])
        # recursos de texto: los prendidos a mano + los vinculados al clip que esta al aire
        live_clip = s["decks"]["A" if s["xfade"] < 0.5 else "B"]["clip"]
        texts = s["texts"] + [t for t in library.linked_texts(live_clip) if t not in s["texts"]]
        if texts:  # van despues del texto en vivo
            s["osd"] = s["osd"] + library.text_layers(texts, s["beats"])
        for k, d in decks.items():
            clip = s["decks"][k]["clip"]
            d.load(library.path_of(clip) if clip else None)
            # el deck que no se ve queda congelado en su primer frame
            # y arranca cuando empieza el crossfade (GO)
            weight = s["xfade"] if k == "B" else 1.0 - s["xfade"]
            d.update(dt, s["decks"][k]["fx"]["speed"] if weight > 0.001 else 0.0, s["beats"], s["decks"][k]["fx"])
            if d.gen == "solid":  # el solido siempre cubre toda la pantalla
                s["decks"][k]["fx"].update(fit="stretch", zoom=1.0, panx=0.0, pany=0.0)
        renderer.draw(decks, s)
        if renderer.name == "sin-video" and now - t_retry > 15:
            # reintentar la pantalla cada 15 s (por si se conecto el HDMI o se libero la pantalla)
            t_retry = now
            pygame.display.quit()
            renderer = render.create(cfg)
        clock.tick(60)
        frames += 1
        if now - t_stat >= 2:
            fps = frames / (now - t_stat)
            server.stats = {"fps": round(fps, 1), "render": renderer.name, "res": getattr(renderer, "res", None)}
            n_log = getattr(server, "_nlog", 0) + 1
            server._nlog = n_log
            if n_log % 5 == 0:  # al log cada 10 s
                logging.getLogger("main").info("%.1f fps (%s)", fps, renderer.name)
            frames, t_stat = 0, now
        if args.max_seconds and now - t_start > args.max_seconds:
            running = False
    for d in decks.values():
        d.stop()
    pygame.quit()


if __name__ == "__main__":
    main()

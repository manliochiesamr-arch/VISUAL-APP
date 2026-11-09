"""Punto de entrada: python -m visuales"""
import argparse
import logging
import os
import time

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


def main():
    ap = argparse.ArgumentParser(description="Visuales en vivo para Raspberry Pi")
    ap.add_argument("--window", action="store_true", help="ventana en vez de pantalla completa (pruebas)")
    ap.add_argument("--renderer", choices=["auto", "gl", "gl2", "sdl"])
    ap.add_argument("--data", help="carpeta de datos")
    ap.add_argument("--demo", action="store_true", help="generar clips de prueba si no hay videos")
    ap.add_argument("--max-seconds", type=float, default=0, help="salir despues de N segundos (pruebas)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    cfg = Config()
    if args.window:
        cfg.fullscreen = False
    if args.renderer:
        cfg.renderer = args.renderer
    if args.data:
        from pathlib import Path
        cfg.data_dir = Path(args.data)

    try:
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(cfg.data_dir / "visuales.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(fh)
    except Exception:
        pass
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
    if args.demo:
        import threading
        from .library import add_demo_clips
        threading.Thread(target=add_demo_clips, args=(library,), daemon=True).start()

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
        if now - t_stat >= 10:
            logging.getLogger("main").info("%.1f fps (%s)", frames / (now - t_stat), renderer.name)
            frames, t_stat = 0, now
        if args.max_seconds and now - t_start > args.max_seconds:
            running = False
    for d in decks.values():
        d.stop()
    pygame.quit()


if __name__ == "__main__":
    main()

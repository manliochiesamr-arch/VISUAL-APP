"""Salida de video. Dos implementaciones con el mismo resultado visual:
- GLRenderer: OpenGL (moderngl), todo en un shader. Opcion principal.
- SDLRenderer: blits de SDL en CPU. Respaldo si OpenGL no arranca en la placa.
"""
import logging
import os

import pygame

log = logging.getLogger("render")

VERT = """
#version 140
in vec2 pos;
out vec2 uv;
void main() {
    uv = vec2(pos.x * 0.5 + 0.5, 0.5 - pos.y * 0.5);
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

FRAG = """
#version 140
in vec2 uv;
out vec4 color;
uniform sampler2D texA;
uniform sampler2D texB;
uniform float hasA;
uniform float hasB;
uniform vec2 fitA;      // tamano del clip en unidades de pantalla (encuadre)
uniform vec2 fitB;
uniform vec3 clipA;     // ajustes del clip: zoom, pan x, pan y
uniform vec3 clipB;
uniform float zoom;
uniform vec2 offset;    // terremoto
uniform float droste;   // 1 = zoom infinito (copias anidadas del cuadro)
uniform float xfade;
uniform float master;
uniform vec3 tint;
uniform float tintAmount;
uniform float strobe;
uniform vec3 strobeColor;

vec3 sampleDeck(sampler2D tex, vec2 fit, vec3 clip, vec2 p) {
    vec2 q = (p / clip.x + clip.yz) / fit;
    if (droste > 0.5) {
        float m = max(abs(q.x), abs(q.y)) * 2.0;
        float k = clamp(floor(-log2(max(m, 1e-4))), -8.0, 12.0);
        q *= exp2(k);
    }
    vec2 tc = q + 0.5;
    if (tc.x < 0.0 || tc.x > 1.0 || tc.y < 0.0 || tc.y > 1.0) return vec3(0.0);
    return texture(tex, tc).rgb;
}

void main() {
    vec2 p = (uv - 0.5) / zoom + offset;
    vec3 a = hasA > 0.5 ? sampleDeck(texA, fitA, clipA, p) : vec3(0.0);
    vec3 b = hasB > 0.5 ? sampleDeck(texB, fitB, clipB, p) : vec3(0.0);
    vec3 c = mix(a, b, xfade);
    c = mix(c, c * tint, tintAmount);
    c = mix(c, strobeColor, strobe);
    color = vec4(c * master, 1.0);
}
"""


def fit_scale(clip_aspect, screen_aspect, mode):
    """Tamano del clip relativo a la pantalla (1,1 = ocupa toda la pantalla)."""
    if mode == "stretch":
        return (1.0, 1.0)
    wider = clip_aspect > screen_aspect
    if mode == "fill":
        return (clip_aspect / screen_aspect, 1.0) if wider else (1.0, screen_aspect / clip_aspect)
    return (1.0, screen_aspect / clip_aspect) if wider else (clip_aspect / screen_aspect, 1.0)


def open_window(cfg, opengl):
    flags = pygame.DOUBLEBUF
    if opengl:
        flags |= pygame.OPENGL
    size = (cfg.width, cfg.height)
    if cfg.fullscreen:
        flags |= pygame.FULLSCREEN
        size = (0, 0)  # resolucion nativa del HDMI

    if opengl:
        # la Pi 4 (V3D) expone GL 3.1; pedimos 3.1 core
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 1)
    screen = pygame.display.set_mode(size, flags, vsync=1)
    pygame.display.set_caption("visuales")
    pygame.mouse.set_visible(False)
    return screen


class GLRenderer:
    name = "gl"

    def __init__(self, cfg):
        import moderngl
        import struct
        self.cfg = cfg
        self.screen = open_window(cfg, opengl=True)
        self.size = pygame.display.get_surface().get_size()
        self.ctx = moderngl.create_context(require=310)
        log.info("OpenGL: %s / %s", self.ctx.info.get("GL_RENDERER"), self.ctx.info.get("GL_VERSION"))
        self.prog = self.ctx.program(vertex_shader=VERT, fragment_shader=FRAG)
        quad = struct.pack("8f", -1, -1, 1, -1, -1, 1, 1, 1)
        self.vbo = self.ctx.buffer(quad)
        self.vao = self.ctx.vertex_array(self.prog, [(self.vbo, "2f", "pos")])
        self.moderngl = moderngl
        self.tex = {"A": None, "B": None}
        self.serial = {"A": -1, "B": -1}
        self.prog["texA"].value = 0
        self.prog["texB"].value = 1

    def _upload(self, k, d, unit):
        t = self.tex[k]
        if t is None or t.size != (d.w, d.h):
            if t is not None:
                t.release()
            t = self.ctx.texture((d.w, d.h), 3)
            t.filter = (self.moderngl.LINEAR, self.moderngl.LINEAR)
            self.tex[k] = t
            self.serial[k] = -1
        if d.frame_serial != self.serial[k]:
            t.write(d.frame)
            self.serial[k] = d.frame_serial
        t.use(unit)

    def draw(self, decks, s):
        p = self.prog
        for unit, k in enumerate("AB"):
            d = decks[k]
            has = d.frame is not None
            if has:
                fx = s["decks"][k]["fx"]
                self._upload(k, d, unit)
                p["fit" + k].value = fit_scale(d.aspect, s["screen_aspect"], fx["fit"])
                p["clip" + k].value = (fx["zoom"], -fx["panx"] * 0.5, -fx["pany"] * 0.5)
            p["has" + k].value = 1.0 if has else 0.0
        p["zoom"].value = s["zoom"]
        p["offset"].value = s["offset"]
        p["droste"].value = 1.0 if s["droste"] else 0.0
        p["xfade"].value = s["xfade"]
        p["master"].value = s["master"]
        p["tint"].value = s["tint"]
        p["tintAmount"].value = s["tint_amount"]
        p["strobe"].value = s["strobe"]
        p["strobeColor"].value = s["strobe_color"]
        self.ctx.viewport = (0, 0, *self.size)
        self.ctx.clear(0, 0, 0)
        self.vao.render(mode=self.ctx.TRIANGLE_STRIP)
        pygame.display.flip()


class SDLRenderer:
    """Respaldo sin OpenGL. Mismo resultado salvo el zoom infinito (aca es un zoom simple)."""
    name = "sdl"

    def __init__(self, cfg):
        self.cfg = cfg
        self.screen = open_window(cfg, opengl=False)
        self.size = self.screen.get_size()
        self.tmp = pygame.Surface(self.size)
        self.gray = pygame.Surface(self.size)
        self.surf = {"A": None, "B": None}
        self.serial = {"A": -1, "B": -1}

    def _surface(self, k, d):
        if d.frame is None:
            return None
        if d.frame_serial != self.serial[k]:
            self.surf[k] = pygame.image.frombuffer(d.frame, (d.w, d.h), "RGB")
            self.serial[k] = d.frame_serial
        return self.surf[k]

    def _place(self, src, d, s, fx, dst):
        """Dibuja el clip en dst con encuadre, zoom y desplazamiento (clip + en vivo)."""
        W, H = self.size
        sx, sy = fit_scale(d.aspect, s["screen_aspect"], fx["fit"])
        zg, zc = s["zoom"], fx["zoom"]
        px, py = -fx["panx"] * 0.5, -fx["pany"] * 0.5
        bw, bh = sx * W * zg * zc, sy * H * zg * zc
        cx = (0.5 - (px * zc + s["offset"][0]) * zg) * W
        cy = (0.5 - (py * zc + s["offset"][1]) * zg) * H
        box = pygame.Rect(round(cx - bw / 2), round(cy - bh / 2), max(1, round(bw)), max(1, round(bh)))
        vis = box.clip(pygame.Rect(0, 0, W, H))
        if vis.w <= 0 or vis.h <= 0:
            return
        kx, ky = d.w / box.w, d.h / box.h
        sr = pygame.Rect(int((vis.x - box.x) * kx), int((vis.y - box.y) * ky),
                         max(1, int(vis.w * kx)), max(1, int(vis.h * ky)))
        sr = sr.clip(src.get_rect())
        part = src.subsurface(sr)
        if part.get_size() != vis.size:
            part = pygame.transform.scale(part, vis.size)
        dst.blit(part, vis.topleft)

    def draw(self, decks, s):
        c = self.screen
        a, b = self._surface("A", decks["A"]), self._surface("B", decks["B"])
        x = s["xfade"]
        layers = [(a, "A", 0.0 if a is None else 1.0 - x), (b, "B", 0.0 if b is None else x)]
        c.fill((0, 0, 0))
        for src, k, w in layers:
            if w <= 0.002:
                continue
            self.tmp.fill((0, 0, 0))
            self._place(src, decks[k], s, s["decks"][k]["fx"], self.tmp)
            if w < 0.998:
                self._mul(self.tmp, w)
            c.blit(self.tmp, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
        if s["tint_amount"] > 0:
            t, k = s["tint"], s["tint_amount"]
            self.gray.fill(tuple(int(255 * (1 - k + k * t[i])) for i in range(3)))
            c.blit(self.gray, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        if s["strobe"] > 0:
            c.fill(tuple(int(255 * v) for v in s["strobe_color"]))
        if s["master"] < 0.998:
            self._mul(c, s["master"])
        pygame.display.flip()

    def _mul(self, surf, k):
        v = int(255 * k)
        self.gray.fill((v, v, v))
        surf.blit(self.gray, (0, 0), special_flags=pygame.BLEND_RGB_MULT)


def create(cfg):
    pygame.display.init()
    want = cfg.renderer
    if want in ("auto", "gl"):
        try:
            os.environ.setdefault("MESA_GL_VERSION_OVERRIDE", "3.3")
            os.environ.setdefault("MESA_GLSL_VERSION_OVERRIDE", "330")
            r = GLRenderer(cfg)
            log.info("render OpenGL activo")
            return r
        except Exception as e:
            if want == "gl":
                raise
            log.warning("OpenGL no disponible (%s), uso render SDL", e)
            pygame.display.quit()
            pygame.display.init()
    r = SDLRenderer(cfg)
    log.info("render SDL activo")
    return r

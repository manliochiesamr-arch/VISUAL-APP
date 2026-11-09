"""Salida de video. Tres implementaciones con el mismo resultado visual:
- GLRenderer: OpenGL 3 (moderngl), Pi 4/5 y PC.
- GL2Renderer: OpenGL 2.1 (PyOpenGL), para la GPU de la Pi 3 (VideoCore IV).
- SDLRenderer: blits de SDL en CPU. Respaldo si OpenGL no arranca.
"""
import logging
import os
import time

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
uniform float rgbSplit;  // glitch: desfasaje de canales 0..1
uniform float tracking;  // glitch: filas corridas + banda de tracking 0..1
uniform float hueShift;  // rotacion de color 0..1 (vuelta completa)
uniform float saturation; // 0 = blanco y negro, 1 = normal, 2 = saturado
uniform float time;
uniform sampler2D texT;  // texto VHS (RGBA)
uniform float hasT;

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

vec3 scene(vec2 p) {
    vec3 a = hasA > 0.5 ? sampleDeck(texA, fitA, clipA, p) : vec3(0.0);
    vec3 b = hasB > 0.5 ? sampleDeck(texB, fitB, clipB, p) : vec3(0.0);
    return mix(a, b, xfade);
}

float hash(vec2 v) {
    return fract(sin(dot(v, vec2(12.9898, 78.233))) * 43758.5453);
}

void main() {
    vec2 p = (uv - 0.5) / zoom + offset;
    float band = 0.0;
    if (tracking > 0.001) {
        float frame = floor(time * 25.0);
        float row = floor(uv.y * 160.0);
        float by = fract(time * 0.23);                       // banda de tracking que baja
        band = smoothstep(0.07, 0.0, abs(uv.y - by));
        float jit = (hash(vec2(row, frame)) - 0.5) * 0.02;   // temblor fino de cada fila
        float tear = (hash(vec2(floor(row / 6.0), frame)) - 0.5) * band * 0.25;
        p.x += tracking * (jit + tear + 0.01 * sin(uv.y * 40.0 + time * 7.0));
    }
    vec3 c;
    if (rgbSplit > 0.001) {
        float dx = rgbSplit * 0.035;
        c = vec3(scene(p + vec2(dx, 0.0)).r, scene(p).g, scene(p - vec2(dx, 0.0)).b);
    } else {
        c = scene(p);
    }
    if (tracking > 0.001) {
        float n = hash(uv * 400.0 + time);
        c = mix(c, vec3(n), band * tracking * 0.6);
    }
    if (hueShift > 0.001) {                                  // rotacion de tono (YIQ)
        float yy = dot(c, vec3(0.299, 0.587, 0.114));
        float ii = dot(c, vec3(0.596, -0.274, -0.322));
        float qq = dot(c, vec3(0.211, -0.523, 0.312));
        float ang = hueShift * 6.2831853;
        float ca = cos(ang), sa = sin(ang);
        float i2 = ii * ca - qq * sa, q2 = ii * sa + qq * ca;
        c = vec3(yy + 0.956 * i2 + 0.621 * q2, yy - 0.272 * i2 - 0.647 * q2, yy - 1.106 * i2 + 1.703 * q2);
    }
    float luma = dot(c, vec3(0.299, 0.587, 0.114));
    c = clamp(mix(vec3(luma), c, saturation), 0.0, 1.0);
    c = mix(c, c * tint, tintAmount);
    c = mix(c, strobeColor, strobe);
    if (hasT > 0.5) {
        vec4 o = texture(texT, uv);
        c = mix(c, o.rgb, o.a);
    }
    color = vec4(c * master, 1.0);
}
"""


# uniform del shader, clave en s["glitch"], valor por defecto
GLITCH_UNIFORMS = (("rgbSplit", "rgb", 0.0), ("tracking", "tracking", 0.0), ("hueShift", "hue", 0.0),
                   ("saturation", "sat", 1.0), ("time", "time", 0.0))


class OsdCache:
    """Lienzo RGBA del texto VHS; solo se rehace cuando cambia el texto, el lugar o el minuto."""

    def __init__(self):
        self.key, self.img = None, None
        self.serial = 0

    def get(self, s):
        layers = [o for o in (s.get("osd") or []) if o.get("on")]
        if not layers:
            return None
        from . import osd
        key = (tuple((osd.expand(o.get("text", "")), o.get("pos"), o.get("size")) for o in layers),
               round(s["screen_aspect"], 2))
        if key != self.key:
            self.key = key
            img = osd.render_layers(key[0], s["screen_aspect"])
            self.img = None if img is None else (img * 255).astype("uint8")
            self.serial += 1
        return self.img


def fit_scale(clip_aspect, screen_aspect, mode):
    """Tamano del clip relativo a la pantalla (1,1 = ocupa toda la pantalla)."""
    if mode == "stretch":
        return (1.0, 1.0)
    wider = clip_aspect > screen_aspect
    if mode == "fill":
        return (clip_aspect / screen_aspect, 1.0) if wider else (1.0, screen_aspect / clip_aspect)
    return (1.0, screen_aspect / clip_aspect) if wider else (clip_aspect / screen_aspect, 1.0)


def open_window(cfg, opengl, gl_version=(3, 1)):
    flags = pygame.DOUBLEBUF
    if opengl:
        flags |= pygame.OPENGL
    size = (cfg.width, cfg.height)
    if cfg.fullscreen:
        flags |= pygame.FULLSCREEN
        size = (0, 0)  # resolucion nativa del HDMI

    if opengl:
        # Pi 4 (V3D): GL 3.1 ; Pi 3 (VC4): GL 2.1
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, gl_version[0])
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, gl_version[1])
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
        self.prog["texT"].value = 2
        self.osd, self.osd_tex, self.osd_serial = OsdCache(), None, -1

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
        g = s.get("glitch") or {}
        for name, key, dflt in GLITCH_UNIFORMS:
            if name in p:  # el compilador quita los uniforms que no se usan
                p[name].value = float(g.get(key, dflt))
        img = self.osd.get(s)
        if img is not None:
            h, w = img.shape[:2]
            if self.osd_tex is None or self.osd_tex.size != (w, h):
                if self.osd_tex is not None:
                    self.osd_tex.release()
                self.osd_tex = self.ctx.texture((w, h), 4)
                self.osd_tex.filter = (self.moderngl.NEAREST, self.moderngl.NEAREST)
                self.osd_serial = -1
            if self.osd_serial != self.osd.serial:
                self.osd_tex.write(img.tobytes())
                self.osd_serial = self.osd.serial
            self.osd_tex.use(2)
        p["hasT"].value = 1.0 if img is not None else 0.0
        self.ctx.viewport = (0, 0, *self.size)
        self.ctx.clear(0, 0, 0)
        self.vao.render(mode=self.ctx.TRIANGLE_STRIP)
        pygame.display.flip()


# GLSL 1.20 (OpenGL 2.1): mismo shader que FRAG, en el dialecto que entiende la Pi 3
VERT2 = """
#version 120
attribute vec2 pos;
varying vec2 uv;
void main() {
    uv = vec2(pos.x * 0.5 + 0.5, 0.5 - pos.y * 0.5);
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""
FRAG2 = (FRAG.replace("#version 140", "#version 120")
         .replace("in vec2 uv;", "varying vec2 uv;")
         .replace("out vec4 color;", "")
         .replace("texture(tex, tc)", "texture2D(tex, tc)")
         .replace("texture(texT, uv)", "texture2D(texT, uv)")
         .replace("color = vec4(", "gl_FragColor = vec4("))


class GL2Renderer:
    name = "gl2"

    def __init__(self, cfg):
        import ctypes
        # en la Pi (kmsdrm) el contexto es EGL; PyOpenGL por defecto busca GLX y no lo encuentra
        if os.environ.get("SDL_VIDEODRIVER") == "kmsdrm":
            os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
        import OpenGL
        OpenGL.ERROR_CHECKING = False
        from OpenGL import GL
        self.GL, self.ctypes = GL, ctypes
        self.cfg = cfg
        open_window(cfg, opengl=True, gl_version=(2, 1))
        self.size = pygame.display.get_surface().get_size()
        log.info("OpenGL: %s / %s", GL.glGetString(GL.GL_RENDERER), GL.glGetString(GL.GL_VERSION))
        self.prog = self._program(VERT2, FRAG2)
        GL.glUseProgram(self.prog)
        import array
        quad = array.array("f", [-1, -1, 1, -1, -1, 1, 1, 1])
        self.vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, len(quad) * 4, quad.tobytes(), GL.GL_STATIC_DRAW)
        loc = GL.glGetAttribLocation(self.prog, "pos")
        GL.glEnableVertexAttribArray(loc)
        GL.glVertexAttribPointer(loc, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, ctypes.c_void_p(0))
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        self.u = {n: GL.glGetUniformLocation(self.prog, n) for n in (
            "texA", "texB", "hasA", "hasB", "fitA", "fitB", "clipA", "clipB", "zoom", "offset", "droste",
            "xfade", "master", "tint", "tintAmount", "strobe", "strobeColor", "texT", "hasT",
            *[n for n, _, _ in GLITCH_UNIFORMS])}
        GL.glUniform1i(self.u["texA"], 0)
        GL.glUniform1i(self.u["texB"], 1)
        GL.glUniform1i(self.u["texT"], 2)
        self.osd = OsdCache()
        GL.glActiveTexture(GL.GL_TEXTURE2)
        self.osd_tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.osd_tex)
        for p, v in ((GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST),
                     (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE), (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, p, v)
        self.osd_serial = -1
        self.tex = {}
        for unit, k in enumerate("AB"):
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            t = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, t)
            for p, v in ((GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR),
                         (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE), (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)):
                GL.glTexParameteri(GL.GL_TEXTURE_2D, p, v)
            self.tex[k] = {"id": t, "size": None, "serial": -1}

    def _program(self, vs, fs):
        GL = self.GL
        prog = GL.glCreateProgram()
        for src, kind in ((vs, GL.GL_VERTEX_SHADER), (fs, GL.GL_FRAGMENT_SHADER)):
            sh = GL.glCreateShader(kind)
            GL.glShaderSource(sh, src)
            GL.glCompileShader(sh)
            if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
                raise RuntimeError("shader: %s" % GL.glGetShaderInfoLog(sh))
            GL.glAttachShader(prog, sh)
        GL.glLinkProgram(prog)
        if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
            raise RuntimeError("link: %s" % GL.glGetProgramInfoLog(prog))
        return prog

    def draw(self, decks, s):
        GL, u = self.GL, self.u
        for unit, k in enumerate("AB"):
            d, t = decks[k], self.tex[k]
            has = d.frame is not None
            if has:
                GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
                GL.glBindTexture(GL.GL_TEXTURE_2D, t["id"])
                if t["size"] != (d.w, d.h):
                    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, d.w, d.h, 0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, d.frame)
                    t["size"], t["serial"] = (d.w, d.h), d.frame_serial
                elif t["serial"] != d.frame_serial:
                    GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, d.w, d.h, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, d.frame)
                    t["serial"] = d.frame_serial
                fx = s["decks"][k]["fx"]
                GL.glUniform2f(u["fit" + k], *fit_scale(d.aspect, s["screen_aspect"], fx["fit"]))
                GL.glUniform3f(u["clip" + k], fx["zoom"], -fx["panx"] * 0.5, -fx["pany"] * 0.5)
            GL.glUniform1f(u["has" + k], 1.0 if has else 0.0)
        GL.glUniform1f(u["zoom"], s["zoom"])
        GL.glUniform2f(u["offset"], *s["offset"])
        GL.glUniform1f(u["droste"], 1.0 if s["droste"] else 0.0)
        GL.glUniform1f(u["xfade"], s["xfade"])
        GL.glUniform1f(u["master"], s["master"])
        GL.glUniform3f(u["tint"], *s["tint"])
        GL.glUniform1f(u["tintAmount"], s["tint_amount"])
        GL.glUniform1f(u["strobe"], s["strobe"])
        GL.glUniform3f(u["strobeColor"], *s["strobe_color"])
        g = s.get("glitch") or {}
        for name, key, dflt in GLITCH_UNIFORMS:
            GL.glUniform1f(u[name], float(g.get(key, dflt)))
        img = self.osd.get(s)
        if img is not None and self.osd_serial != self.osd.serial:
            GL.glActiveTexture(GL.GL_TEXTURE2)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.osd_tex)
            h, w = img.shape[:2]
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, w, h, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, img.tobytes())
            self.osd_serial = self.osd.serial
        GL.glUniform1f(u["hasT"], 1.0 if img is not None else 0.0)
        GL.glViewport(0, 0, *self.size)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
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
        self.osd, self.osd_serial, self.osd_surf = OsdCache(), -1, None

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
        img = self.osd.get(s)
        if img is not None:
            if self.osd_serial != self.osd.serial:
                h, w = img.shape[:2]
                surf = pygame.image.frombuffer(img.tobytes(), (w, h), "RGBA")
                self.osd_surf = pygame.transform.scale(surf, self.size)  # sin suavizar: pixeles VHS
                self.osd_serial = self.osd.serial
            c.blit(self.osd_surf, (0, 0))
        if s["master"] < 0.998:
            self._mul(c, s["master"])
        pygame.display.flip()

    def _mul(self, surf, k):
        v = int(255 * k)
        self.gray.fill((v, v, v))
        surf.blit(self.gray, (0, 0), special_flags=pygame.BLEND_RGB_MULT)


def _is_pi3():
    try:
        with open("/proc/device-tree/model") as f:
            return "Raspberry Pi 3" in f.read()
    except OSError:
        return False


class NullRenderer:
    """Sin salida de video (no hay pantalla disponible). La web sigue andando y se reintenta."""
    name = "sin-video"

    def draw(self, decks, s):
        time.sleep(0.04)


def create(cfg):
    """Devuelve un renderer. Si no hay pantalla (kmsdrm no disponible, HDMI sin detectar,
    otro programa usando la pantalla), devuelve NullRenderer en vez de romper."""
    try:
        pygame.display.init()
    except pygame.error as e:
        log.error("sin pantalla (%s). Revisar: HDMI conectado antes de encender, "
                  "escritorio desactivado (multi-user.target), /dev/dri. La web sigue activa.", e)
        return NullRenderer()
    want = cfg.renderer
    order = {"gl": ["gl"], "gl2": ["gl2"], "sdl": []}.get(want)
    if order is None:  # auto
        order = ["gl2"] if _is_pi3() else ["gl", "gl2"]
    for name in order:
        try:
            if name == "gl":
                os.environ.setdefault("MESA_GL_VERSION_OVERRIDE", "3.3")
                os.environ.setdefault("MESA_GLSL_VERSION_OVERRIDE", "330")
                r = GLRenderer(cfg)
            else:
                r = GL2Renderer(cfg)
            log.info("render %s activo", r.name)
            return r
        except Exception as e:
            if want == name:
                raise
            log.warning("render %s no disponible (%s)", name, e)
            pygame.display.quit()
            pygame.display.init()
    r = SDLRenderer(cfg)
    log.info("render SDL activo")
    return r

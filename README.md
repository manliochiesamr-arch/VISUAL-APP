# Visuales

Motor de visuales en vivo para Raspberry Pi 4. Tiene dos decks (A/B) con crossfade real, tinte, strobe a tempo, velocidad por deck, encuadre 4:3/16:9, zoom (fijo, pulso, infinito in/out), terremoto, master y blackout con fade. Sale por HDMI. Se controla desde el iPhone por el wifi propio de la Pi, sin internet.

## Cómo se usa en el show

1. Conecta el iPhone al wifi de la Pi (por ejemplo `VISUALES`) y abre **http://10.42.0.1**.
2. En Safari toca Compartir y luego **Agregar a pantalla de inicio**. Así queda como una app a pantalla completa.
3. **Shows por banda:** arriba de la pestaña Show eliges qué show está activo, o *Todos los videos*. Con **＋ Show** creas uno nuevo.
   - Un show es una lista ordenada de videos tomados de la biblioteca común. Un mismo video puede estar en varios shows sin duplicarse.
   - Con un show activo, la grilla muestra solo sus videos, en su orden. Lo que subas entra automáticamente a ese show.
   - El show guarda sus ajustes en vivo: BPM, tinte, pantalla, strobe, tiempos de fade y master. Al elegirlo, se cargan.
   - Se arma en Biblioteca: el botón **＋ show** de cada video lo agrega o lo quita, y en la lista del show se ordena con ↑ ↓.
   - Los ajustes de la pestaña Clip pertenecen al video, así que son los mismos en todos los shows.
4. **Pestaña Show:**
   - Toca un clip para cargarlo en **NEXT** (borde azul). Queda congelado en su primer frame.
   - Para lanzarlo, toca el mismo clip otra vez o aprieta **GO**. Hace crossfade con el tiempo del fader *Fade*.
   - **CUT** cambia de deck al instante. El fader A/B es un crossfader manual.
   - **Master** controla el brillo general.
5. **BLACKOUT** (arriba, siempre visible) funde a negro, y si lo vuelves a tocar vuelve. El tiempo del fade se ajusta en En vivo.
6. **TAP:** toca al ritmo, con 4 toques alcanza. El último toque marca el beat 1.
7. **Pestaña Clip**, con los ajustes que **quedan guardados en cada video**:
   - Elige si editas el clip en **NEXT** (para prepararlo mientras otro está al aire) o el que está **AL AIRE**. Si en Show tocas el recuadro de un deck, se abre directamente su panel.
   - **Encuadre**: *Entero* lo muestra completo con franjas, *Llenar* recorta para cubrir la pantalla y *Estirar* lo deforma.
   - **Zoom**, **Posición ↔ / ↕** y **Velocidad**. La vista previa muestra cómo va a quedar en la pantalla.
   - Cada vez que cargues ese video sale con estos ajustes. *Reset clip* los vuelve a los valores por defecto.
8. **Pestaña En vivo**, con efectos que se aplican encima de lo que está saliendo y no se guardan en los clips:
   - **Pantalla**: la proporción física del monitor (4:3 para la TV de tubo, 16:9).
   - **Zoom en vivo**: un fader y cuatro modos. *Fijo* aplica el zoom del fader. *Pulso* hace zoom in y out. *∞ In* y *∞ Out* hacen un zoom infinito con el cuadro anidado dentro de sí mismo. **Ciclo** son los beats que dura cada vuelta.
   - **Terremoto**: una sacudida corta y rápida con un fader de intensidad. Un toque la activa o desactiva y si lo mantienes apretado funciona solo mientras lo aprietas.
   - **Tinte**: color y cantidad.
   - **Strobe**: un toque lo activa o desactiva y si lo mantienes apretado funciona solo mientras lo aprietas. Puedes elegir 1/4 a 4 destellos por beat y el color.
   - Tiempo del fade del blackout y tempo: ajuste fino, ½ y ×2, y "Beat 1 ahora".
9. **Pestaña Biblioteca:** subir videos, renombrar y borrar. También se suben desde el PC con el navegador en la misma dirección.

### Videos
- Solo **MP4 con H.264**. Los demás formatos (HEVC/H.265, .mov, .avi y otros) se rechazan con un aviso.
- Al subirse, cada video se convierte **una sola vez** a SD, conservando su proporción (16:9 queda en 1024x576 y 4:3 en 768x576, a 25 fps y sin audio), con prioridad baja. Cómo encaja en la pantalla se ajusta en la pestaña Clip. En la Pi 4 la conversión tarda más o menos lo mismo que dura el video. Mientras tanto aparece como "convirtiendo…". **Sube el material antes del show, no durante.**
- Los videos quedan en `~/visuales-data/` en la Pi.

### Micrófono para BPM (experimental)
Safari solo da acceso al micrófono en una conexión **https**. Para usarlo:
1. Abre **https://10.42.0.1**. Safari avisa que el certificado no es de confianza. Toca *Mostrar detalles* y luego *visitar este sitio web*.
2. En la pestaña En vivo toca "Detectar BPM por micrófono" y acerca el teléfono al bombo. Cuando la estimación se mantiene estable, la manda sola.

Si Safari igual bloquea el micrófono, usa TAP, que funciona siempre.

## Instalación en la Raspberry Pi

**Si nunca usaste una Raspberry, sigue la guía paso a paso [INSTALAR-PI.md](INSTALAR-PI.md)**, desde flashear la SD hasta conectarte con el iPhone. Funciona en Pi 3 (modo liviano: clips de 360p y OpenGL 2.1) y en Pi 4.

Se necesita **Raspberry Pi OS Bookworm 64-bit**. Se recomienda la versión **Lite** (sin escritorio). Para la instalación hace falta internet, por cable o por wifi.

```bash
# copiar esta carpeta a la Pi (pendrive o scp) y luego:
cd visuales
sudo ./install/install.sh
sudo /opt/visuales/install/hdmi-mode.sh 576p     # opcional, ver "HDMI a TV de tubo"
sudo reboot
```

Después de reiniciar, la Pi arranca sola con la app y su wifi propio.

- Logs: `journalctl -u visuales -f`
- Reiniciar la app: `sudo systemctl restart visuales`
- Resolución HDMI automática: `sudo /opt/visuales/install/hdmi-mode.sh auto && sudo reboot`

### HDMI a TV de tubo
Una TV de tubo no tiene entrada HDMI, así que hace falta un **conversor HDMI a AV/RCA**. La mayoría tiene un selector PAL/NTSC, que en Argentina va en PAL (PAL-N si lo ofrece).

- Empieza con la resolución automática. Si el conversor no muestra imagen, o la imagen sale cortada o lenta, fija la salida con `hdmi-mode.sh 576p` (720x576 a 50 Hz). Es la resolución nativa PAL y con ella la Pi trabaja menos. Para NTSC usa `480p`.
- Si el conversor deforma la imagen, porque comprime 16:9 en 4:3, cambia **Pantalla** a 16:9 en la app hasta que un círculo se vea redondo.

### Render
La app usa OpenGL (un shader hace la mezcla y los efectos). Si OpenGL no arranca en la placa, cambia sola a un render SDL que da el mismo resultado. Se puede forzar con `VISUALES_RENDERER=sdl` o `gl` en el servicio. En el log aparece cuál está activo y los fps.

## Probar en una PC con Windows

1. Descomprime el zip en cualquier carpeta.
2. Haz doble clic en **INICIAR-WINDOWS.bat**. La primera vez descarga, dentro de la carpeta `tools`, un Python 3.12 portable propio, ffmpeg y las librerías, así que necesita internet y tarda unos minutos. No toca el Python que ya tengas instalado.
3. Se abre una ventana con la **salida de video** (simula la TV) y el **control** en el navegador (http://localhost:8080). La primera vez se generan 4 clips de prueba.
4. Para probar con el iPhone, conéctalo a la misma wifi que la PC y abre la dirección `http://192.168.x.x:8080` que muestra la consola. Si Windows pregunta por el firewall, permite el acceso en red privada.

Los videos y shows quedan guardados en `C:\Users\<tu usuario>\visuales-datos`, fuera de la carpeta del programa. Así no se pierden al actualizar o al bajar una versión nueva desde GitHub.

## Probar en un PC (Linux o Mac)

```bash
pip install -r requirements.txt     # y tener ffmpeg instalado
python -m visuales --window          # abrir http://localhost:8080 en el navegador
```

## Estructura
- `visuales/state.py`: estado del mezclador y reloj de beat.
- `visuales/deck.py`: decodifica cada clip en loop con ffmpeg, con control de velocidad.
- `visuales/render.py`: salida de video (OpenGL 3, OpenGL 2.1 para la Pi 3, o SDL).
- `visuales/library.py`: biblioteca, validación y conversión a SD.
- `visuales/shows.py`: shows por banda.
- `visuales/server.py`: web, subida de videos y websocket de control.
- `visuales/web/`: interfaz del teléfono.
- `install/`: instalación, wifi propio y resolución HDMI.

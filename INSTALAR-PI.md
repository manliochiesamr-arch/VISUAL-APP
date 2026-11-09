# Instalar Visuales en la Raspberry Pi (paso a paso)

> El instalador detecta solo el usuario de la Pi, sea cual sea. Lo único que cambia son los comandos `ssh` y `scp`, donde va tu usuario.

Esta guía está probada en papel para una **Raspberry Pi 3 Model B**. En una Pi 4 los pasos son los mismos.

## Qué necesitas

- Una **microSD de 16 GB o más**, clase 10 o A1. Con 32 GB te sobra lugar para videos.
- Un lector de microSD para la PC.
- Una **fuente de 5V y 2.5A con conector micro-USB**. La Pi 3 se cuelga o va lenta con un cargador de celular débil.
- Un cable HDMI y un monitor o TV para ver la primera vez. Es opcional pero ayuda.
- La PC con Windows en tu wifi de casa. Para la instalación hace falta internet.

## 1. Flashear la SD (en la PC)

1. Descarga e instala **Raspberry Pi Imager**: https://www.raspberrypi.com/software/
2. Abre el programa y elige:
   - **Dispositivo:** Raspberry Pi 3
   - **Sistema operativo:** *Raspberry Pi OS (other)* → **Raspberry Pi OS Lite (64-bit)**. Es la versión sin escritorio, más liviana, y la app no lo necesita.
   - **Almacenamiento:** tu microSD. Revisa bien que no sea otro disco.
3. Cuando pregunte si quieres **personalizar la configuración**, di que sí y completa:
   - Nombre de host (hostname): el que quieras, por ejemplo `muchoberry`.
   - Usuario: el que quieras (por ejemplo `muchoberry`) y una contraseña que recuerdes. **En esta guía `TU_USUARIO` y `TU_HOST` son el usuario y el hostname que pusiste**, así que reemplázalos en cada comando.
   - Wifi: el **wifi de tu casa** (nombre y clave), con país **AR**.
   - Zona horaria: `America/Argentina/Buenos_Aires`, teclado `es` o `latam`.
   - En la pestaña Servicios: **Habilitar SSH**, con contraseña.
4. Graba la SD y espera a que termine y la verifique.

## 2. Primer arranque

1. Pon la SD en la Pi, conecta el HDMI y por último la fuente.
2. Espera **3 a 5 minutos**: el primer arranque es lento. Cuando en la pantalla aparezca `visuales login:`, ya está.

## 3. Conectarte desde la PC

En Windows abre **PowerShell** y escribe:

```
ssh TU_USUARIO@TU_HOST.local
```

La primera vez pregunta si confías en el equipo: escribe `yes` y después tu contraseña. Mientras la escribes no se ve nada, es normal.

Si responde que no encuentra `TU_HOST.local`, busca la IP de la Pi. Puede estar en el panel de tu router, o en la pantalla HDMI al arrancar. Usa `ssh TU_USUARIO@ESA-IP`. En redes de empresa `.local` suele no funcionar, así que usa directamente la IP.

## 4. Pasar el programa a la Pi

1. En la PC, entra al repo en GitHub, ve a **Code → Download ZIP** y guárdalo en Descargas.
2. En **otra** ventana de PowerShell, en la PC y no en la Pi, ejecuta:

```
scp $HOME\Downloads\VISUAL-APP-main.zip TU_USUARIO@TU_HOST.local:
```

3. Vuelve a la ventana donde estás conectado a la Pi y ejecuta:

```
sudo apt update && sudo apt install -y unzip
unzip -o VISUAL-APP-main.zip
cd VISUAL-APP-main
sudo ./install/install.sh
```

En la Pi 3 esto tarda **10 a 20 minutos**.

## 5. Resolución HDMI para la TV de tubo

Si vas a usar el conversor HDMI a AV, ejecuta:

```
sudo /opt/visuales/install/hdmi-mode.sh 576p
```

Con un monitor normal no hace falta este paso.

## 6. Probar con el wifi de casa

```
sudo reboot
```

Espera 1 o 2 minutos. La pantalla queda negra porque la app está esperando videos. Desde el **iPhone, conectado al wifi de casa**, abre Safari en **http://TU_HOST.local**, o en la IP de la Pi. Sube un video, cárgalo y dale GO.

Si algo falla, desde la PC ejecuta: `ssh TU_USUARIO@TU_HOST.local` y después `journalctl -u visuales -n 50`, y mándame lo que salga.

## 7. Red: wifi conocido o red propia VISUALES

La red se maneja desde la app, en **Biblioteca > Red**. Hay tres modos:

- **Auto** (el que viene puesto): al prender, la Pi busca un wifi conocido (trabajo, casa) durante un minuto. Si lo encuentra se conecta ahí y anda Connect. Si no encuentra ninguno, como en el auditorio, levanta la red propia **VISUALES**.
- **Forzar VISUALES**: siempre la red propia. Es para el día del show. Si la forzás desde la app y en 5 minutos ningún teléfono entra a VISUALES, vuelve sola a Auto.
- **Solo wifi**: nunca levanta VISUALES.

Con la red VISUALES: conectá el iPhone a **VISUALES** y abrí **http://10.42.0.1**. Safari puede avisar que esa red "no tiene internet": elegí mantenerte conectado. La Pi 3 tiene una sola antena wifi, así que mientras está VISUALES no hay internet ni Connect.

Los wifis conocidos se agregan desde la app con **＋ Agregar wifi conocido**.

La red es abierta y el control queda protegido con el PIN de la app. Para cambiar el nombre, ponerle clave u ocultarla: `sudo /opt/visuales/install/setup-ap.sh VISUALES - AR oculta` (el `-` es "sin clave").

**Rescate sin app:** poné la SD en la PC y, en la partición `bootfs`, creá un archivo `visuales-red.txt` con una sola palabra: `auto`, `visuales` o `wifi`. La Pi lo aplica al arrancar. Lo que hace la red queda anotado en `red-log.txt`, en esa misma partición.

## Actualizar el programa más adelante

Repite el paso 4: baja el ZIP nuevo, cópialo con scp, ejecuta `unzip -o` y `sudo ./install/install.sh`, y reinicia. Para descargar del repo hace falta internet, o sea el wifi de casa o un cable de red. **Tus videos y shows no se tocan**: viven en `/home/TU_USUARIO/visuales-data`.

## Qué esperar de la Pi 3

- Es bastante menos potente que una Pi 4, así que la app trabaja en modo liviano: los videos se convierten a 360p, que para una TV de tubo es suficiente. La mezcla y los efectos corren en la GPU con OpenGL 2.1.
- **La conversión al subir es lenta.** Un video 1080p de 3 minutos puede tardar 5 minutos o más. Sube el material con tiempo, o mejor, exporta los videos desde la PC en 720p o menos para que se conviertan más rápido.
- Si en el log ves menos de 20 fps, avísame y lo ajustamos.

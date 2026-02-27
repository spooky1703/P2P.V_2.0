# 📡 P2P File Transfer & Remote Desktop v2.0

![P2P Logo](logo.png)

Una potente aplicación de terminal interactiva para **Transferencia de Archivos** a alta velocidad y **Control de Escritorio Remoto** entre equipos Windows y Mac. Diseñada para funcionar **sin internet**, operando de manera directa y segura dentro de tu red local (Wi-Fi, hotspot o cable Ethernet).

---

##  Características Principales

###  Transferencia Inteligente de Archivos
* **TUI Interactiva:** Olvídate de los comandos complejos. Una interfaz de terminal hermosa y guiada por menús.
* **Auto-Descubrimiento:** No necesitas saber direcciones IP. Los equipos "Remitentes" detectan automáticamente a los "Receptores" en la misma red Wi-Fi o red LAN.
* **Maximizada para Velocidad:**
  * Uso de optimizaciones **Zero-Copy** (transferencias directas del disco a la red).
  * Auto-compresión al vuelo de directorios enteros.
  * Detección automática de archivos ya comprimidos (mp4, zip, jpg) para saltar la recompresión y ahorrar tiempo.
* **Seguridad y Verificación:** Incluye validación interactiva del receptor ("¿Deseas aceptar este archivo?") y comprobación criptográfica **SHA-256** para garantizar la integridad exacta bit por bit.

###  Control de Escritorio Remoto (¡NUEVO en v2.0!)
* **Control Total:** Mira y controla la pantalla de otra computadora en tu misma red desde una ventana nativa (incluye eventos de ratón, clicks, double-clicks, scroll y teclado completo).
* **Conexión Dual-Socket:** Transmisión robusta de video (`puerto 50507`) y eventos (`puerto 50508`) usando arquitecturas paralelas para evitar bloqueos.
* **Streaming de Alta Eficiencia:** Auto-escalado de resolución y compresión inteligente en formato JPEG a un objetivo de **~20 FPS**.
* **Auto-Instalador de Dependencias:** La app instala las dependencias gráficas (`mss`, `Pillow`, `pyautogui`) automáticamente **sólo si decides usar esta función**. Si únicamente transfieres archivos, sigue siendo *100% libre de dependencias extra*.

### Builds Standalone
Puedes compilar la app usando los nuevos scripts de empaquetado. El resultado es un único archivo ejecutable (`.exe` en Windows, ejecutable en Mac) que no requiere que Python esté instalado en la computadora de destino.

---

## Instalación y Uso

### Opción 1: Ejecutables Compilados (Recomendado)
Descarga o usa los ejecutables en la carpeta `dist/` tras ejecutar los scripts.
* **Mac:** `./dist/P2P`
* **Windows:** Doble click en `dist\P2P.exe`

### Opción 2: Usar desde Python
Si descargas el código fuente, solo necesitas ejecutar:

```bash
python3 p2p.py
```

*En Windows se recomienda usar `python p2p.py`.*

---

## Guía de la Interfaz (Menú Principal)

Al ejecutar la aplicación, serás recibido por el menú interactivo con colores ANSI y arte ASCII:

```text
    ▼ [1] Recibir Archivos   (Activar radar)
    ▲ [2] Enviar Archivos    (A un equipo en la red)

    ◆ [3] Controlar Equipo   (Escritorio remoto)
    ◆ [4] Permitir Control   (Compartir tu pantalla)

    ⚙ [5] Configuración
    ✖ [0] Salir
```

### Flujo de Transferencia de Archivos:
1. **Receptor:** Elige `[1] Recibir Archivos`. La app encenderá el "Radar" y quedará a la espera.
2. **Emisor:** Elige `[2] Enviar Archivos`. Arrastra y suelta un archivo o carpeta en la terminal. El emisor escaneará la red y te mostrará una lista de receptores detectados. Eliges uno.
3. **Receptor:** Aparecerá un aviso emergente en tu terminal preguntando si deseas aceptar el archivo. Presiona `S`. ¡Transferencia completada!

### Flujo de Control Remoto:
1. **Equipo a controlar:** Elige `[4] Permitir Control`. La pantalla queda a la escucha.
2. **Controlador:** Elige `[3] Controlar Equipo`. Selecciona el equipo de la lista que aparece.
3. **Equipo a controlar:** Aparece un aviso solicitando el permiso de control. Presiona `S` para confirmar.
4. **Controlador:** Se abrirá una ventana mostrando la pantalla del otro equipo. Puedes enviar clicks y pulsaciones de teclas. Cierra la ventana cuando desees terminar la sesión.

---

## Scripts de Compilación Integrados

Si deseas compilar el código para distribuirlo a máquinas sin Python instalado, localiza los siguientes scripts en la raíz del proyecto. Estos scripts instalan las dependencias gráficas y crean un binario en la carpeta `dist/` luciendo un **ícono personalizado (`logo.png`)**:

**Para compilar en macOS:**
Hacer el script ejecutable (solo la primera vez) y compilar:
```bash
chmod +x build_mac.sh
./build_mac.sh
```

**Para compilar en Windows:**
Solo haz doble click sobre el archivo o corre en la terminal:
```cmd
build_windows.bat
```

---

## Requisitos Técnicos
- Python 3.6+ (si corres desde el código, en vez de los binarios).
- Las funciones de Red Local asumen que los puertos **50505**, **50506**, **50507** y **50508** no están bloqueados por un Firewall.
- macOS pedirá permisos en Ajustes del Sistema -> Privacidad para "Grabación de Pantalla" (Screen Recording) y "Accesibilidad" la primera vez que intentes usar *Permitir Control*. En Windows funciona de "Caja Abierta".

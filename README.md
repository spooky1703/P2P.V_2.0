# P2P File Transfer

Transfiere archivos y carpetas entre Windows y Mac **sin internet**, usando la red local (Wi-Fi directo, hotspot, o cable Ethernet).

## Requisitos

- **Python 3.6+** (ya instalado en Mac; en Windows descargar de [python.org](https://python.org))
- Ambos equipos conectados a la **misma red local** (o cable Ethernet directo)
- **Sin dependencias externas** — solo usa la librería estándar de Python

## Uso Rápido

### 1. En el equipo que RECIBE

```bash
python3 p2p.py receive
```

Opciones:
```bash
python3 p2p.py receive --dir ~/Documentos   # cambiar carpeta destino
python3 p2p.py receive --port 9999           # cambiar puerto
```

### 2. En el equipo que ENVÍA

```bash
python3 p2p.py send ./mi_carpeta
python3 p2p.py send documento.pdf
```

El sender detecta automáticamente al receptor en la red. Si no lo encuentra, puedes especificar la IP:

```bash
python3 p2p.py send archivo.zip --to 192.168.1.50
```

## ¿Cómo funciona?

```
  SENDER                              RECEIVER
  ──────                              ────────
  1. Comprime a ZIP          ←UDP──   1. Anuncia "estoy listo" via broadcast
  2. Detecta al receptor              2. Espera conexión TCP
  3. Conecta TCP ──────TCP──────────→ 3. Recibe header (nombre, tamaño)
  4. Envía archivo   ──datos──────→   4. Recibe y guarda ZIP
  5. Espera confirmación  ←─DONE──   5. Verifica SHA-256, descomprime
```

## Escenarios de conexión

| Escenario | Pasos |
|-----------|-------|
| **Misma red Wi-Fi** | Solo ejecutar los comandos, se detectan solos |
| **Hotspot de celular** | Conectar ambos al hotspot, luego ejecutar |
| **Cable Ethernet directo** | Conectar cable entre los 2 equipos, configurar IPs manuales si es necesario |
| **Sin detección** | Usar `--to <IP>` en el sender |

## Notas

- Los archivos se guardan por defecto en `~/Downloads`
- La transferencia incluye verificación SHA-256 de integridad
- Puedes enviar múltiples archivos metiéndolos en una carpeta
- El receptor se queda escuchando después de cada transferencia (Ctrl+C para salir)
- En Windows, usa `python` en vez de `python3`

# M-Game Mixer (plugin de Omarchy)

Widget de barra para la **M-Audio M-Game RGB Dual** en Linux. El equipo expone
una sola salida de 8 canales; este plugin la divide con PipeWire en dos sinks
estéreo virtuales, como hace el software de Windows:

| Sink | Canales de la M-Game |
|---|---|
| `mgame_game` ("M-Game Game") | FL FR |
| `mgame_chat` ("M-Game Chat") | FC LFE (configurable: `RL RR`, `SL SR`) |

## Qué hace

- Ícono de headset en la barra; el panel muestra dos canales, **Game** y **Chat**, con volumen, mute y "usar como salida por defecto".
- Lista las apps que están reproduciendo audio y deja mandar cada una a Game o a Chat.
- Si los sinks no existen (o el par de canales elegido no coincide con la config instalada), muestra un aviso y un botón que instala `~/.config/pipewire/pipewire.conf.d/50-mgame-split.conf` y reinicia `pipewire pipewire-pulse wireplumber`. **Corta el audio unos segundos**, juegos incluidos.

## Instalar

```bash
omarchy plugin add ~/Projects/omarchy-mgame-mixer --enable
```

Validar antes: `omarchy plugin validate ~/Projects/omarchy-mgame-mixer`.

El par de canales de Chat se cambia en la configuración del widget (`chatPair`). Después de cambiarlo, abrí el panel y tocá **Aplicar canales y reiniciar audio**.

## Comprobar qué canal es cada uno

```bash
speaker-test -c 8 -t wav -l 1
```

Dice el nombre de cada canal por turno (front left, front right, center, LFE, rear left, rear right, side left, side right). Fijate en cuál sale el auricular de Chat y elegí el par que corresponda.

## Archivos

- `manifest.json`, `BarWidget.qml`, `Panel.qml`: el plugin.
- `mgame.py`: helper (solo `pactl`/`systemctl --user`, todo por argv).
- `pipewire/50-mgame-split.conf`: copia de la config por defecto (la que instala el botón se genera con el par elegido).
- `i18n/`: textos en `en` y `es`.

## Licencia

MIT

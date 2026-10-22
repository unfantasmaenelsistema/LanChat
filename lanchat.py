#!/usr/bin/env python3
"""LanChat — chat de texto para tu red local (servidor y cliente en un archivo).

by Un fantasma en el sistema · https://www.unfantasmaenelsistema.com · Licencia MIT

Solo usa la biblioteca estándar de Python 3.8+. Cualquiera puede unirse también
con `ncat IP PUERTO` (o `ncat --ssl IP PUERTO` si la sala usa TLS).
"""

import argparse
import asyncio
import getpass
import hashlib
import hmac
import ipaddress
import json
import os
import re
import select
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata

VERSION = "2.0"
DEFAULT_PORT = 4444
MAX_MSG = 400            # caracteres por mensaje
MAX_LINE = 4096          # bytes por línea antes de cortar la conexión
MAX_NICK = 20
HANDSHAKE_TIMEOUT = 60   # segundos para elegir nombre / contraseña
DEFAULT_IDLE = 600       # 10 minutos sin escribir
DEFAULT_MAX_CLIENTS = 32
RATE_BURST = 8           # mensajes seguidos permitidos
RATE_PER_SEC = 1.5       # recarga del cubo
FLOOD_KICK = 20          # mensajes descartados seguidos antes de expulsar
MAX_WRITE_BUFFER = 256 * 1024
HELLO = "LANCHAT/2 "
WEB = "https://www.unfantasmaenelsistema.com"
REPO = "https://github.com/unfantasmaenelsistema/LanChat"

# --------------------------------------------------------------------------- #
# Textos ES / EN
# --------------------------------------------------------------------------- #

TEXTS = {
    "es": {
        "tagline": "Chat de texto para tu red local",
        "ask_nick": "Escribe tu nombre de usuario:",
        "ask_password": "Contraseña de la sala:",
        "bad_password": "Contraseña incorrecta.",
        "too_many_tries": "Demasiados intentos. Adiós.",
        "nick_invalid": "Nombre no válido: 1-{max} letras, números, «_», «-» o «.» y sin espacios.",
        "nick_taken": "Ese nombre ya está en uso.",
        "room_full": "La sala está llena (máximo {max}).",
        "welcome": "Bienvenido/a a la sala de {host}, {nick}. Escribe /ayuda para ver los comandos.",
        "welcome_headless": "Bienvenido/a a la sala, {nick}. Escribe /ayuda para ver los comandos.",
        "in_room": "En la sala ({n}): {list}",
        "joined": "{nick} se ha unido desde {ip} ({n} en la sala)",
        "left": "{nick} ha salido ({n} en la sala)",
        "left_msg": "{nick} ha salido: {msg} ({n} en la sala)",
        "left_idle": "{nick} desconectado por inactividad ({n} en la sala)",
        "left_lost": "{nick} ha perdido la conexión ({n} en la sala)",
        "left_kick": "{nick} ha sido expulsado/a por el anfitrión ({n} en la sala)",
        "left_flood": "{nick} expulsado/a por inundar la sala ({n} en la sala)",
        "left_slow": "{nick} desconectado/a: no recibía los mensajes ({n} en la sala)",
        "left_long": "{nick} desconectado/a: línea demasiado larga ({n} en la sala)",
        "renamed": "{old} ahora se llama {new}",
        "idle_bye": "Desconectado/a tras {min} min sin escribir.",
        "kicked_you": "El anfitrión te ha expulsado de la sala.",
        "kicked_reason": "El anfitrión te ha expulsado: {reason}",
        "flood_warn": "Vas demasiado rápido: mensaje descartado.",
        "flood_bye": "Expulsado/a por inundar la sala.",
        "line_bye": "Línea demasiado larga ({max} bytes). Conexión cerrada.",
        "truncated": "Mensaje recortado a {max} caracteres.",
        "unknown_cmd": "Comando desconocido: {cmd}. Escribe /ayuda.",
        "no_such_nick": "No hay nadie llamado {nick} en la sala.",
        "msg_self": "No hace falta que te escribas a ti mismo/a.",
        "usage_msg": "Uso: /msg NOMBRE texto",
        "usage_nick": "Uso: /nick NUEVO_NOMBRE",
        "usage_kick": "Uso: /kick NOMBRE [motivo]",
        "host_only": "Solo el anfitrión puede usar {cmd}.",
        "cant_kick_host": "No puedes expulsarte a ti mismo/a.",
        "server_closed": "El servidor ha cerrado la sala.",
        "help": [
            "Comandos:",
            "  /quien  (/who)              quién está en la sala",
            "  /msg NOMBRE texto  (/mp)    mensaje privado",
            "  /me acción                  «* nombre acción»",
            "  /nick NUEVO                 cambiar de nombre",
            "  /salir [mensaje]  (/quit)   salir de la sala",
            "  //texto                     enviar un texto que empieza por /",
        ],
        "help_host": "  /kick NOMBRE [motivo]       expulsar (solo anfitrión)",
        # consola / menú
        "menu_title": "¿Qué quieres hacer?",
        "menu_host": "Crear una sala (servidor)",
        "menu_join": "Unirse a una sala (cliente)",
        "menu_lang": "Language: English",
        "menu_exit": "Salir",
        "option": "Opción",
        "invalid_option": "Opción no válida.",
        "pick_iface": "Interfaz donde escuchará la sala:",
        "all_ifaces": "todas las interfaces",
        "no_ips": "No se detectó ninguna IP de red local; se escuchará en todas las interfaces.",
        "port": "Puerto",
        "port_invalid": "Puerto no válido (1-65535).",
        "nick": "Tu nombre",
        "room_password": "Contraseña de la sala (ENTER = sin contraseña)",
        "use_tls": "¿Cifrar la sala con TLS? (necesita openssl) [s/N]",
        "use_tls_join": "¿La sala usa TLS? [s/N]",
        "no_openssl": "No se encontró openssl: la sala irá sin cifrar.",
        "server_ip": "IP o nombre del servidor",
        "server_ip_invalid": "Dirección no válida.",
        "yes_chars": "sys",
        "listening": "Sala abierta en {addr}:{port}{tls}",
        "tls_on": " con TLS",
        "how_to_join": "Para unirse: ./lan_chat.sh → 2 → {addr}:{port}   ·   o: {ncat}",
        "fingerprint_srv": "Huella SHA-256 del certificado (compruébala de palabra con quien se una):",
        "password_cleartext": "Ojo: sin TLS la contraseña viaja en claro por la red.",
        "write_hint": "Escribe y pulsa ENTER. /ayuda para los comandos, Ctrl+C para salir.",
        "port_busy": "El puerto {port} ya está en uso.",
        "port_denied": "Sin permiso para el puerto {port} (por debajo de 1024 hace falta root).",
        "bind_failed": "No se pudo abrir la sala en {addr}:{port}: {err}",
        "connecting": "Conectando a {host}:{port}{tls} como {nick}…",
        "connect_failed": "No se pudo conectar con {host}:{port}: {err}",
        "not_lanchat": "Ese servidor no responde como una sala LanChat.",
        "tls_failed": "Fallo de TLS: {err}. ¿La sala usa TLS? Prueba con/sin --tls.",
        "fp_seen": "Huella SHA-256 del servidor:",
        "fp_known": "Huella conocida para {host}:{port} ✓",
        "fp_changed": [
            "¡ATENCIÓN! LA HUELLA DEL SERVIDOR HA CAMBIADO.",
            "Antes: {old}",
            "Ahora: {new}",
            "Puede que el anfitrión haya reiniciado la sala con un certificado nuevo,",
            "o que alguien esté interceptando la conexión (MITM). Confírmalo de palabra.",
        ],
        "fp_confirm": "¿Coincide con la huella que muestra el anfitrión? [s/N]",
        "fp_mismatch": "La huella no coincide con --fingerprint. Conexión cancelada.",
        "fp_rejected": "Conexión cancelada.",
        "fp_saved": "Huella guardada en {path}",
        "nick_retry": "Prueba con otro nombre",
        "password_prompt": "Contraseña de la sala: ",
        "lost": "Conexión perdida.",
        "bye": "Hasta pronto.",
        "need_tty": "Este modo necesita una terminal interactiva.",
        "brand": "Un fantasma en el sistema",
    },
    "en": {
        "tagline": "Text chat for your local network",
        "ask_nick": "Type your username:",
        "ask_password": "Room password:",
        "bad_password": "Wrong password.",
        "too_many_tries": "Too many attempts. Bye.",
        "nick_invalid": "Invalid name: 1-{max} letters, digits, '_', '-' or '.', no spaces.",
        "nick_taken": "That name is already taken.",
        "room_full": "The room is full (max {max}).",
        "welcome": "Welcome to {host}'s room, {nick}. Type /help to see the commands.",
        "welcome_headless": "Welcome to the room, {nick}. Type /help to see the commands.",
        "in_room": "In the room ({n}): {list}",
        "joined": "{nick} joined from {ip} ({n} in the room)",
        "left": "{nick} left ({n} in the room)",
        "left_msg": "{nick} left: {msg} ({n} in the room)",
        "left_idle": "{nick} disconnected for inactivity ({n} in the room)",
        "left_lost": "{nick} lost the connection ({n} in the room)",
        "left_kick": "{nick} was kicked by the host ({n} in the room)",
        "left_flood": "{nick} kicked for flooding ({n} in the room)",
        "left_slow": "{nick} disconnected: not reading messages ({n} in the room)",
        "left_long": "{nick} disconnected: line too long ({n} in the room)",
        "renamed": "{old} is now {new}",
        "idle_bye": "Disconnected after {min} min without typing.",
        "kicked_you": "The host kicked you out of the room.",
        "kicked_reason": "The host kicked you out: {reason}",
        "flood_warn": "You are going too fast: message dropped.",
        "flood_bye": "Kicked for flooding the room.",
        "line_bye": "Line too long ({max} bytes). Connection closed.",
        "truncated": "Message cut to {max} characters.",
        "unknown_cmd": "Unknown command: {cmd}. Type /help.",
        "no_such_nick": "Nobody called {nick} is in the room.",
        "msg_self": "No need to message yourself.",
        "usage_msg": "Usage: /msg NAME text",
        "usage_nick": "Usage: /nick NEW_NAME",
        "usage_kick": "Usage: /kick NAME [reason]",
        "host_only": "Only the host can use {cmd}.",
        "cant_kick_host": "You can't kick yourself.",
        "server_closed": "The server closed the room.",
        "help": [
            "Commands:",
            "  /who  (/quien)              who is in the room",
            "  /msg NAME text  (/mp)       private message",
            "  /me action                  '* name action'",
            "  /nick NEW                   change your name",
            "  /quit [message]  (/salir)   leave the room",
            "  //text                      send a text that starts with /",
        ],
        "help_host": "  /kick NAME [reason]         kick someone (host only)",
        "menu_title": "What do you want to do?",
        "menu_host": "Create a room (server)",
        "menu_join": "Join a room (client)",
        "menu_lang": "Idioma: Español",
        "menu_exit": "Exit",
        "option": "Option",
        "invalid_option": "Invalid option.",
        "pick_iface": "Interface the room will listen on:",
        "all_ifaces": "all interfaces",
        "no_ips": "No local network IP found; the room will listen on all interfaces.",
        "port": "Port",
        "port_invalid": "Invalid port (1-65535).",
        "nick": "Your name",
        "room_password": "Room password (ENTER = no password)",
        "use_tls": "Encrypt the room with TLS? (needs openssl) [y/N]",
        "use_tls_join": "Does the room use TLS? [y/N]",
        "no_openssl": "openssl not found: the room will not be encrypted.",
        "server_ip": "Server IP or hostname",
        "server_ip_invalid": "Invalid address.",
        "yes_chars": "y",
        "listening": "Room open on {addr}:{port}{tls}",
        "tls_on": " with TLS",
        "how_to_join": "To join: ./lan_chat.sh → 2 → {addr}:{port}   ·   or: {ncat}",
        "fingerprint_srv": "Certificate SHA-256 fingerprint (check it out loud with whoever joins):",
        "password_cleartext": "Warning: without TLS the password travels in clear text.",
        "write_hint": "Type and press ENTER. /help for commands, Ctrl+C to quit.",
        "port_busy": "Port {port} is already in use.",
        "port_denied": "No permission for port {port} (below 1024 needs root).",
        "bind_failed": "Could not open the room on {addr}:{port}: {err}",
        "connecting": "Connecting to {host}:{port}{tls} as {nick}…",
        "connect_failed": "Could not connect to {host}:{port}: {err}",
        "not_lanchat": "That server does not answer like a LanChat room.",
        "tls_failed": "TLS error: {err}. Does the room use TLS? Try with/without --tls.",
        "fp_seen": "Server SHA-256 fingerprint:",
        "fp_known": "Known fingerprint for {host}:{port} ✓",
        "fp_changed": [
            "WARNING! THE SERVER FINGERPRINT HAS CHANGED.",
            "Before: {old}",
            "Now:    {new}",
            "The host may have restarted the room with a new certificate,",
            "or someone may be intercepting the connection (MITM). Confirm it out loud.",
        ],
        "fp_confirm": "Does it match the fingerprint the host shows? [y/N]",
        "fp_mismatch": "Fingerprint does not match --fingerprint. Connection cancelled.",
        "fp_rejected": "Connection cancelled.",
        "fp_saved": "Fingerprint saved in {path}",
        "nick_retry": "Try another name",
        "password_prompt": "Room password: ",
        "lost": "Connection lost.",
        "bye": "See you soon.",
        "need_tty": "This mode needs an interactive terminal.",
        "brand": "Un fantasma en el sistema",
    },
}


class I18n:
    def __init__(self, lang="es"):
        self.lang = lang if lang in TEXTS else "es"

    def __call__(self, key, **kw):
        value = TEXTS[self.lang][key]
        if isinstance(value, list):
            return [v.format(**kw) for v in value]
        return value.format(**kw)


# --------------------------------------------------------------------------- #
# Configuración (idioma, últimas respuestas, huellas conocidas)
# --------------------------------------------------------------------------- #

def config_dir():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "lanchat")


def load_config():
    try:
        with open(os.path.join(config_dir(), "config.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(data):
    try:
        os.makedirs(config_dir(), exist_ok=True)
        with open(os.path.join(config_dir(), "config.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


def detect_lang(cli_lang=None):
    for value in (cli_lang, os.environ.get("LANCHAT_LANG"), load_config().get("lang")):
        if value in TEXTS:
            return value
    # Kali y muchas distros traen en_US aunque el aula sea española: por defecto, español.
    return "es"


# --------------------------------------------------------------------------- #
# Saneado y validación
# --------------------------------------------------------------------------- #

ZWJ = "\u200d"  # se conserva para no romper emojis compuestos


def sanitize(text, limit=None):
    """Quita caracteres de control (ESC, BEL, retornos, bidi…) para que nadie
    pueda pintar ni mover el cursor en la terminal de los demás."""
    out = []
    for ch in text:
        if ch == "\t":
            out.append(" ")
            continue
        if ch != ZWJ and unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co"):
            continue
        out.append(ch)
    clean = "".join(out).strip()
    return clean[:limit] if limit else clean


NICK_RE = re.compile(r"^[^\W_][\w.-]{0,%d}$" % (MAX_NICK - 1))


def valid_nick(nick):
    return bool(NICK_RE.match(nick or ""))


def valid_host(value):
    value = (value or "").strip()
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        pass
    if re.fullmatch(r"[\d.]+", value):  # parece una IP pero no lo es
        return False
    return bool(re.match(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$", value))


def clock():
    return time.strftime("%H:%M")


# --------------------------------------------------------------------------- #
# Terminal: colores, logo y línea de escritura
# --------------------------------------------------------------------------- #

_ART_PALETTE = (
    "000000", "200000", "202000", "202020", "402020", "404020", "404040", "602020",
    "604020", "604040", "606040", "606060", "608080", "802020", "804020", "806040",
    "806060", "808060", "808080", "80a0a0", "a06040", "a06060", "a08080", "a0a0a0",
    "c04040", "c06040", "c06060", "c08040", "c08080", "c0c0c0", "c0e0e0", "e02020",
    "e04040", "e06060", "e0c0c0", "e0e0e0", "ffa0a0", "ffc0c0", "ffe0e0", "ffffff",
)
_ART_ROWS = (
    "............GLSL......WX..........",
    "..........LXjnnnL....VfaW.........",
    "........GXnnnnnjL...GXfhgcSE......",
    ".......GdnnnnjXXiL..AMcgkgaS......",
    "......GdnnnnXEAGXjL..DTahlgae.....",
    "......XjnnnSADDCDXd...DSghmgc.....",
    ".....LjnnnWADCDDDCXS.IZFThhkgW....",
    ".....XjnnjDDDGDDDCGXIZPD.LVhhYX...",
    "....KdjnnSCBSnQADDBSQI.....QgfaL..",
    "....SdinnLBDjndCASXGS.......SaHAG.",
    "....SddnjGAGnnnXDnjGS.......DSAGX.",
    "....SdSnjGCDjnndAdSFS........GGdXL",
    "....SSGnnLACLjdGDBASL........AGDXS",
    ".......XndGCADBABDSS...........AD.",
    "........injXLGGLSXS...............",
    "........GjnnnjjjdL................",
    ".......JOPnnnnnnjL................",
    ".....IOZZNXnnnnnjG................",
    "..FIPZbZOIRnnnnnd.................",
    "EIPUZZUISjnnnnnnL.................",
    "EEUUPI...SdnnnjL..................",
    "EIIE.......JRQG...................",
)
_ART_KEYS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-"

_TITLE = (
    "█   ▄▀█ █▄ █   █▀▀ █ █ ▄▀█ ▀█▀",
    "█▄▄ █▀█ █ ▀█   █▄▄ █▀█ █▀█  █ ",
)

GREEN = "92"
NICK_COLORS = ("96", "93", "95", "94", "92", "91", "33", "35", "32", "97")


def enable_windows_ansi():
    if os.name == "nt":
        os.system("")  # activa las secuencias VT en la consola clásica


def utf8_streams():
    """En Windows, con la E/S redirigida Python usaría cp1252: «→» o «▀» romperían la salida
    y «ñ» llegaría como «Ã±». La consola interactiva ya va en Unicode."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            if stream.isatty():
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def color_support(stream=None, force_off=False):
    stream = stream or sys.stdout
    if force_off or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return 0
    if not hasattr(stream, "isatty") or not stream.isatty():
        return 0
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit") or os.environ.get("WT_SESSION"):
        return 24
    return 8


def _rgb(hexcode):
    return tuple(int(hexcode[i:i + 2], 16) for i in (0, 2, 4))


def _xterm256(rgb):
    r, g, b = (round(c / 255 * 5) for c in rgb)
    return 16 + 36 * r + 6 * g + b


def _paint(rgb, depth, background=False):
    if depth == 24:
        return "\x1b[%d;2;%d;%d;%dm" % ((48 if background else 38), rgb[0], rgb[1], rgb[2])
    return "\x1b[%d;5;%dm" % ((48 if background else 38), _xterm256(rgb))


def art_lines(depth):
    """Fantasma de la casa en medios bloques (▀): dos píxeles por carácter."""
    pal = {_ART_KEYS[i]: _rgb(h) for i, h in enumerate(_ART_PALETTE)}
    lines = []
    for y in range(0, len(_ART_ROWS), 2):
        top, bottom = _ART_ROWS[y], _ART_ROWS[y + 1]
        out = []
        for a, b in zip(top, bottom):
            if a == "." and b == ".":
                out.append("\x1b[0m ")
            elif b == ".":
                out.append("\x1b[0m" + _paint(pal[a], depth) + "▀")
            elif a == ".":
                out.append("\x1b[0m" + _paint(pal[b], depth) + "▄")
            else:
                out.append(_paint(pal[a], depth) + _paint(pal[b], depth, True) + "▀")
        lines.append("".join(out) + "\x1b[0m")
    return lines


def banner(t, depth=None, width=None):
    depth = color_support() if depth is None else depth
    width = width or shutil.get_terminal_size((80, 24)).columns
    info = [
        "",
        "",
        _TITLE[0],
        _TITLE[1],
        "",
        "v%s · %s" % (VERSION, t("tagline")),
        "",
        "by %s" % t("brand"),
        WEB.replace("https://", ""),
        "",
        "",
    ]
    if not depth:
        return "\n".join(["", "  " + _TITLE[0], "  " + _TITLE[1], "",
                          "  v%s · %s" % (VERSION, t("tagline")),
                          "  by %s · %s" % (t("brand"), WEB.replace("https://", "")), ""])
    if width < 72:
        art = []
    else:
        art = art_lines(depth)
    g = "\x1b[%sm" % GREEN
    dim = "\x1b[2m"
    rst = "\x1b[0m"
    rows = []
    for i in range(max(len(art), len(info))):
        left = art[i] if i < len(art) else ""
        right = info[i] if i < len(info) else ""
        if right in _TITLE:
            right = "\x1b[1m" + g + right + rst
        elif right.startswith("v"):
            right = g + right + rst
        elif right:
            right = dim + right + rst
        rows.append(("  " + left + "   " if art else "  ") + right)
    return "\n".join([""] + rows + [""])


def nick_color(nick):
    return NICK_COLORS[hashlib.sha1(nick.casefold().encode("utf-8")).digest()[0] % len(NICK_COLORS)]


_LINE_RE = re.compile(r"^\[(\d\d:\d\d)\] (.*)$")


def render(line, depth, me=None):
    """Colorea una línea del protocolo. El texto ya llega saneado."""
    if not depth:
        return line
    rst = "\x1b[0m"
    m = _LINE_RE.match(line)
    if not m:
        if line.startswith("[!]") or line.startswith("[-]"):
            return "\x1b[93m" + line + rst
        return "\x1b[2m" + line + rst
    ts, rest = m.groups()
    head = "\x1b[2m[" + ts + "]" + rst + " "
    mention = me and re.search(r"(?<![\w.-])@?%s(?![\w-])" % re.escape(me), rest, re.IGNORECASE)
    if rest.startswith("<"):
        end = rest.find("> ")
        if end > 0:
            nick = rest[1:end]
            body = rest[end + 2:]
            colored = "\x1b[1;%sm<%s>%s " % (nick_color(nick.lstrip("@")), nick, rst)
            if mention and nick.lstrip("@").casefold() != me.casefold():
                body = "\x1b[1;7m" + body + rst
            return head + colored + body
    if rest.startswith("* "):
        return head + "\x1b[3;%sm" % nick_color(rest[2:].split(" ", 1)[0]) + rest + rst
    if rest.startswith("[MP]"):
        return head + "\x1b[95m" + rest + rst
    if rest.startswith("[+]"):
        return head + "\x1b[92m" + rest + rst
    if rest.startswith("[-]"):
        return head + "\x1b[91m" + rest + rst
    if rest.startswith("[!]"):
        return head + "\x1b[93m" + rest + rst
    return head + "\x1b[96m" + rest + rst


class TerminalUI:
    """Pinta mensajes entrantes sin destrozar lo que el usuario está escribiendo."""

    prompt = "> "

    def __init__(self, depth=0, me=None, stream=None):
        self.depth = depth
        self.me = me
        self.stream = stream or sys.stdout
        self.lock = threading.Lock()
        self.interactive = sys.stdin.isatty() and self.stream.isatty()
        self.reading = False        # hay un input() esperando: hay que repintar el prompt
        self.readline = None
        if self.interactive:
            try:
                import readline  # activa la edición de línea en input()
                self.readline = readline
                # se marca «leyendo» cuando el prompt ya está en pantalla, no antes:
                # así un mensaje que llegue justo entonces no duplica el «> »
                readline.set_pre_input_hook(self._prompt_shown)
            except (ImportError, AttributeError):
                self.readline = None

    def _prompt_shown(self):
        with self.lock:
            self.reading = True

    def show(self, line):
        text = render(line, self.depth, self.me)
        with self.lock:
            if self.interactive and self.reading:
                pending = self.readline.get_line_buffer() if self.readline is not None else ""
                self.stream.write("\r\x1b[K" + text + "\n" + self.prompt + pending)
            else:
                self.stream.write(text + "\n")
            self.stream.flush()

    def show_many(self, lines):
        for line in lines:
            self.show(line)

    def read(self):
        if self.interactive:
            if self.readline is None:
                with self.lock:
                    self.reading = True
            try:
                line = input(self.prompt)
            finally:
                with self.lock:
                    self.reading = False
            # borra la línea escrita: el servidor la devuelve ya con hora y nombre
            with self.lock:
                self.stream.write("\x1b[1A\r\x1b[K")
                self.stream.flush()
            return line
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        return line.rstrip("\r\n")


# --------------------------------------------------------------------------- #
# Red: IPs locales y TLS
# --------------------------------------------------------------------------- #

VIRTUAL_IFACES = ("docker", "br-", "veth", "virbr", "vmnet", "vboxnet", "lxc", "tun", "tap", "zt", "wg")


def primary_ip():
    """IP de la interfaz con ruta por defecto (UDP connect: no envía ningún paquete)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1: solo sirve para elegir la ruta
            ip = s.getsockname()[0]
        finally:
            s.close()
        return None if ip.startswith("127.") or ip == "0.0.0.0" else ip
    except OSError:
        return None


def local_ips():
    """Lista (interfaz, IPv4): primero la de la ruta por defecto, al final las virtuales."""
    found = []
    if shutil.which("ip"):
        try:
            out = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True,
                                 text=True, timeout=5).stdout
            for row in out.splitlines():
                parts = row.split()
                if len(parts) >= 4 and parts[2] == "inet" and parts[1] != "lo":
                    ip = parts[3].split("/")[0]
                    if not ip.startswith("127."):
                        found.append((parts[1], ip))
        except (OSError, subprocess.SubprocessError):
            pass
    main = primary_ip()
    if not found:
        candidates = [main] if main else []
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                candidates.append(info[4][0])
        except OSError:
            pass
        for ip in candidates:
            if ip and not ip.startswith("127.") and ip not in [f[1] for f in found]:
                found.append(("", ip))

    def rank(item):
        name, ip = item
        return (ip != main, name.startswith(VIRTUAL_IFACES))
    return sorted(found, key=rank)


def fingerprint_of(der):
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def normalize_fp(fp):
    return re.sub(r"[^0-9A-Fa-f]", "", fp or "").upper()


def generate_cert(directory):
    """Certificado autofirmado de un solo uso (curva P-256, 30 días)."""
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError("openssl")
    cert = os.path.join(directory, "lanchat.crt")
    key = os.path.join(directory, "lanchat.key")
    subprocess.run([openssl, "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                    "-nodes", "-keyout", key, "-out", cert, "-days", "30", "-subj", "/CN=LanChat"],
                   check=True, capture_output=True, timeout=30)
    return cert, key


def server_tls_context(cert, key):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    with open(cert, encoding="ascii") as fh:
        der = ssl.PEM_cert_to_DER_cert(fh.read())
    return ctx, fingerprint_of(der)


def client_tls_context():
    # Sin CA: la confianza se basa en comparar la huella (como SSH).
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class KnownHosts:
    def __init__(self, path=None):
        self.path = path or os.path.join(config_dir(), "known_hosts.json")

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, host, port):
        return self._load().get("%s:%s" % (host, port))

    def put(self, host, port, fp):
        data = self._load()
        data["%s:%s" % (host, port)] = fp
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)


# --------------------------------------------------------------------------- #
# Servidor (asyncio: un solo hilo maneja todas las conexiones)
# --------------------------------------------------------------------------- #

class Member:
    def __init__(self, nick, ip, capable, host=False):
        self.nick = nick
        self.ip = ip
        self.capable = capable      # cliente LanChat: recibe su propio eco
        self.host = host
        self.tokens = float(RATE_BURST)
        self.stamp = time.monotonic()
        self.drops = 0
        self.reason = None          # por qué se fue: quit, idle, lost, kick, flood, slow, long
        self.quit_msg = ""

    @property
    def label(self):
        return ("@" if self.host else "") + self.nick

    def allow(self):
        now = time.monotonic()
        self.tokens = min(RATE_BURST, self.tokens + (now - self.stamp) * RATE_PER_SEC)
        self.stamp = now
        if self.tokens >= 1:
            self.tokens -= 1
            self.drops = 0
            return True
        self.drops += 1
        return False


class RemoteMember(Member):
    def __init__(self, nick, ip, capable, writer):
        super().__init__(nick, ip, capable)
        self.writer = writer

    def deliver(self, line):
        if self.writer.is_closing():
            return
        self.writer.write((line + "\n").encode("utf-8"))
        transport = self.writer.transport
        if transport.get_write_buffer_size() > MAX_WRITE_BUFFER:
            self.reason = self.reason or "slow"
            transport.abort()

    def close(self):
        if not self.writer.is_closing():
            self.writer.close()


class HostMember(Member):
    def __init__(self, nick, ui):
        super().__init__(nick, "local", True, host=True)
        self.ui = ui
        self.tokens = float("inf")

    def allow(self):
        return True

    def deliver(self, line):
        self.ui.show(line)

    def close(self):
        pass


class ChatServer:
    def __init__(self, bind="0.0.0.0", port=DEFAULT_PORT, lang="es", host_nick=None, ui=None,
                 password=None, tls=None, idle=DEFAULT_IDLE, max_clients=DEFAULT_MAX_CLIENTS,
                 log_path=None):
        self.bind = bind
        self.port = port
        self.t = I18n(lang)
        self.password = password or None
        self.tls = tls                  # (SSLContext, huella) o None
        self.idle = idle
        self.max_clients = max_clients
        self.log_path = log_path
        self.ui = ui
        self.members = {}               # nick.casefold() -> Member
        self.pending = 0
        self.loop = None
        self.server = None
        self.ready = threading.Event()
        self.stopped = None
        self.host = None
        self.shutting_down = False
        if host_nick:
            self.host = HostMember(host_nick, ui)
            self.members[host_nick.casefold()] = self.host

    # ---- utilidades ----
    def admin(self, text):
        """Avisos solo para el anfitrión (y el registro)."""
        line = "[%s] [i] %s" % (clock(), text)
        if self.ui is not None:
            self.ui.show(line)
        self.log(line)

    def log(self, line):
        if not self.log_path:
            return
        try:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%d ") + line + "\n")
        except OSError:
            pass

    def count(self):
        return len(self.members)

    def roster(self):
        people = sorted(self.members.values(), key=lambda m: (not m.host, m.nick.casefold()))
        return ", ".join(m.label for m in people)

    def broadcast(self, line, skip=None, log=True):
        for member in list(self.members.values()):
            if member is skip:
                continue
            member.deliver(line)
        if log:
            self.log(line)

    def system(self, text, kind="*", skip=None):
        self.broadcast("[%s] [%s] %s" % (clock(), kind, text), skip=skip)

    def tell(self, member, text, kind="*"):
        member.deliver("[%s] [%s] %s" % (clock(), kind, text))

    def nick_error(self, nick, me=None):
        if not valid_nick(nick):
            return self.t("nick_invalid", max=MAX_NICK)
        holder = self.members.get(nick.casefold())
        if holder is not None and holder is not me:
            return self.t("nick_taken")
        return None

    # ---- mensajes y comandos ----
    def process(self, member, raw):
        text = sanitize(raw)
        if not text:
            return
        if not member.allow():
            if member.drops >= FLOOD_KICK:
                member.reason = "flood"
                self.tell(member, self.t("flood_bye"), "!")
                member.close()
            else:
                self.tell(member, self.t("flood_warn"), "!")
            return
        if text.startswith("/") and not text.startswith("//"):
            self.command(member, text)
            return
        if text.startswith("//"):
            text = text[1:]
        self.say(member, text)

    def _cut(self, member, text):
        if len(text) > MAX_MSG:
            self.tell(member, self.t("truncated", max=MAX_MSG), "!")
            return text[:MAX_MSG]
        return text

    def say(self, member, text):
        text = self._cut(member, text)
        line = "[%s] <%s> %s" % (clock(), member.label, text)
        self.broadcast(line, skip=None if member.capable else member)

    def command(self, member, text):
        parts = text.split(None, 2)
        cmd = parts[0].lower()
        if cmd in ("/help", "/ayuda", "/?"):
            lines = self.t("help")
            if member.host:
                lines = lines + [self.t("help_host")]
            for line in lines:
                member.deliver("[%s] [*] %s" % (clock(), line))
        elif cmd in ("/who", "/quien", "/quién", "/names"):
            self.tell(member, self.t("in_room", n=self.count(), list=self.roster()))
        elif cmd == "/me":
            action = text[3:].strip()
            if action:
                line = "[%s] * %s %s" % (clock(), member.label, self._cut(member, action))
                self.broadcast(line, skip=None if member.capable else member)
        elif cmd in ("/msg", "/mp", "/privado", "/w"):
            if len(parts) < 3:
                self.tell(member, self.t("usage_msg"), "!")
                return
            target = self.members.get(parts[1].lstrip("@").casefold())
            if target is None:
                self.tell(member, self.t("no_such_nick", nick=parts[1]), "!")
                return
            if target is member:
                self.tell(member, self.t("msg_self"), "!")
                return
            body = self._cut(member, parts[2])
            line = "[%s] [MP] <%s → %s> %s" % (clock(), member.label, target.label, body)
            target.deliver(line)
            if member.capable:
                member.deliver(line)
            # el contenido de los privados no se guarda en el registro
            self.log("[%s] [MP] %s → %s" % (clock(), member.label, target.label))
        elif cmd == "/nick":
            if len(parts) < 2:
                self.tell(member, self.t("usage_nick"), "!")
                return
            new = parts[1]
            error = self.nick_error(new, member)
            if error:
                self.tell(member, error, "!")
                return
            old = member.label
            del self.members[member.nick.casefold()]
            member.nick = new
            self.members[new.casefold()] = member
            self.system(self.t("renamed", old=old, new=member.label))
        elif cmd in ("/quit", "/salir", "/exit", "/bye"):
            member.reason = "quit"
            member.quit_msg = text.split(None, 1)[1] if len(parts) > 1 else ""
            if member.host:
                self.request_stop()
            else:
                member.close()
        elif cmd in ("/kick", "/echar"):
            if not member.host:
                self.tell(member, self.t("host_only", cmd=cmd), "!")
                return
            if len(parts) < 2:
                self.tell(member, self.t("usage_kick"), "!")
                return
            target = self.members.get(parts[1].lstrip("@").casefold())
            if target is None:
                self.tell(member, self.t("no_such_nick", nick=parts[1]), "!")
                return
            if target is member:
                self.tell(member, self.t("cant_kick_host"), "!")
                return
            reason = " ".join(parts[2:])
            target.reason = "kick"
            self.tell(target, self.t("kicked_reason", reason=reason) if reason else self.t("kicked_you"), "!")
            target.close()
        else:
            self.tell(member, self.t("unknown_cmd", cmd=cmd), "!")

    # ---- conexiones ----
    async def _readline(self, reader, timeout):
        data = await asyncio.wait_for(reader.readline(), timeout)
        if not data:
            raise ConnectionError("eof")
        return data.decode("utf-8", "replace").rstrip("\r\n")

    def _send(self, writer, line):
        writer.write((line + "\n").encode("utf-8"))

    async def _refuse(self, writer, capable, text):
        self._send(writer, ("@BYE " if capable else "[-] ") + text)
        try:
            await asyncio.wait_for(writer.drain(), 2)
        except Exception:
            pass
        writer.close()

    async def _handshake(self, reader, writer, ip):
        t = self.t
        self._send(writer, "[?] " + (t("ask_password") if self.password else t("ask_nick")))
        first = await self._readline(reader, HANDSHAKE_TIMEOUT)
        capable = first.startswith(HELLO)
        if capable:
            nick = sanitize(first[len(HELLO):])
        else:
            # con contraseña, lo primero que escribe un ncat es la contraseña
            nick = None if self.password else sanitize(first)

        if self.password:
            # ncat: su primera línea ya es la respuesta a «[?] Contraseña»
            answer = None if capable else first
            if capable:
                self._send(writer, "@AUTH")
            for attempt in range(3):
                if answer is None:
                    answer = await self._readline(reader, HANDSHAKE_TIMEOUT)
                if hmac.compare_digest(answer.encode("utf-8"), self.password.encode("utf-8")):
                    break
                self.admin("%s %s" % (ip, t("bad_password")))
                await asyncio.sleep(1)
                if attempt < 2:
                    # una sola petición por intento: el cliente responde a @FAIL con otra contraseña
                    self._send(writer, ("@FAIL " + t("bad_password")) if capable else
                               ("[!] %s %s" % (t("bad_password"), t("ask_password"))))
                answer = None
            else:
                await self._refuse(writer, capable, t("too_many_tries"))
                return None
            if not capable:
                self._send(writer, "[?] " + t("ask_nick"))

        if nick is None:
            nick = sanitize(await self._readline(reader, HANDSHAKE_TIMEOUT))
        for attempt in range(3):
            error = self.nick_error(nick)
            if not error:
                break
            if attempt == 2:
                await self._refuse(writer, capable, error)
                return None
            self._send(writer, ("@NICK " + error) if capable else ("[?] %s %s" % (error, t("ask_nick"))))
            nick = sanitize(await self._readline(reader, HANDSHAKE_TIMEOUT))
        if self.count() >= self.max_clients + (1 if self.host else 0):
            await self._refuse(writer, capable, t("room_full", max=self.max_clients))
            return None
        return RemoteMember(nick, ip, capable, writer)

    async def _on_client(self, reader, writer):
        peer = writer.get_extra_info("peername") or ("?", 0)
        ip = peer[0]
        if self.count() + self.pending >= self.max_clients + (1 if self.host else 0):
            await self._refuse(writer, False, self.t("room_full", max=self.max_clients))
            self.admin("%s → %s" % (ip, self.t("room_full", max=self.max_clients)))
            return
        self.pending += 1
        member = None
        try:
            try:
                member = await self._handshake(reader, writer, ip)
            except (asyncio.TimeoutError, ConnectionError, OSError, ValueError, asyncio.LimitOverrunError):
                member = None
            finally:
                self.pending -= 1
            if member is None:
                if not writer.is_closing():
                    writer.close()
                return
            self.members[member.nick.casefold()] = member
            t = self.t
            if member.capable:
                member.deliver("@WELCOME " + member.nick)
            if self.host:
                self.tell(member, t("welcome", host=self.host.label, nick=member.nick))
            else:
                self.tell(member, t("welcome_headless", nick=member.nick))
            self.tell(member, t("in_room", n=self.count(), list=self.roster()))
            self.system(t("joined", nick=member.label, ip=member.ip, n=self.count()), "+", skip=member)
            while not writer.is_closing():
                try:
                    line = await self._readline(reader, self.idle or None)
                except asyncio.TimeoutError:
                    member.reason = "idle"
                    self.tell(member, t("idle_bye", min=max(1, round(self.idle / 60))), "!")
                    break
                except ValueError:  # la línea supera MAX_LINE
                    member.reason = "long"
                    self.tell(member, t("line_bye", max=MAX_LINE), "!")
                    break
                except (ConnectionError, OSError, asyncio.IncompleteReadError):
                    break
                self.process(member, line)
        finally:
            if member is not None:
                self._leave(member)
            if not writer.is_closing():
                writer.close()

    def _leave(self, member):
        if self.members.get(member.nick.casefold()) is not member:
            return
        del self.members[member.nick.casefold()]
        member.close()
        if self.shutting_down:
            return
        n = self.count()
        reason = member.reason or "lost"
        if reason == "quit":
            text = self.t("left_msg", nick=member.label, msg=sanitize(member.quit_msg, MAX_MSG), n=n) \
                if member.quit_msg else self.t("left", nick=member.label, n=n)
        else:
            text = self.t("left_" + reason, nick=member.label, n=n)
        self.system(text, "-")

    # ---- arranque y parada ----
    async def serve(self):
        self.loop = asyncio.get_running_loop()
        self.stopped = asyncio.Event()
        kwargs = {"limit": MAX_LINE, "reuse_address": True}
        if self.tls:
            kwargs["ssl"] = self.tls[0]
            kwargs["ssl_handshake_timeout"] = 10
        self.server = await asyncio.start_server(self._on_client, self.bind, self.port, **kwargs)
        self.port = self.server.sockets[0].getsockname()[1]
        self.loop.set_exception_handler(self._quiet_errors)
        self.ready.set()
        try:
            await self.stopped.wait()
        finally:
            await self._shutdown()

    def _quiet_errors(self, loop, context):
        # Los fallos de TLS de clientes sin cifrado no deben ensuciar la consola.
        exc = context.get("exception")
        if isinstance(exc, (ssl.SSLError, ConnectionError, OSError)):
            if self.ui is not None and isinstance(exc, ssl.SSLError):
                self.admin("TLS: %s" % (getattr(exc, "reason", None) or exc))
            return
        loop.default_exception_handler(context)

    async def _shutdown(self):
        self.shutting_down = True
        closing = self.t("server_closed")
        for member in list(self.members.values()):
            if isinstance(member, RemoteMember):
                member.deliver("[%s] [!] %s" % (clock(), closing))
                if member.capable:
                    member.deliver("@CLOSE")
                member.reason = "quit"
                member.close()
        self.log("[%s] [!] %s" % (clock(), closing))
        self.server.close()
        await asyncio.sleep(0.2)

    def request_stop(self):
        if self.loop and self.stopped is not None:
            self.loop.call_soon_threadsafe(self.stopped.set)

    def submit(self, member, text, wait=False):
        """Llamado desde otro hilo (la consola del anfitrión). Con wait=True vuelve
        cuando el mensaje ya se ha procesado y su eco está en pantalla."""
        if not wait:
            self.loop.call_soon_threadsafe(self.process, member, text)
            return

        async def run():
            self.process(member, text)
        try:
            asyncio.run_coroutine_threadsafe(run(), self.loop).result(2)
        except Exception:
            pass

    def start_in_thread(self):
        errors = []

        def runner():
            try:
                asyncio.run(self.serve())
            except Exception as exc:  # se informa al hilo principal
                errors.append(exc)
                self.ready.set()

        thread = threading.Thread(target=runner, name="lanchat-server", daemon=True)
        thread.start()
        self.ready.wait(15)
        if errors:
            raise errors[0]
        return thread


# --------------------------------------------------------------------------- #
# Cliente (bloqueante: el hilo de red es el único que toca el socket)
# --------------------------------------------------------------------------- #

class LineSocket:
    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

    def readline(self):
        while b"\n" not in self.buf:
            data = self.sock.recv(4096)
            if not data:
                raise ConnectionError("eof")
            self.buf += data
            if len(self.buf) > 64 * 1024:
                raise ConnectionError("line too long")
        line, self.buf = self.buf.split(b"\n", 1)
        return sanitize(line.decode("utf-8", "replace"))

    def send(self, text):
        self.sock.sendall((text + "\n").encode("utf-8"))


class ChatClient:
    def __init__(self, host, port, nick, lang="es", tls=False, fingerprint=None, password=None,
                 ui=None, out=None, known_hosts=None, ask=None):
        self.host = host
        self.port = port
        self.nick = nick
        self.t = I18n(lang)
        self.tls = tls
        self.fingerprint = normalize_fp(fingerprint) if fingerprint else None
        self.password = password
        self.ui = ui
        self.out = out or (lambda line: print(line, flush=True))
        self.known = known_hosts or KnownHosts()
        self.ask = ask                  # función(pregunta) -> respuesta, o None si no es interactivo
        self.outbox = []
        self.outbox_lock = threading.Lock()
        self.wake_r, self.wake_w = socket.socketpair()
        self.closed = threading.Event()
        self.lines = None

    def connect(self):
        try:
            return self._connect()
        except BaseException:
            self.release()
            raise

    def release(self):
        for s in (getattr(self, "sock", None), self.wake_r, self.wake_w):
            try:
                if s is not None:
                    s.close()
            except OSError:
                pass

    def _connect(self):
        t = self.t
        self.sock = None
        raw = socket.create_connection((self.host, self.port), timeout=10)
        self.sock = raw
        sock = raw
        if self.tls:
            try:
                sock = client_tls_context().wrap_socket(raw)
            except (ssl.SSLError, OSError) as exc:
                raw.close()
                raise RuntimeError(t("tls_failed", err=getattr(exc, "reason", None) or exc))
            self.sock = sock
            fp = fingerprint_of(sock.getpeercert(binary_form=True))
            self._check_fingerprint(fp)
        sock.settimeout(HANDSHAKE_TIMEOUT + 5)
        self.lines = LineSocket(sock)
        self.lines.send(HELLO + self.nick)
        while True:
            try:
                line = self.lines.readline()
            except (ConnectionError, OSError, socket.timeout):
                raise RuntimeError(t("not_lanchat"))
            if line.startswith("[?]"):
                continue
            if line == "@AUTH" or line.startswith("@FAIL "):
                if line.startswith("@FAIL "):
                    self.out("[!] " + line[6:])
                    self.password = None
                if self.password is None:
                    if self.ask is None:
                        raise RuntimeError(t("bad_password"))
                    self.password = self.ask(t("password_prompt"), secret=True)
                self.lines.send(self.password)
                continue
            if line.startswith("@NICK "):
                self.out("[!] " + line[6:])
                if self.ask is None:
                    raise RuntimeError(line[6:])
                self.nick = sanitize(self.ask(t("nick_retry") + ": ")) or self.nick
                self.lines.send(self.nick)
                continue
            if line.startswith("@BYE "):
                raise RuntimeError(line[5:])
            if line.startswith("@WELCOME "):
                self.nick = line[9:]
                break
            raise RuntimeError(t("not_lanchat"))
        sock.settimeout(None)
        if self.ui is not None:
            self.ui.me = self.nick
        return sock

    def _check_fingerprint(self, fp):
        t = self.t
        self.out("[*] " + t("fp_seen"))
        self.out("[*] " + fp)
        if self.fingerprint:
            if normalize_fp(fp) != self.fingerprint:
                raise RuntimeError(t("fp_mismatch"))
            self.known.put(self.host, self.port, fp)
            return
        old = self.known.get(self.host, self.port)
        if old == fp:
            self.out("[*] " + t("fp_known", host=self.host, port=self.port))
            return
        if old:
            for row in t("fp_changed", old=old, new=fp):
                self.out("[!] " + row)
        if self.ask is None:
            if old:
                raise RuntimeError(t("fp_rejected"))
            return  # sin terminal (pruebas, scripts): se acepta sin guardar
        if not is_yes(t, self.ask(t("fp_confirm") + " ")):
            raise RuntimeError(t("fp_rejected"))
        try:
            self.known.put(self.host, self.port, fp)
            self.out("[*] " + t("fp_saved", path=self.known.path))
        except OSError:
            pass

    def send(self, text):
        with self.outbox_lock:
            self.outbox.append(text)
        try:
            self.wake_w.send(b"x")
        except OSError:
            pass

    def close(self):
        self.closed.set()
        try:
            self.wake_w.send(b"x")
        except OSError:
            pass

    def network_loop(self, sock, on_line, on_end):
        """Único hilo que lee y escribe en el socket (TLS no admite dos a la vez)."""
        lines = self.lines
        try:
            for line in self._drain_buffer(lines):
                on_line(line)
            while not self.closed.is_set():
                ready = [sock] if (self.tls and sock.pending()) else \
                    select.select([sock, self.wake_r], [], [])[0]
                if self.wake_r in ready:
                    self.wake_r.recv(1024)
                    with self.outbox_lock:
                        batch, self.outbox = self.outbox, []
                    for text in batch:
                        lines.send(text)
                if sock in ready:
                    data = sock.recv(4096)
                    if not data:
                        break
                    lines.buf += data
                    for line in self._drain_buffer(lines):
                        on_line(line)
            with self.outbox_lock:
                for text in self.outbox:
                    lines.send(text)
                self.outbox = []
        except (OSError, ConnectionError, ssl.SSLError):
            pass
        finally:
            self.release()
            on_end()

    @staticmethod
    def _drain_buffer(lines):
        out = []
        while b"\n" in lines.buf:
            line, lines.buf = lines.buf.split(b"\n", 1)
            out.append(sanitize(line.decode("utf-8", "replace")))
        if len(lines.buf) > 64 * 1024:
            lines.buf = b""
        return out


# --------------------------------------------------------------------------- #
# Interfaz de consola
# --------------------------------------------------------------------------- #

def ask(prompt, default=None, secret=False):
    shown = "%s [%s]: " % (prompt, default) if default not in (None, "") else (
        prompt if prompt.endswith(" ") else prompt + ": ")
    value = getpass.getpass(shown) if secret else input(shown)
    value = value.strip() if not secret else value
    return value if value else (default if default is not None else "")


def is_yes(t, answer):
    answer = (answer or "").strip().lower()
    return bool(answer) and answer[0] in t("yes_chars")


def ask_port(t, default):
    while True:
        value = ask(t("port"), str(default))
        if value.isdigit() and 1 <= int(value) <= 65535:
            return int(value)
        print("[!] " + t("port_invalid"))


def ask_nick(t, default):
    while True:
        value = ask(t("nick"), default)
        if valid_nick(value):
            return value
        print("[!] " + t("nick_invalid", max=MAX_NICK))


def run_server(args, t, lang):
    depth = color_support(force_off=args.no_color)
    interactive = not args.no_input and sys.stdin.isatty()
    ui = TerminalUI(depth, me=args.nick)
    ui.interactive = ui.interactive and interactive
    tmpdir = None
    tls = None
    try:
        if args.tls:
            if args.cert and args.key:
                cert, key = args.cert, args.key
            else:
                tmpdir = tempfile.mkdtemp(prefix="lanchat-")
                cert, key = generate_cert(tmpdir)
            tls = server_tls_context(cert, key)
        password = os.environ.get("LANCHAT_PASSWORD") or None
        if args.ask_password:
            password = getpass.getpass(t("password_prompt")) or None
        server = ChatServer(bind=args.bind, port=args.port, lang=lang,
                            host_nick=args.nick if interactive else None,
                            ui=ui, password=password, tls=tls,
                            idle=args.idle, max_clients=args.max_clients, log_path=args.log)
        try:
            server.start_in_thread()
        except OSError as exc:
            import errno
            if exc.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1)):
                print("[-] " + t("port_busy", port=args.port), file=sys.stderr)
            elif exc.errno in (errno.EACCES, errno.EPERM):
                print("[-] " + t("port_denied", port=args.port), file=sys.stderr)
            else:
                print("[-] " + t("bind_failed", addr=args.bind, port=args.port, err=exc), file=sys.stderr)
            return 2
        addr = args.bind if args.bind not in ("0.0.0.0", "") else (
            primary_ip() or (local_ips() or [("", "0.0.0.0")])[0][1])
        say = ui.show
        say("[*] " + t("listening", addr=args.bind, port=server.port, tls=t("tls_on") if tls else ""))
        ncat = "ncat %s%s %d" % ("--ssl " if tls else "", addr, server.port)
        say("[*] " + t("how_to_join", addr=addr, port=server.port, ncat=ncat))
        if tls:
            say("[*] " + t("fingerprint_srv"))
            say("[*] " + tls[1])
        elif password:
            say("[!] " + t("password_cleartext"))
        if not interactive:
            try:
                while not server.stopped.is_set():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
            server.request_stop()
            time.sleep(0.4)
            return 0
        ui.show("[*] " + t("write_hint"))
        try:
            while True:
                text = ui.read()
                if text.strip():
                    server.submit(server.host, text, wait=True)
                    if sanitize(text).split(" ", 1)[0].lower() in ("/quit", "/salir", "/exit", "/bye"):
                        break
        except (KeyboardInterrupt, EOFError):
            sys.stdout.write("\r\x1b[K")
        server.request_stop()
        time.sleep(0.4)
        print("[*] " + t("bye"))
        return 0
    except (RuntimeError, subprocess.SubprocessError, ssl.SSLError) as exc:
        if str(exc) == "openssl":
            print("[-] " + t("no_openssl"), file=sys.stderr)
        else:
            print("[-] %s" % exc, file=sys.stderr)
        return 2
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def run_client(args, t, lang):
    depth = color_support(force_off=args.no_color)
    ui = TerminalUI(depth, me=args.nick)
    interactive = ui.interactive
    password = os.environ.get("LANCHAT_PASSWORD") or None

    def asker(prompt, secret=False):
        try:
            return getpass.getpass(prompt) if secret else input(prompt)
        finally:
            ui.reading = False  # el gancho de readline también salta con estas preguntas

    client = ChatClient(args.host, args.port, args.nick, lang=lang, tls=args.tls,
                        fingerprint=args.fingerprint, password=password, ui=ui,
                        out=ui.show, ask=asker if interactive else None)
    ui.show("[*] " + t("connecting", host=args.host, port=args.port,
                         tls=t("tls_on") if args.tls else "", nick=args.nick))
    try:
        sock = client.connect()
    except RuntimeError as exc:
        ui.show("[-] %s" % exc)
        return 1
    except (OSError, socket.timeout) as exc:
        ui.show("[-] " + t("connect_failed", host=args.host, port=args.port,
                            err=getattr(exc, "strerror", None) or exc))
        return 1

    state = {"server_closed": False, "leaving": False}
    replied = threading.Event()

    def on_line(line):
        if line.startswith("@"):        # control del protocolo, no se muestra
            if line == "@CLOSE":
                state["server_closed"] = True
            return
        ui.show(line)
        replied.set()

    def on_end():
        if client.closed.is_set():
            return
        client.closed.set()
        if state["leaving"]:
            return
        if not state["server_closed"]:
            ui.show("[-] " + t("lost"))
        if interactive and os.name != "nt":
            os.kill(os.getpid(), signal.SIGINT)  # despierta el input() del hilo principal
        elif interactive:
            import _thread
            _thread.interrupt_main()

    net = threading.Thread(target=client.network_loop, args=(sock, on_line, on_end),
                           name="lanchat-net", daemon=True)
    net.start()
    try:
        while not client.closed.is_set():
            text = ui.read()
            if not text.strip():
                continue
            replied.clear()
            client.send(text)
            if sanitize(text).split(" ", 1)[0].lower() in ("/quit", "/salir", "/exit", "/bye"):
                break
            if interactive:
                # el servidor contesta a todo (eco, aviso o resultado): se espera para
                # que el prompt no se pinte justo antes de esa respuesta
                replied.wait(0.5)
    except (KeyboardInterrupt, EOFError):
        if not client.closed.is_set():
            client.send("/quit")
    # el servidor cierra tras /quit: se espera para no perder los últimos mensajes
    state["leaving"] = True
    try:
        net.join(3)
        client.close()
        net.join(2)
    except KeyboardInterrupt:
        client.close()
    if interactive:
        sys.stdout.write("\r\x1b[K")  # borra el «> » que queda a medias
    print("[*] " + t("bye"))
    return 0


def menu(args):
    enable_windows_ansi()
    if not sys.stdin.isatty():
        print(TEXTS["es"]["need_tty"] + " / " + TEXTS["en"]["need_tty"], file=sys.stderr)
        return 2
    conf = load_config()
    lang = detect_lang(args.lang)
    while True:
        t = I18n(lang)
        depth = color_support(force_off=args.no_color)
        if sys.stdout.isatty():
            print("\x1b[2J\x1b[H", end="")
        print(banner(t, depth))
        print(t("menu_title"))
        print("  1) " + t("menu_host"))
        print("  2) " + t("menu_join"))
        print("  3) " + t("menu_lang"))
        print("  0) " + t("menu_exit"))
        try:
            choice = ask(t("option"))
        except (KeyboardInterrupt, EOFError):
            print()
            return 0
        if choice == "3":
            lang = "en" if lang == "es" else "es"
            conf["lang"] = lang
            save_config(conf)
            continue
        if choice in ("0", "q"):
            return 0
        if choice not in ("1", "2"):
            continue
        try:
            if choice == "1":
                ips = local_ips()
                print()
                print(t("pick_iface"))
                options = [(name, ip) for name, ip in ips] + [("", "0.0.0.0")]
                for i, (name, ip) in enumerate(options, 1):
                    label = ip if ip != "0.0.0.0" else "0.0.0.0  (%s)" % t("all_ifaces")
                    print("  %d) %-16s %s" % (i, label, name))
                while True:
                    pick = ask(t("option"), "1")
                    if pick.isdigit() and 1 <= int(pick) <= len(options):
                        break
                    print("[!] " + t("invalid_option"))
                bind = options[int(pick) - 1][1]
                port = ask_port(t, conf.get("port", DEFAULT_PORT))
                nick = ask_nick(t, conf.get("nick", ""))
                password = ask(t("room_password"), secret=True) or None
                use_tls = False
                if shutil.which("openssl"):
                    use_tls = is_yes(t, ask(t("use_tls")))
                conf.update(port=port, nick=nick, lang=lang)
                save_config(conf)
                if password:
                    os.environ["LANCHAT_PASSWORD"] = password
                else:
                    os.environ.pop("LANCHAT_PASSWORD", None)
                ns = argparse.Namespace(bind=bind, port=port, nick=nick, tls=use_tls, cert=None, key=None,
                                        idle=DEFAULT_IDLE, max_clients=DEFAULT_MAX_CLIENTS, log=None,
                                        no_input=False, ask_password=False, no_color=args.no_color)
                print()
                return run_server(ns, t, lang)
            host = ""
            while not valid_host(host):
                host = ask(t("server_ip"), conf.get("server", ""))
                if not valid_host(host):
                    print("[!] " + t("server_ip_invalid"))
            port = ask_port(t, conf.get("port", DEFAULT_PORT))
            nick = ask_nick(t, conf.get("nick", ""))
            use_tls = is_yes(t, ask(t("use_tls_join")))
            conf.update(server=host, port=port, nick=nick, tls=use_tls, lang=lang)
            save_config(conf)
            ns = argparse.Namespace(host=host, port=port, nick=nick, tls=use_tls, fingerprint=None,
                                    no_color=args.no_color)
            print()
            return run_client(ns, t, lang)
        except (KeyboardInterrupt, EOFError):
            print()
            return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="lanchat",
        description="LanChat v%s — chat de texto para tu red local / text chat for your LAN. %s" % (VERSION, WEB))
    p.add_argument("--lang", choices=("es", "en"), help="idioma / language")
    p.add_argument("--no-color", action="store_true", help="sin colores / no colours")
    # las mismas opciones valen también detrás del subcomando
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--lang", choices=("es", "en"), default=argparse.SUPPRESS, help="idioma / language")
    common.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS,
                        help="sin colores / no colours")
    sub = p.add_subparsers(dest="mode")

    s = sub.add_parser("serve", parents=[common], help="crear una sala / create a room")
    s.add_argument("--bind", default="0.0.0.0", help="IP donde escuchar (por defecto todas)")
    s.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)
    s.add_argument("--nick", "-n", default="host", help="tu nombre como anfitrión")
    s.add_argument("--tls", action="store_true", help="cifrar con TLS (certificado autofirmado temporal)")
    s.add_argument("--cert", help="certificado PEM propio (con --tls)")
    s.add_argument("--key", help="clave PEM propia (con --tls)")
    s.add_argument("--ask-password", action="store_true",
                   help="pedir contraseña de sala (o variable LANCHAT_PASSWORD)")
    s.add_argument("--idle", type=int, default=DEFAULT_IDLE, help="segundos sin escribir antes de desconectar (0 = nunca)")
    s.add_argument("--max-clients", type=int, default=DEFAULT_MAX_CLIENTS)
    s.add_argument("--log", help="guardar la conversación pública en este archivo")
    s.add_argument("--no-input", action="store_true", help="solo servidor, sin participar en el chat")

    j = sub.add_parser("join", parents=[common], help="unirse a una sala / join a room")
    j.add_argument("host", help="IP o nombre del servidor")
    j.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)
    j.add_argument("--nick", "-n", required=True)
    j.add_argument("--tls", action="store_true")
    j.add_argument("--fingerprint", help="huella SHA-256 esperada del servidor")

    sub.add_parser("banner", parents=[common], help=argparse.SUPPRESS)
    sub.add_parser("ips", parents=[common], help="mostrar las IP locales / show local IPs")
    return p


def main(argv=None):
    utf8_streams()
    args = build_parser().parse_args(argv)
    enable_windows_ansi()
    lang = detect_lang(args.lang)
    t = I18n(lang)
    if args.mode is None:
        return menu(args)
    if args.mode == "banner":
        print(banner(t, color_support(force_off=args.no_color)))
        return 0
    if args.mode == "ips":
        for name, ip in local_ips():
            print("%-16s %s" % (ip, name))
        return 0
    if not 1 <= args.port <= 65535 and not (args.mode == "serve" and args.port == 0):
        print("[-] " + t("port_invalid"), file=sys.stderr)
        return 2
    if args.mode == "serve":
        if args.bind and args.bind != "0.0.0.0":
            try:
                ipaddress.ip_address(args.bind)
            except ValueError:
                print("[-] " + t("server_ip_invalid"), file=sys.stderr)
                return 2
        if not valid_nick(args.nick):
            print("[-] " + t("nick_invalid", max=MAX_NICK), file=sys.stderr)
            return 2
        return run_server(args, t, lang)
    if not valid_host(args.host):
        print("[-] " + t("server_ip_invalid"), file=sys.stderr)
        return 2
    if not valid_nick(args.nick):
        print("[-] " + t("nick_invalid", max=MAX_NICK), file=sys.stderr)
        return 2
    return run_client(args, t, lang)


if __name__ == "__main__":
    sys.exit(main())

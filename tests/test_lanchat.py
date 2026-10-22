"""Pruebas de LanChat: servidores reales en 127.0.0.1 y clientes por socket.

    python -m unittest discover -s tests -v
"""

import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import lanchat  # noqa: E402

LINE = r"^\[\d\d:\d\d\] "


class Collector:
    """UI falsa para el anfitrión: guarda lo que se le muestra."""

    def __init__(self):
        self.lines = []
        self.lock = threading.Lock()

    def show(self, line):
        with self.lock:
            self.lines.append(line)

    def wait_for(self, pattern, timeout=3):
        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                for line in self.lines:
                    if re.search(pattern, line):
                        return line
            time.sleep(0.02)
        raise AssertionError("el anfitrión no vio %r; vio: %r" % (pattern, self.lines))


class Raw:
    """Cliente crudo, como un `ncat IP PUERTO`."""

    def __init__(self, port, tls=False):
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        if tls:
            sock = lanchat.client_tls_context().wrap_socket(sock)
        self.sock = sock
        self.buf = b""
        self.seen = []

    def send(self, text):
        self.sock.sendall(text.encode("utf-8") + b"\n")

    def send_raw(self, data):
        self.sock.sendall(data)

    def line(self, timeout=3):
        self.sock.settimeout(timeout)
        while b"\n" not in self.buf:
            data = self.sock.recv(4096)
            if not data:
                raise EOFError
            self.buf += data
        line, self.buf = self.buf.split(b"\n", 1)
        text = line.decode("utf-8", "replace")
        self.seen.append(text)
        return text

    def expect(self, pattern, timeout=3):
        end = time.time() + timeout
        while True:
            left = end - time.time()
            if left <= 0:
                raise AssertionError("no llegó %r; llegó: %r" % (pattern, self.seen))
            try:
                line = self.line(left)
            except socket.timeout:
                raise AssertionError("no llegó %r; llegó: %r" % (pattern, self.seen))
            if re.search(pattern, line):
                return line

    def quiet(self, wait=0.4):
        """Lee todo lo que llegue durante `wait` segundos."""
        out = []
        end = time.time() + wait
        while time.time() < end:
            try:
                out.append(self.line(max(0.01, end - time.time())))
            except (socket.timeout, EOFError):
                break
        return out

    def closed(self, timeout=3):
        end = time.time() + timeout
        while time.time() < end:
            try:
                self.line(max(0.01, end - time.time()))
            except (EOFError, ConnectionError):
                return True
            except socket.timeout:
                return False
        return False

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class ServerCase(unittest.TestCase):
    server_kwargs = {}
    with_host = False

    def setUp(self):
        self.host_ui = Collector() if self.with_host else None
        kwargs = dict(bind="127.0.0.1", port=0, lang="es", idle=30)
        kwargs.update(self.server_kwargs)
        if self.with_host:
            kwargs.update(host_nick="profe", ui=self.host_ui)
        self.server = lanchat.ChatServer(**kwargs)
        self.thread = self.server.start_in_thread()
        self.port = self.server.port
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.server.request_stop()
        self.thread.join(5)

    def join(self, nick, capable=False):
        c = Raw(self.port)
        self.clients.append(c)
        if capable:
            c.send(lanchat.HELLO + nick)
            c.expect(r"^@WELCOME " + re.escape(nick) + "$")
        else:
            c.expect(r"^\[\?\] ")
            c.send(nick)
        c.expect(r"\[\*\] En la sala")
        return c


class SanitizeTests(unittest.TestCase):
    def test_quita_controles_y_bidi(self):
        dirty = "a\x1b[31mb\x07c\r\x1b]0;titulo\x07d\u202ee\u200bf"
        self.assertEqual(lanchat.sanitize(dirty), "a[31mbc]0;titulode" + "f")

    def test_conserva_tildes_y_emojis(self):
        text = "Peña ñandú 😀 👩\u200d💻"
        self.assertEqual(lanchat.sanitize(text), text)

    def test_tabulador_y_limite(self):
        self.assertEqual(lanchat.sanitize("a\tb"), "a b")
        self.assertEqual(lanchat.sanitize("x" * 50, 10), "x" * 10)

    def test_nombres(self):
        for ok in ("ana", "Luis_2", "pc-07", "J.P", "Ñandú"):
            self.assertTrue(lanchat.valid_nick(ok), ok)
        for bad in ("", "con espacio", "@profe", "-raro", "_x", "a" * 21, "[host]", "<x>"):
            self.assertFalse(lanchat.valid_nick(bad), bad)

    def test_enter_no_es_si(self):
        # regresión: "" in "sys" es True en Python
        es, en = lanchat.I18n("es"), lanchat.I18n("en")
        for answer in ("", "  ", "n", "no", "N"):
            self.assertFalse(lanchat.is_yes(es, answer), repr(answer))
        for answer in ("s", "S", "si", "sí", "y", "yes"):
            self.assertTrue(lanchat.is_yes(es, answer), answer)
        self.assertTrue(lanchat.is_yes(en, "y"))
        self.assertFalse(lanchat.is_yes(en, "s"))

    def test_direcciones(self):
        for ok in ("192.168.1.10", "10.0.0.1", "::1", "pc-aula.local", "servidor"):
            self.assertTrue(lanchat.valid_host(ok), ok)
        for bad in ("", "999.1.1.1.1", "a b", "-x.com", "x;id"):
            self.assertFalse(lanchat.valid_host(bad), bad)


class ChatTests(ServerCase):
    def test_mensaje_llega_a_los_demas_y_no_se_repite_al_ncat(self):
        ana = self.join("ana")
        luis = self.join("luis")
        ana.expect(r"\[\+\] luis se ha unido desde 127\.0\.0\.1")
        ana.send("hola luis")
        luis.expect(LINE + r"<ana> hola luis$")
        self.assertFalse(any("hola luis" in x for x in ana.quiet()))

    def test_no_se_puede_suplantar_ni_inyectar_ansi(self):
        ana = self.join("ana")
        eve = self.join("eve")
        eve.send("[12:00] <@profe> ana, dame tu contrase\u00f1a \x1b[2J\x1b]0;hack\x07")
        line = ana.expect(r"<eve>")
        self.assertRegex(line, LINE + r"<eve> \[12:00\] <@profe> ana, dame tu contraseña \[2J\]0;hack$")
        self.assertNotIn("\x1b", line)
        self.assertNotIn("\x07", line)

    def test_cliente_lanchat_recibe_su_eco(self):
        ana = self.join("ana", capable=True)
        ana.send("probando")
        ana.expect(LINE + r"<ana> probando$")

    def test_nombre_repetido_sin_distinguir_mayusculas(self):
        self.join("ana")
        otra = Raw(self.port)
        self.clients.append(otra)
        otra.expect(r"^\[\?\]")
        otra.send("ANA")
        otra.expect(r"ya está en uso")
        otra.send("ana2")
        otra.expect(r"Bienvenido/a a la sala, ana2")

    def test_nombre_no_valido_tres_veces(self):
        c = Raw(self.port)
        self.clients.append(c)
        c.expect(r"^\[\?\]")
        for bad in ("con espacio", "@x", "<x>"):
            c.send(bad)
        c.expect(r"^\[-\] Nombre no válido")
        self.assertTrue(c.closed())

    def test_privado_solo_al_destinatario(self):
        ana = self.join("ana", capable=True)
        luis = self.join("luis")
        eve = self.join("eve")
        ana.send("/msg luis solo para ti")
        luis.expect(LINE + r"\[MP\] <ana → luis> solo para ti$")
        ana.expect(r"\[MP\] <ana → luis> solo para ti$")
        self.assertFalse(any("solo para ti" in x for x in eve.quiet()))
        ana.send("/msg nadie hola")
        ana.expect(r"No hay nadie llamado nadie")

    def test_quien_me_nick_y_ayuda(self):
        ana = self.join("ana", capable=True)
        luis = self.join("luis")
        ana.send("/quien")
        ana.expect(r"En la sala \(2\): ana, luis")
        ana.send("/me saluda")
        luis.expect(LINE + r"\* ana saluda$")
        ana.send("/nick anita")
        luis.expect(r"ana ahora se llama anita")
        luis.send("/nick anita")
        luis.expect(r"ya está en uso")
        luis.send("/ayuda")
        luis.expect(r"/msg NOMBRE texto")
        luis.send("/kick anita")
        luis.expect(r"Solo el anfitrión puede usar /kick")
        luis.send("//no soy un comando")
        ana.expect(r"<luis> /no soy un comando$")
        luis.send("/patata")
        luis.expect(r"Comando desconocido: /patata")

    def test_salir_con_mensaje(self):
        ana = self.join("ana")
        luis = self.join("luis")
        luis.send("/salir me voy a comer")
        ana.expect(r"\[-\] luis ha salido: me voy a comer \(1 en la sala\)")
        self.assertTrue(luis.closed())

    def test_mensaje_largo_se_recorta(self):
        ana = self.join("ana", capable=True)
        ana.send("x" * 600)
        ana.expect(r"Mensaje recortado a 400")
        line = ana.expect(r"<ana> x+$")
        self.assertEqual(line.count("x"), lanchat.MAX_MSG)

    def test_inundacion_avisa_y_expulsa(self):
        ana = self.join("ana")
        eve = self.join("eve")
        for i in range(40):
            try:
                eve.send("spam %d" % i)
            except OSError:  # el servidor ya la ha echado (Windows corta con RST)
                break
        ana.expect(r"\[-\] eve expulsado/a por inundar la sala")
        # ana no recibe la inundación entera: solo pasa la ráfaga permitida
        spam = [x for x in ana.seen if "<eve> spam" in x]
        self.assertLessEqual(len(spam), lanchat.RATE_BURST + 2)
        try:
            eve.expect(r"Vas demasiado rápido")
            eve.expect(r"Expulsado/a por inundar la sala")
        except (OSError, EOFError):
            pass  # en Windows el RST puede descartar lo pendiente de leer

    def test_linea_gigante_sin_salto_corta_la_conexion(self):
        ana = self.join("ana")
        eve = self.join("eve")
        try:
            eve.send_raw(b"A" * (lanchat.MAX_LINE * 3))
        except OSError:
            pass
        ana.expect(r"\[-\] eve desconectado/a: línea demasiado larga")


class IdleTests(ServerCase):
    server_kwargs = {"idle": 1}

    def test_inactividad(self):
        ana = self.join("ana")
        ana.expect(r"Desconectado/a tras 1 min sin escribir", timeout=4)
        self.assertTrue(ana.closed())


class PasswordTests(ServerCase):
    server_kwargs = {"password": "s3creta"}

    def test_ncat_con_contrasena(self):
        c = Raw(self.port)
        self.clients.append(c)
        c.expect(r"^\[\?\] Contraseña de la sala")
        c.send("s3creta")
        c.expect(r"^\[\?\] Escribe tu nombre")
        c.send("ana")
        c.expect(r"Bienvenido/a a la sala, ana")

    def test_tres_fallos_cierran(self):
        c = Raw(self.port)
        self.clients.append(c)
        c.expect(r"^\[\?\] Contraseña")
        for _ in range(3):
            c.send("mala")
        c.expect(r"^\[-\] Demasiados intentos", timeout=6)
        self.assertTrue(c.closed())

    def test_cliente_lanchat_pide_auth(self):
        c = Raw(self.port)
        self.clients.append(c)
        c.send(lanchat.HELLO + "ana")
        c.expect(r"^@AUTH$")
        c.send("s3creta")
        c.expect(r"^@WELCOME ana$")

    def test_reintento_no_pide_la_contrasena_dos_veces(self):
        # regresión: tras un fallo llegaban @FAIL y @AUTH, y la segunda copia
        # de la contraseña acababa usándose como nombre de usuario
        c = Raw(self.port)
        self.clients.append(c)
        c.send(lanchat.HELLO + "ana")
        c.expect(r"^@AUTH$")
        c.send("mala")
        c.expect(r"^@FAIL Contraseña incorrecta", timeout=4)
        c.send("s3creta")
        c.expect(r"^@WELCOME ana$")
        self.assertEqual([x for x in c.seen if x == "@AUTH"], ["@AUTH"])

    def test_ncat_reintenta_contrasena(self):
        c = Raw(self.port)
        self.clients.append(c)
        c.expect(r"^\[\?\] Contraseña")
        c.send("mala")
        c.expect(r"^\[!\] Contraseña incorrecta\. Contraseña de la sala:", timeout=4)
        c.send("s3creta")
        c.expect(r"^\[\?\] Escribe tu nombre")
        c.send("luis")
        c.expect(r"Bienvenido/a a la sala, luis")

    def test_cliente_real_con_contrasena(self):
        c = lanchat.ChatClient("127.0.0.1", self.port, "ana", password="s3creta", out=lambda line: None)
        sock = c.connect()
        self.assertEqual(c.nick, "ana")
        c.release()
        sock.close()
        mala = lanchat.ChatClient("127.0.0.1", self.port, "eve", password="mala", out=lambda line: None)
        with self.assertRaises(RuntimeError):
            mala.connect()


class FullRoomTests(ServerCase):
    server_kwargs = {"max_clients": 1}

    def test_sala_llena(self):
        self.join("ana")
        c = Raw(self.port)
        self.clients.append(c)
        c.expect(r"La sala está llena \(máximo 1\)")
        self.assertTrue(c.closed())


class HostTests(ServerCase):
    with_host = True

    def test_anfitrion_ve_y_expulsa(self):
        ana = self.join("ana", capable=True)
        self.assertTrue(any("Bienvenido/a a la sala de @profe, ana" in x for x in ana.seen))
        self.host_ui.wait_for(r"\[\+\] ana se ha unido")
        ana.send("hola profe")
        self.host_ui.wait_for(LINE + r"<ana> hola profe$")
        self.server.submit(self.server.host, "hola ana")
        ana.expect(LINE + r"<@profe> hola ana$")
        self.server.submit(self.server.host, "/kick ana por spam")
        ana.expect(r"El anfitrión te ha expulsado: por spam")
        self.host_ui.wait_for(r"\[-\] ana ha sido expulsado/a")
        self.assertTrue(ana.closed())

    def test_nadie_puede_llamarse_como_el_anfitrion(self):
        c = Raw(self.port)
        self.clients.append(c)
        c.expect(r"^\[\?\]")
        c.send("Profe")
        c.expect(r"ya está en uso")

    def test_cierre_avisa_a_los_clientes(self):
        ana = self.join("ana", capable=True)
        self.server.submit(self.server.host, "/salir")
        ana.expect(r"El servidor ha cerrado la sala")
        ana.expect(r"^@CLOSE$")


@unittest.skipUnless(shutil.which("openssl"), "hace falta openssl")
class TlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cert, key = lanchat.generate_cert(self.tmp)
        self.ctx, self.fp = lanchat.server_tls_context(cert, key)
        self.server = lanchat.ChatServer(bind="127.0.0.1", port=0, tls=(self.ctx, self.fp))
        self.thread = self.server.start_in_thread()
        self.known = lanchat.KnownHosts(os.path.join(self.tmp, "known.json"))

    def tearDown(self):
        self.server.request_stop()
        self.thread.join(5)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def client(self, nick, **kw):
        return lanchat.ChatClient("127.0.0.1", self.server.port, nick, tls=True,
                                  out=lambda line: None, known_hosts=self.known, **kw)

    def test_huella_correcta_y_conversacion_cifrada(self):
        c = self.client("ana", fingerprint=self.fp.lower())
        sock = c.connect()
        self.assertIsInstance(sock, ssl.SSLSocket)
        self.assertEqual(self.known.get("127.0.0.1", self.server.port), self.fp)
        got = []
        t = threading.Thread(target=c.network_loop, args=(sock, got.append, lambda: None), daemon=True)
        t.start()
        luis = Raw(self.server.port, tls=True)
        luis.expect(r"^\[\?\]")
        luis.send("luis")
        luis.expect(r"En la sala")
        c.send("hola cifrado")
        luis.expect(LINE + r"<ana> hola cifrado$")
        luis.send("recibido")
        end = time.time() + 3
        while time.time() < end and not any("<luis> recibido" in x for x in got):
            time.sleep(0.05)
        self.assertTrue(any("<luis> recibido" in x for x in got), got)
        c.close()
        t.join(3)
        luis.close()

    def test_huella_distinta_se_rechaza(self):
        c = self.client("ana", fingerprint="AA" * 32)
        with self.assertRaises(RuntimeError):
            c.connect()

    def test_huella_cambiada_sin_terminal_se_rechaza(self):
        self.known.put("127.0.0.1", self.server.port, "00:" * 31 + "00")
        with self.assertRaises(RuntimeError):
            self.client("ana").connect()

    def test_cliente_sin_tls_contra_sala_tls_no_entra(self):
        c = lanchat.ChatClient("127.0.0.1", self.server.port, "ana", out=lambda line: None)
        old = lanchat.HANDSHAKE_TIMEOUT
        lanchat.HANDSHAKE_TIMEOUT = 1
        try:
            with self.assertRaises((RuntimeError, OSError)):
                c.connect()
        finally:
            lanchat.HANDSHAKE_TIMEOUT = old


class CliTests(ServerCase):
    def test_join_desde_la_linea_de_comandos(self):
        ana = self.join("ana")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", NO_COLOR="1")
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "lanchat.py"), "join", "127.0.0.1",
             "-p", str(self.port), "-n", "bot"],
            input="hola desde la CLI\n/salir adiós\n", capture_output=True, text=True,
            encoding="utf-8", timeout=20, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ana.expect(LINE + r"<bot> hola desde la CLI$")
        ana.expect(r"\[-\] bot ha salido: adiós")
        self.assertIn("<bot> hola desde la CLI", proc.stdout)

    def test_banner_y_ayuda(self):
        t = lanchat.I18n("es")
        plain = lanchat.banner(t, depth=0)
        self.assertIn("unfantasmaenelsistema.com", plain)
        self.assertNotIn("\x1b", plain)
        color = lanchat.banner(t, depth=24, width=100)
        self.assertIn("▀", color)
        self.assertIn("38;2;", color)
        self.assertEqual(len(lanchat.art_lines(8)), len(lanchat._ART_ROWS) // 2)
        out = subprocess.run([sys.executable, os.path.join(ROOT, "lanchat.py"), "--help"],
                             capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(out.returncode, 0)
        self.assertIn("serve", out.stdout)

    def test_textos_completos_en_los_dos_idiomas(self):
        self.assertEqual(set(lanchat.TEXTS["es"]), set(lanchat.TEXTS["en"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Offline tests for cms_telnet_driver using a fake line-mode z/VM server."""
import socket
import threading
import time
import unittest

from cms_telnet_driver import CmsSession, CmsTimeout, strip_telnet


class FakeCmsServer(threading.Thread):
    def __init__(self, host="127.0.0.1"):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, 0))
        self.sock.listen(1)
        self.host, self.port = self.sock.getsockname()
        self.commands = []
        self.stop = False

    def send(self, obj, text):
        # mimic the 0x13 0x7f prefix and XON suffix
        obj.sendall(b"\r\n\x13\x7f" + text.encode() + b"\x11")

    def run(self):
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        conn.sendall(b"\xff\xfd\x28\xff\xfb\x03")
        self.send(conn, "z/VM ONLINE  --TACOTICO--PRESS BREAK KEY TO BEGIN SESSION.")
        buf = b""
        state = "banner"
        while not self.stop:
            try:
                conn.settimeout(2)
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                line = strip_telnet(line).decode("latin-1", "replace").strip()
                if not line:
                    continue
                self.commands.append(line)
                if state == "banner":
                    self.send(conn, "Enter password:")
                    state = "password"
                elif state == "password":
                    self.send(conn, "z/VM Version 6 Release 3.0")
                    self.send(conn, "RECONNECTED AT NOW")
                    self.send(conn, ".")
                    state = "cp"
                elif line == "IPL CMS":
                    self.send(conn, "z/VM V6.3.0")
                    self.send(conn, ".")
                    state = "cms"
                elif line == "QUERY CMSLEVEL":
                    if state == "cms":
                        self.send(conn, "Ready; T=0.01/0.01 12:00:00")
                        self.send(conn, "CMS Level 27, Service Level 1302")
                        self.send(conn, "Ready; T=0.01/0.01 12:00:00")
                    else:
                        self.send(conn, "Unknown CP/CMS command")
                    self.send(conn, ".")
                elif line == "BEGIN":
                    self.send(conn, "Ready; T=0.01/0.01 12:00:00")
                    state = "cms"
                    self.send(conn, ".")
                elif line == "QUERY DISK":
                    self.send(conn, "Ready; T=0.01/0.01 12:00:00")
                    for i in range(3):
                        self.send(conn, f"DISK{ i }")
                    self.send(conn, ".")
                elif line == "SLOW":
                    for i in range(3):
                        self.send(conn, f"step {i}")
                        time.sleep(0.6)
                    self.send(conn, "Ready; T=1.0/1.0 12:00:00")
                    self.send(conn, ".")
                elif line == "HANG":
                    self.send(conn, "working...")
                    # never send a prompt
                elif line == "HX":
                    self.send(conn, "HX accepted")
                    self.send(conn, ".")
                else:
                    self.send(conn, "Ready; T=0.01/0.01 12:00:00")
                    self.send(conn, ".")
        conn.close()

    def close(self):
        self.stop = True
        try:
            self.sock.close()
        except OSError:
            pass


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeCmsServer()
        self.server.start()
        time.sleep(0.1)
        self.lines = []
        self.session = CmsSession(
            "127.0.0.1", self.server.port,
            userid="MAINT", password="secret",
            on_line=self.lines.append,
        )
        self.session.connect()

    def tearDown(self):
        self.session.close()
        self.server.close()

    def test_login_and_probe(self):
        result = self.session.command("QUERY CMSLEVEL")
        self.assertIn("CMS Level 27", result.output)
        self.assertIsNone(result.rc)

    def test_multiline_command(self):
        result = self.session.command("QUERY DISK")
        self.assertIn("DISK0", result.output)
        self.assertIn("DISK2", result.output)

    def test_streaming(self):
        self.lines.clear()
        result = self.session.command("SLOW", timeout=10)
        self.assertIn("step 0", result.output)
        self.assertIn("step 2", result.output)
        self.assertTrue(any("step 0" in line for line in self.lines))

    def test_timeout_then_interrupt(self):
        with self.assertRaises(CmsTimeout):
            self.session.command("HANG", timeout=1.5)
        output = self.session.interrupt(timeout=5)
        self.assertIn("HX accepted", output)
        self.assertIn("HX", self.server.commands)

    def test_telnet_stripper(self):
        self.assertEqual(strip_telnet(b"\xff\xfd\x28hello\xff\xfb\x03"), b"hello")


if __name__ == "__main__":
    unittest.main(verbosity=2)

import unittest

from cms_ftpput import (
    _cms_fileid,
    _remote_name,
    get_files_on_session,
    put_files_on_session,
)


class FtpNameTests(unittest.TestCase):
    def test_cms_fileid_uses_ftp_dotted_syntax(self):
        self.assertEqual(_cms_fileid("GITPMK EXEC"), "GITPMK.EXEC.A")
        self.assertEqual(_cms_fileid("M173NEW DIRECT C"), "M173NEW.DIRECT.C")
        self.assertEqual(_cms_fileid("M50BAK DIRECT C0"), "M50BAK.DIRECT.C0")

    def test_remote_names_accept_cms_ids_and_private_relative_paths(self):
        self.assertEqual(_remote_name("GITPMK EXEC"), "GITPMK.EXEC")
        self.assertEqual(
            _remote_name(".mdisk-stage/M50NEW.DIRECT"),
            ".mdisk-stage/M50NEW.DIRECT",
        )

    def test_fileids_and_remote_paths_reject_injection_shapes(self):
        for invalid in ("NAME", "A B C D", "A.B.C.D", "A;QUIT B"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    _cms_fileid(invalid)
        for invalid in ("", "../outside", "/absolute", "a/../../b"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    _remote_name(invalid)


class FakeFtpSession:
    verbose = False

    def __init__(self):
        self.commands = []
        self.responses = []

    def _send(self, command):
        self.commands.append(command)

    def _read_until(self, pattern, timeout=30, stream=False):
        if not self.responses:
            raise AssertionError("unexpected FTP read")
        return self.responses.pop(0)


class FtpSessionTests(unittest.TestCase):
    def session(self, transfer_response="226 Transfer complete\nCommand:\n"):
        session = FakeFtpSession()
        session.responses = [
            "Command:\n",  # FTP login
            "200 Type set to ASCII\nCommand:\n",
            "250 staging directory selected\nCommand:\n",
            transfer_response,
            "Ready;\n.\n",  # CMS prompt after QUIT
        ]
        return session

    def test_put_uses_dotted_cms_fileid_and_relative_ftp_path(self):
        session = self.session()
        put_files_on_session(
            session,
            [("M50NEW DIRECT C1", "M50NEW.DIRECT")],
            remote_directory=".mdisk-stage",
        )
        self.assertIn("PUT M50NEW.DIRECT.C1 M50NEW.DIRECT", session.commands)
        self.assertIn("CWD .mdisk-stage", session.commands)
        self.assertEqual(session.commands[-1], "QUIT")

    def test_get_sets_fixed_80_and_uses_dotted_local_fileid(self):
        session = self.session()
        # GET includes LOCSITE between CWD and transfer.
        session.responses.insert(3, "200 Fixed record format set\nCommand:\n")
        get_files_on_session(
            session,
            [("M50NEW.DIRECT", "M50NEW DIRECT C1")],
            remote_directory=".mdisk-stage",
        )
        self.assertIn("LOCSITE FIXRECFM 80", session.commands)
        self.assertIn("GET M50NEW.DIRECT M50NEW.DIRECT.C1", session.commands)

    def test_failed_transfer_raises_and_closes_ftp_session(self):
        session = self.session("550 transfer refused\nCommand:\n")
        with self.assertRaisesRegex(RuntimeError, "FTP transfer failed"):
            put_files_on_session(
                session, [("M50NEW DIRECT C1", "M50NEW.DIRECT")])
        self.assertEqual(session.commands[-1], "QUIT")


if __name__ == "__main__":
    unittest.main()

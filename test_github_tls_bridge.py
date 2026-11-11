"""Offline tests for the host-side plain-HTTP to HTTPS bridge.

The bridge is deployed on the workstation, not shipped inside the guest
bundle, so these tests are run by CI directly rather than by the packaged
build.  They exercise parsing, policy, header rewriting, credential loading
and the request-forwarding order without opening a socket to GitHub.
"""
import os
import socket
import stat
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import github_tls_bridge as bridge


class QuietLog:
    def setUp(self):
        super().setUp()
        self._saved_log = bridge.log
        bridge.log = lambda msg: None

    def tearDown(self):
        bridge.log = self._saved_log
        super().tearDown()


def head(text):
    return text.replace("\n", "\r\n").encode("iso-8859-1")


class RequestHeadTests(QuietLog, unittest.TestCase):
    def test_accepts_a_normal_git_request(self):
        method, target, version, headers = bridge.parse_request_head(head(
            "GET /owner/repo.git/info/refs?service=git-upload-pack HTTP/1.1\n"
            "Host: github.com\n"
            "User-Agent: git/2.45\n"
            "Content-Length: 0\n"
        ))
        self.assertEqual((method, version), ("GET", "HTTP/1.1"))
        self.assertEqual(target,
                         "/owner/repo.git/info/refs?service=git-upload-pack")
        self.assertEqual(bridge.header_get(headers, "host"), "github.com")

    def test_rejects_malformed_request_lines(self):
        for raw in (b"", b"GET\r\n", b"GET /path\r\n", b"get /p HTTP/1.1\r\n",
                    b"GET /p HTTP/2\r\n", b"GET  /p HTTP/1.1\r\n",
                    b"GET /p HTTP/1.1\r\nBroken\r\n",
                    b"GET /p HTTP/1.1\r\nHost : github.com\r\n",
                    b"GET /p HTTP/1.1\r\nHost: git\nhub.com\r\n"):
            with self.subTest(raw=raw):
                with self.assertRaises(bridge.BridgeError) as caught:
                    bridge.parse_request_head(raw)
                self.assertEqual(caught.exception.status, 400)

    def test_rejects_folded_headers(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.parse_request_head(head(
                "GET /p HTTP/1.1\nHost: github.com\n more\n"))

    def test_rejects_control_characters_in_values(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.parse_request_head(b"GET /p HTTP/1.1\r\nHost: git\x00hub\r\n")

    def test_rejects_too_many_headers(self):
        raw = "GET /p HTTP/1.1\nHost: github.com\n"
        raw += "".join(f"X-Pad-{i}: 1\n" for i in range(250))
        with self.assertRaises(bridge.BridgeError) as caught:
            bridge.parse_request_head(head(raw))
        self.assertEqual(caught.exception.status, 431)

    def test_rejects_an_overlong_target(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.parse_request_head(head(
                f"GET /{'a' * bridge.MAX_TARGET} HTTP/1.1\nHost: github.com\n"))


class RepositoryTargetTests(unittest.TestCase):
    def test_discovery_targets(self):
        fetch = bridge.parse_repo_request(
            "GET", "/Owner/Repo.git/info/refs?service=git-upload-pack")
        self.assertEqual(fetch, bridge.RepoRequest("Owner/Repo", "upload-pack",
                                                   False, True))
        push = bridge.parse_repo_request(
            "GET", "/o/r/info/refs?foo=1&service=git-receive-pack")
        self.assertEqual(push, bridge.RepoRequest("o/r", "receive-pack", True, True))

    def test_post_targets(self):
        self.assertEqual(
            bridge.parse_repo_request("POST", "/o/r.git/git-upload-pack"),
            bridge.RepoRequest("o/r", "upload-pack", False, False))
        self.assertEqual(
            bridge.parse_repo_request("POST", "/o/r/git-receive-pack"),
            bridge.RepoRequest("o/r", "receive-pack", True, False))

    def test_rejects_everything_else(self):
        for method, target in (
            ("GET", "/o/r.git/git-upload-pack"),
            ("POST", "/o/r/info/refs?service=git-upload-pack"),
            ("GET", "/o/r/info/refs?service=git-archive"),
            ("GET", "/o/r/info/refs"),
            ("GET", "/o/r.git/objects/aa/bb"),
            ("GET", "/o/r.git"),
            ("GET", "/o/r.git/extra/info/refs?service=git-upload-pack"),
            ("GET", "http://github.com/o/r/info/refs?service=git-upload-pack"),
            ("GET", "/../r/info/refs?service=git-upload-pack"),
            ("GET", "/o/r%2e%2e/info/refs?service=git-upload-pack"),
        ):
            with self.subTest(target=target):
                with self.assertRaises(bridge.BridgeError):
                    bridge.parse_repo_request(method, target)


class PolicyTests(unittest.TestCase):
    def request(self, repo="owner/repo", push=False):
        return bridge.RepoRequest(repo, "receive-pack" if push else "upload-pack",
                                  push, False)

    def test_open_policy_allows_any_repository(self):
        bridge.Policy(False, set(), set()).check(self.request("any/thing", True))

    def test_closed_policy_requires_an_exact_repository(self):
        policy = bridge.Policy(True, {"owner/repo"}, set())
        policy.check(self.request())
        for repo in ("owner/other", "owner/repo2", "someone/owner/repo"):
            with self.subTest(repo=repo):
                with self.assertRaises(bridge.BridgeError) as caught:
                    policy.check(self.request(repo))
                self.assertEqual(caught.exception.status, 403)

    def test_push_needs_its_own_allowlist(self):
        policy = bridge.Policy(True, {"owner/repo"}, set())
        with self.assertRaises(bridge.BridgeError):
            policy.check(self.request(push=True))

    def test_allowlists_are_case_and_suffix_insensitive(self):
        self.assertEqual(bridge.normalize_repo(" /Owner/Repo.git/ "), "owner/repo")
        policy = bridge.Policy(True, {bridge.normalize_repo("Owner/Repo.git")},
                               {bridge.normalize_repo("Owner/Repo.git")})
        policy.check(self.request("owner/repo", True))


class HeaderRewriteTests(unittest.TestCase):
    def test_pass_mode_keeps_the_client_credential(self):
        out = bridge.rewrite_headers(
            [("Host", "github.com"), ("Authorization", "Basic abc"),
             ("Connection", "keep-alive")],
            auth_mode="pass", auth_header=None, request_id="rid1")
        self.assertIn(("Authorization", "Basic abc"), out)
        self.assertIn(("Connection", "close"), out)
        self.assertNotIn(("Connection", "keep-alive"), out)
        self.assertIn(("X-CMS-Git-Id", "rid1"), out)

    def test_host_mode_replaces_the_client_credential(self):
        out = bridge.rewrite_headers(
            [("Authorization", "Basic client"), ("X-CMS-Git-Id", "spoof")],
            auth_mode="host", auth_header="Basic host", request_id="rid2")
        self.assertNotIn(("Authorization", "Basic client"), out)
        self.assertIn(("Authorization", "Basic host"), out)
        values = [v for k, v in out if k.lower() == "x-cms-git-id"]
        self.assertEqual(values, ["rid2"])

    def test_head_ends_with_a_blank_line(self):
        wire = bridge.build_request_head(
            "POST", "/o/r/git-upload-pack", "HTTP/1.1", [("Host", "github.com")])
        self.assertTrue(wire.endswith(b"\r\n\r\n"))
        self.assertTrue(wire.startswith(b"POST /o/r/git-upload-pack HTTP/1.1\r\n"))


class HeaderValidationTests(unittest.TestCase):
    def test_accepts_one_host_and_a_length(self):
        headers = [("Host", "github.com"), ("Content-Length", "12")]
        self.assertEqual(bridge.validate_headers(headers, "github.com", 1024), 12)

    def test_accepts_a_host_with_a_port(self):
        self.assertIsNone(bridge.validate_headers(
            [("Host", "github.com:443")], "github.com", 1024))

    def test_chunked_has_no_declared_length(self):
        self.assertIsNone(bridge.validate_headers(
            [("Host", "github.com"), ("Transfer-Encoding", "chunked")],
            "github.com", 1024))

    def test_rejects_ambiguous_framing(self):
        for headers in (
            [("Host", "github.com"), ("Host", "evil.example")],
            [],
            [("Host", "evil.example")],
            [("Host", "github.com"), ("Content-Length", "1"),
             ("Transfer-Encoding", "chunked")],
            [("Host", "github.com"), ("Transfer-Encoding", "gzip")],
            [("Host", "github.com"), ("Transfer-Encoding", "chunked"),
             ("Transfer-Encoding", "chunked")],
            [("Host", "github.com"), ("Content-Length", "1"),
             ("Content-Length", "2")],
            [("Host", "github.com"), ("Content-Length", "-1")],
            [("Host", "github.com"), ("Content-Length", "1x")],
        ):
            with self.subTest(headers=headers):
                with self.assertRaises(bridge.BridgeError):
                    bridge.validate_headers(headers, "github.com", 1024)

    def test_rejects_an_oversized_body(self):
        with self.assertRaises(bridge.BridgeError) as caught:
            bridge.validate_headers(
                [("Host", "github.com"), ("Content-Length", "2048")],
                "github.com", 1024)
        self.assertEqual(caught.exception.status, 413)


class CredentialTests(unittest.TestCase):
    def write(self, text, mode=0o600):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "token"
        path.write_text(text, encoding="utf-8")
        os.chmod(path, mode)
        return path

    def test_reads_a_bare_token(self):
        token = bridge.load_token(str(self.write("ghp_example\n")))
        self.assertEqual((token.user, token.secret), ("git", "ghp_example"))
        self.assertEqual(token.header(),
                         "Basic " + bridge.base64.b64encode(
                             b"git:ghp_example").decode("ascii"))

    def test_reads_a_user_and_token(self):
        token = bridge.load_token(str(self.write("bot:ghp_example")))
        self.assertEqual((token.user, token.secret), ("bot", "ghp_example"))

    def test_rejects_unsafe_files(self):
        cases = {
            "group readable": self.write("ghp_x", 0o640),
            "world readable": self.write("ghp_x", 0o604),
            "empty": self.write("  \n"),
            "two lines": self.write("one\ntwo\n"),
            "empty user": self.write(":ghp_x"),
        }
        for label, path in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    bridge.load_token(str(path))

    def test_rejects_a_directory(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with self.assertRaises((ValueError, OSError)):
            bridge.load_token(directory.name)

    def test_rejects_a_symlink(self):
        target = self.write("ghp_x")
        link = Path(target).parent / "link"
        os.symlink(target, link)
        with self.assertRaises(ValueError):
            bridge.load_token(str(link))

    def test_mode_check_uses_real_permissions(self):
        path = self.write("ghp_x", 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(bridge.load_token(str(path)).secret, "ghp_x")


class FakeUpstream:
    def __init__(self, response=b""):
        self.sent = bytearray()
        self.response = response
        self.timeout = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, data):
        self.sent += data

    def recv(self, count):
        if not self.response:
            return b""
        out, self.response = self.response[:count], self.response[count:]
        return out

    def shutdown(self, how):
        pass

    def close(self):
        self.closed = True


class ForwardingTests(QuietLog, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._saved_connect = bridge.connect_upstream
        self.upstream = FakeUpstream()
        bridge.connect_upstream = lambda *a, **k: self.upstream

    def tearDown(self):
        bridge.connect_upstream = self._saved_connect
        super().tearDown()

    def serve(self, request, response=b"", **overrides):
        client, proxy = socket.socketpair()
        self.addCleanup(client.close)
        self.upstream.response = response
        args = SimpleNamespace(
            upstream_host="github.com", upstream_port=443, auth_mode="pass",
            max_header=bridge.MAX_HEADER_DEFAULT, max_body=1024,
            connect_timeout=5.0, idle_timeout=5.0, total_timeout=30.0,
            mode="http")
        for key, value in overrides.items():
            setattr(args, key, value)
        client.sendall(request)
        client.shutdown(socket.SHUT_WR)
        try:
            bridge.serve_http(proxy, ("127.0.0.1", 1), args, None,
                              bridge.Policy(False, set(), set()), None)
        finally:
            proxy.close()
        return client.recv(65536)

    def test_request_head_precedes_the_body(self):
        self.serve(head(
            "POST /o/r.git/git-upload-pack HTTP/1.1\n"
            "Host: github.com\nContent-Length: 5\n\nHELLO"))
        sent = bytes(self.upstream.sent)
        marker = sent.find(b"\r\n\r\n")
        self.assertGreater(marker, 0)
        self.assertEqual(sent[marker + 4:], b"HELLO")
        self.assertTrue(sent.startswith(b"POST /o/r.git/git-upload-pack HTTP/1.1\r\n"))
        self.assertIn(b"Connection: close", sent)

    def test_chunked_body_is_relayed_unchanged(self):
        body = b"5\r\nHELLO\r\n0\r\n\r\n"
        self.serve(head(
            "POST /o/r/git-receive-pack HTTP/1.1\n"
            "Host: github.com\nTransfer-Encoding: chunked\n\n") + body)
        sent = bytes(self.upstream.sent)
        marker = sent.find(b"\r\n\r\n")
        self.assertEqual(sent[marker + 4:], body)

    def test_multi_chunk_body_with_trailers_is_relayed(self):
        body = b"3\r\none\r\n3;ext=1\r\ntwo\r\n0\r\nX-Trailer: 1\r\n\r\n"
        self.serve(head(
            "POST /o/r/git-receive-pack HTTP/1.1\n"
            "Host: github.com\nTransfer-Encoding: chunked\n\n") + body)
        sent = bytes(self.upstream.sent)
        self.assertTrue(sent.endswith(body))

    def test_an_oversized_chunk_is_refused(self):
        body = b"1000\r\n" + b"A" * 0x1000 + b"\r\n0\r\n\r\n"
        with self.assertRaises(bridge.BridgeError) as caught:
            self.serve(head(
                "POST /o/r/git-receive-pack HTTP/1.1\n"
                "Host: github.com\nTransfer-Encoding: chunked\n\n") + body)
        self.assertEqual(caught.exception.status, 413)

    def test_an_invalid_chunk_size_is_refused(self):
        body = b"1g\r\nA\r\n0\r\n\r\n"
        with self.assertRaises(bridge.BridgeError) as caught:
            self.serve(head(
                "POST /o/r/git-receive-pack HTTP/1.1\n"
                "Host: github.com\nTransfer-Encoding: chunked\n\n") + body)
        self.assertEqual(caught.exception.status, 400)

    def test_a_truncated_body_is_an_error(self):
        with self.assertRaises(bridge.BridgeError) as caught:
            self.serve(head(
                "POST /o/r/git-upload-pack HTTP/1.1\n"
                "Host: github.com\nContent-Length: 10\n\nSHORT"))
        self.assertEqual(caught.exception.status, 400)

    def test_extra_bytes_after_the_declared_length_are_not_forwarded(self):
        self.serve(head(
            "POST /o/r/git-upload-pack HTTP/1.1\n"
            "Host: github.com\nContent-Length: 3\n\nABCDEF"))
        sent = bytes(self.upstream.sent)
        self.assertTrue(sent.endswith(b"\r\n\r\nABC"))

    def test_the_response_is_returned_to_the_client(self):
        reply = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"
        out = self.serve(head(
            "GET /o/r/info/refs?service=git-upload-pack HTTP/1.1\n"
            "Host: github.com\n\n"), response=reply)
        self.assertEqual(out, reply)

    def test_discovery_with_a_body_is_refused(self):
        with self.assertRaises(bridge.BridgeError):
            self.serve(head(
                "GET /o/r/info/refs?service=git-upload-pack HTTP/1.1\n"
                "Host: github.com\nContent-Length: 4\n\nBODY"))
        self.assertEqual(bytes(self.upstream.sent), b"")

    def test_a_disallowed_repository_never_reaches_the_upstream(self):
        client, proxy = socket.socketpair()
        self.addCleanup(client.close)
        args = SimpleNamespace(
            upstream_host="github.com", upstream_port=443, auth_mode="pass",
            max_header=bridge.MAX_HEADER_DEFAULT, max_body=1024,
            connect_timeout=5.0, idle_timeout=5.0, total_timeout=30.0,
            mode="http")
        client.sendall(head(
            "GET /evil/repo/info/refs?service=git-upload-pack HTTP/1.1\n"
            "Host: github.com\n\n"))
        with self.assertRaises(bridge.BridgeError) as caught:
            bridge.serve_http(proxy, ("127.0.0.1", 1), args, None,
                              bridge.Policy(True, {"owner/repo"}, set()), None)
        proxy.close()
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(bytes(self.upstream.sent), b"")

    def test_host_auth_replaces_the_guest_credential(self):
        token = bridge.Token("git", "host-secret")
        client, proxy = socket.socketpair()
        self.addCleanup(client.close)
        args = SimpleNamespace(
            upstream_host="github.com", upstream_port=443, auth_mode="host",
            max_header=bridge.MAX_HEADER_DEFAULT, max_body=1024,
            connect_timeout=5.0, idle_timeout=5.0, total_timeout=30.0,
            mode="http")
        client.sendall(head(
            "GET /o/r/info/refs?service=git-upload-pack HTTP/1.1\n"
            "Host: github.com\nAuthorization: Basic guest\n\n"))
        bridge.serve_http(proxy, ("127.0.0.1", 1), args, None,
                          bridge.Policy(False, set(), set()), token)
        proxy.close()
        sent = bytes(self.upstream.sent)
        self.assertNotIn(b"Basic guest", sent)
        self.assertIn(b"Authorization: " + token.header().encode("ascii"), sent)


class ArgumentTests(QuietLog, unittest.TestCase):
    def test_defaults_keep_relay_compatibility(self):
        args = bridge.parse_args([])
        self.assertEqual((args.mode, args.policy, args.auth_mode),
                         ("relay", "open", "pass"))
        bridge.validate_args(args)

    def test_closed_policy_needs_a_read_allowlist(self):
        with self.assertRaises(SystemExit):
            bridge.build_policy(bridge.parse_args(["--policy", "closed"]))

    def test_push_allowlist_must_be_readable(self):
        with self.assertRaises(SystemExit):
            bridge.build_policy(bridge.parse_args([
                "--policy", "closed", "--allow-repo", "owner/repo",
                "--allow-push-repo", "owner/other"]))
        policy = bridge.build_policy(bridge.parse_args([
            "--policy", "closed", "--allow-repo", "owner/repo",
            "--allow-push-repo", "owner/repo"]))
        self.assertEqual(policy.allow_push, {"owner/repo"})

    def test_invalid_allowlist_entries_are_refused(self):
        for value in ("repo", "owner/", "/repo", "own er/repo", "../repo"):
            with self.subTest(value=value):
                with self.assertRaises(SystemExit):
                    bridge.build_policy(bridge.parse_args([
                        "--policy", "closed", "--allow-repo", value]))

    def test_rejects_impossible_limits(self):
        bad = (
            ["--max-header", "10"],
            ["--max-body", "10"],
            ["--max-connections", "0"],
            ["--max-connections", "5000"],
            ["--connect-timeout", "0"],
            ["--idle-timeout", "-1"],
            ["--total-timeout", "-1"],
            ["--connect-timeout", "60", "--idle-timeout", "30"],
        )
        for extra in bad:
            with self.subTest(extra=extra):
                args = bridge.parse_args(extra)
                with self.assertRaises(SystemExit):
                    bridge.validate_args(args)

    def test_zero_timeouts_disable_the_limit(self):
        args = bridge.parse_args(["--idle-timeout", "0", "--total-timeout", "0"])
        bridge.validate_args(args)
        self.assertIsNone(bridge.next_timeout(0, None))
        self.assertEqual(bridge.next_timeout(0, time.monotonic() + 60) > 0, True)


if __name__ == "__main__":
    unittest.main()

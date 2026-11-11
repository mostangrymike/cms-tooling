# Host TLS bridge for CMS GitHub access

`github_tls_bridge.py` is a small, dependency-free process on the workstation
that lets the CMS Git client reach GitHub. It is a host-side component: it is
not shipped in the guest tooling bundle, and it must not be uploaded to CMS.

z/VM 6.3 CMS cannot originate the TLS session GitHub requires, so the bridge is
a fixed part of this design. The question is how much of the network policy it
should own. In `http` mode it owns HTTP framing, the repository allowlist, the
GitHub credential and request correlation, so the guest sends plain HTTP and
never holds a token.

```
CMS client  -- plain HTTP over VMnet -->  bridge  -- verified HTTPS -->  github.com
            (no TLS, no token)            (policy, auth, limits)
```

## Modes

| Mode | Behaviour | Use |
| --- | --- | --- |
| `relay` (default) | Forwards bytes both ways to one fixed upstream. No parsing, no policy, no auth injection. | Compatibility and rollback. |
| `http` | Parses the request line and headers, enforces the allowlist, optionally injects a host credential, adds a request ID, then forwards the body and relays the response unchanged. | Normal operation. |

`relay` is the default so an existing command line keeps working after an
upgrade. Run `http` deliberately.

```sh
python3 github_tls_bridge.py \
  --mode http \
  --bind 192.168.200.1 --port 8444 \
  --upstream-host github.com --upstream-port 443 \
  --policy closed \
  --allow-repo mostangrymike/cms-git \
  --allow-repo mostangrymike/cms-git-push-test \
  --allow-push-repo mostangrymike/cms-git-push-test \
  --auth-mode host \
  --token-file "$HOME/.config/ibm-zvm-cms/github-token"
```

## What `http` mode accepts

Only the four smart-HTTP endpoints a clone, fetch, pull or push needs:

| Request | Service | Effect |
| --- | --- | --- |
| `GET /owner/repo(.git)/info/refs?service=git-upload-pack` | upload-pack | read discovery |
| `GET /owner/repo(.git)/info/refs?service=git-receive-pack` | receive-pack | write discovery |
| `POST /owner/repo(.git)/git-upload-pack` | upload-pack | read |
| `POST /owner/repo(.git)/git-receive-pack` | receive-pack | write |

Anything else, including `dumb` HTTP object paths, archives and the GitHub web
API, is refused with `404`. A repository path must be exactly `owner/repo`;
extra path segments, `..`, encoded separators and non-ASCII names are refused.

The request must carry exactly one `Host` header naming the configured upstream.
Duplicate `Host`, `Transfer-Encoding` together with `Content-Length`, an
unsupported transfer coding, or a malformed `Content-Length` is refused with
`400` before any upstream connection is opened. This pins the bridge to one
upstream instead of turning it into a general proxy.

`GET /healthz` returns `200 ok` and is logged, so a supervisor or a manual check
can prove the listener is alive without involving GitHub.

## Response handling

The response is passed through byte for byte. That matters: the CMS client
requires the exact Git content types and `Transfer-Encoding: chunked`, so the
bridge must not decompress, re-chunk or rewrite bodies. The bridge removes the
client `Connection` header and sends `Connection: close`, so one request maps to
one upstream connection.

## Policy

`--policy open` (default) forwards any `owner/repo` to the upstream. It is
appropriate only on a trusted host network while migrating.

`--policy closed` refuses anything not named by a repeatable `--allow-repo`.
Push additionally requires `--allow-push-repo`. A push repository must also
appear in `--allow-repo`, and the bridge refuses to start otherwise. Entries are
compared case-insensitively after stripping a trailing `.git`.

The allowlist is the only thing preventing a compromised guest from reading
private repositories the host token can see. Keep it explicit and small.

## Credentials

| `--auth-mode` | Behaviour |
| --- | --- |
| `pass` (default) | The guest's `Authorization` header is forwarded. This is the current `GHCRED REPO A` behaviour. |
| `host` | The guest's `Authorization` header is removed and replaced with the host-held token. Requires `--token-file` or `BRIDGE_GITHUB_TOKEN_FILE`. |

The token file is one line, either `TOKEN` or `USER:TOKEN`. With no colon the
user defaults to `git`, which is what GitHub expects for a PAT over Basic auth.
The file must be a regular file (not a symlink), owned by the bridge user, with
no group or other permission bits, at most 4096 bytes:

```sh
install -m 600 /dev/null "$HOME/.config/ibm-zvm-cms/github-token"
# write one line into the file without echoing it into shell history
```

The bridge never logs the token, the header value or a URL query string. A
startup line records only the token's user name:

```
[...] host credential loaded user=git (value not logged)
```

When `host` mode is in use, remove the guest copy so the secret exists in one
place:

```
GIT CREDENTIAL STATUS
GIT CREDENTIAL REMOVE
```

`GIT CREDENTIAL STATUS` should then report `No GitHub credential stored`.

## Limits and timeouts

| Flag | Default | Meaning |
| --- | --- | --- |
| `--max-header` | 65536 | Request head bytes; at least 1024. |
| `--max-body` | 268435456 | Declared or decoded request body bytes; at least 1024. |
| `--max-connections` | 8 | Concurrent connections; 1 to 1024. |
| `--connect-timeout` | 20 | Header read and upstream connect; must not exceed the idle timeout. |
| `--idle-timeout` | 900 | Longest silence during a transfer; `0` disables. |
| `--total-timeout` | 3600 | Whole connection, measured from after the upstream connects; `0` disables. |

All values are validated at startup; a negative timeout is a startup error,
not an infinite wait. `--idle-timeout 0 --total-timeout 0` reproduces the
original relay's unlimited transfers, which is the exact rollback setting for
a push that legitimately runs longer than an hour. Connections beyond
`--max-connections` are closed immediately and logged.

## Request bodies

A `POST` body is framed by `Content-Length` or by `Transfer-Encoding: chunked`.
Both are relayed unchanged. The bridge sends the rewritten head first, then the
body, and it stops reading the client at the declared length or at the final
chunk and trailer. It never forwards a request body for discovery, and it never
buffers a body in memory.

The current CMS client sends `Content-Length`, so it uses the simpler path.
Chunked request bodies are supported for a stock host-side `git` client.

## Logging

Each line is timestamped on stderr and contains only the request ID, the peer
address, the method, the normalized `owner/repo`, the service, the push flag,
and byte counts. Rejections log the status and a fixed reason string. There is
no header dump, no body capture and no query string.

```
[...] request id=9f3c1a04e7b2 peer=192.168.200.2:41234 GET mostangrymike/cms-git upload-pack push=0
[...] complete id=9f3c1a04e7b2 peer=192.168.200.2:41234 sent=842 received=192044
[...] reject peer=192.168.200.2:41235 status=403 reason=repository is not allowed
```

A client may supply `X-CMS-Git-Id` to correlate a CMS-side log line with a
bridge line. It is accepted only if it matches `[A-Za-z0-9._-]{1,64}`;
otherwise the bridge generates one. A supplied value is replaced, never
duplicated.

## Deployment and rollback

Bind the VMnet interface only (`--bind 192.168.200.1`); the guest reaches the
bridge at the port it is configured with. Do not bind `0.0.0.0`.

Rollback is `--mode relay --idle-timeout 0 --total-timeout 0` with no policy or
auth flags; that reproduces the previous behaviour exactly. Keep the old
command line in the launcher until `http` mode has been used for a clone, a
pull and a push.

If the bridge is upgraded while a transfer is running, the in-flight connection
fails; the CMS side is fail-closed, so re-run the command.

## Tests

```sh
python3 -B -m unittest -v test_github_tls_bridge
```

These tests are offline: parsing, policy, allowlist construction, header
rewriting and framing validation, token-file permissions, and request/response
forwarding over a socket pair. CI runs them directly; the packaged build does
not include either file.

# TLS capability of the z/VM 6.3 guest

Assessed 2026-11-19 on `MAINT AT TACOTICO` (z/VM 6.3.0, CMS 27 SL 1302).

## Verdict

**Not modern enough for outbound HTTPS, and there is no outbound path anyway.**

The client stack cannot complete a handshake with GitHub, Cloudflare,
CloudFront, or any endpoint that requires SNI or ECDHE. Separately, the guest
has no route to the internet today.

Inbound TLS is fine. Five SSL server user IDs are active and serve host tools.

## Client stack

| Item | Value |
|---|---|
| Modules | `GSKCMS31 MODULE T2`, `GSKSSL MODULE T2` |
| Build date | 6/27/13 08:29 (z/VM 6.3 GA) |
| Platform | `CMS Level 27, Service Level 1302` |
| CA store | none; `GSK*` on A and F both `File not found` |

## Captured ClientHello

Taken from the CMS FTP client itself. After login, `CProtect` (no operands) is
the TLS trigger; it issues `AUTH TLS`, then starts the handshake. Against a host
listener that answers `234` and reads raw bytes:

```
RECORD_VERSION            0303
HANDSHAKE_LEGACY_VERSION  0303
EXTENSIONS                signature_algorithms only
CIPHERS (32)              00ff 003c 003d 003e 003f 0040 0067 0068 0069 006a
                          006b 0005 0004 0035 0036 0037 0038 0039 002f 0030
                          0031 0032 0033 000a 0016 0013 0010 000d 003b 0002
                          0001 0000
SIGALGS                   0601 0603 0501 0503 0401 0403 0301 0303 0201 0203
                          0202 0101
```

What that means:

| Feature | Present | Consequence |
|---|---|---|
| TLS 1.3 (`supported_versions`) | **no** | TLS-1.3-only endpoints refuse |
| SNI (`0x0000`) | **no** | CDNs and vhosts return the default cert |
| ECDHE (`0x000a`) | **no** | ECDHE-only endpoints refuse; ECDSA unusable |
| AES-GCM, ChaCha20 | **no** | only RSA/DHE with AES-CBC |
| ALPN | **no** | no HTTP/2 |
| RC4, 3DES, export suites | yes | legacy ciphers still offered |

Maximum version is TLS 1.2. Key exchange is RSA transport or finite-field DHE
only. Cipher families present are AES-128/256-CBC with SHA or SHA-256, RC4-128,
3DES, and export-grade suites.

## Version pinning

Four single-version host listeners, one `CProtect` each:

| Listener pinned to | Result |
|---|---|
| TLS 1.0 | handshake reached cert validation |
| TLS 1.1 | client `(412) Internal SSL error` |
| TLS 1.2 | handshake reached cert validation |
| TLS 1.3 | `unsupported protocol` |

Certificate validation works: the client aborted with
`(417) Self-signed certificate cannot be validated` and sent
`alert unknown_ca`. There is no key database on any accessed disk, so no CA
roots exist until someone builds one with `gskkyman`.

## Network

| Probe | Result |
|---|---|
| `PING 8.8.8.8 (COUNT 2` | `Ping #1 timed out`, `Ping #2 timed out` |
| `PING github.com` | `DTCPIN0014E Unknown host GITHUB.COM` |
| `TELNET 1.1.1.1 443` | `Foreign host did not respond within OPEN timeout` |
| `NETSTAT HOME` | `192.168.200.2/24` on `CTC1LINK` |
| `NETSTAT GATE` | default `192.168.200.1` |
| `NSINTERADDR` in `TCPIP DATA T1` | `8.8.8.8` (unreachable from the guest) |

The default gateway is the workstation (`192.168.200.1`), which does have
internet access. Nothing NATs `192.168.200.0/24`, so the guest cannot reach it.

## Consequences by site class

| Site class | Result |
|---|---|
| GitHub, Google, most CDNs | fail (SNI and ECDHE both absent) |
| TLS-1.3-only endpoints | fail |
| Legacy RSA-kex AES-CBC, single cert, no SNI | could work |
| Host to guest (inbound) | works |

## Recommendation

Do not port a TLS stack to the guest. Keep the terminating gateway pattern that
`github_tls_bridge.py` already proves: the guest speaks plain TCP, a gateway
(Linux guest under the same z/VM, or the host relay) speaks modern TLS.

Native outbound TLS with SNI, ECDHE, and TLS 1.3 is a z/VM 7.x GSKit feature.
z/VM 6.3 went out of service in 2017.

## Reproducing

The probe needs no CMS-side code; it uses the FTP client as a TLS initiator.

1. On the host, listen on a spare port, answer `220`, and on `AUTH` reply `234`
   and then read the next bytes without wrapping the socket.
2. From CMS, `FTP <host> <port>`, log in, then send `CProtect`.
3. Parse the ClientHello: record version at byte 1, then the cipher list and
   the extension block. Absence of `0x0000`, `0x000a`, and `0x002b` is the
   whole answer.

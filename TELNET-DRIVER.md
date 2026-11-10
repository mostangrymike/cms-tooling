# CMS line-mode Telnet driver

`cms_telnet_driver.py` is the supported command path for z/VM CMS work from
macOS. It speaks the line-mode Telnet service on `192.168.200.2:23` (the z/VM
TCPIP stack) instead of the 3270 screen protocol, so it works when s3270/x3270
is stuck in CP READ, VM READ, or a blank buffer.

It is deliberately small and dependency-free (Python 3.9+, standard library
only), which makes it usable from scripts, CI, and the MCP server.

## Why line mode

* One command in flight, one prompt. Completion is a line containing only `.`.
* Output streams line by line, so long imports show progress instead of
  looking hung.
* No screen geometry, field layout, MORE paging, or AID-key state to track.
* `IPL CMS` always recovers a clean CMS environment when a program is stuck.

## Usage

```bash
# Probe: log on, IPL CMS, report level/disk/terminal
.venv/bin/python cms_telnet_driver.py -v --log /tmp/cms_driver.log probe

# One command (output streams to the terminal)
.venv/bin/python cms_telnet_driver.py run --timeout 600 "EXEC GIT FETCH-IMPORT M273P021 G"

# Batch, stopping on the first non-zero RC
.venv/bin/python cms_telnet_driver.py batch commands.txt --timeout 120

# Interactive
.venv/bin/python cms_telnet_driver.py shell
```

Credentials are read from `~/.config/ibm-zvm-cms/credentials.json`
(`{"userid": "...", "password": "..."}`) unless `--credentials` is given.
Passwords are never logged; `--log` records sanitized sends and received text.

## Python API

```python
from cms_telnet_driver import CmsSession, CmsTimeout

with CmsSession(on_line=print) as session:   # streams every output line
    session.connect()                         # LOGON + IPL CMS + QUERY CMSLEVEL
    result = session.command("EXEC GIT VERSION", timeout=60)
    print(result.rc, result.duration)
    try:
        session.command("EXEC GIT FETCH-IMPORT M273P021 G", timeout=1800)
    except CmsTimeout:
        session.interrupt()                   # attention -> HX -> IPL CMS
```

`connect(fresh=False)` reconnects to the existing MAINT session
(`LOGON MAINT HERE`) instead of IPLing CMS from scratch.

## Behaviour notes

* The banner appears only after the first input; the driver sends a Telnet
  BREAK and then `LOGON MAINT`.
* After the password the guest is at CP READ. The driver issues `IPL CMS` and
  then a sync command (`QUERY CMSLEVEL`) to flush the pending Ready.
* The prompt is a line containing only `.`. `Ready;` alone is not treated as a
  terminator; it is only a fallback after a quiet period.
* `MORE...`/`HOLDING` is advanced automatically with a blank line.
* `interrupt()` sends Telnet IP (attention), then `HX`, then falls back to
  `IPL CMS`. This z/VM level rejects `HX` (`HCPCMD001E Unknown CP command: HX`),
  so `IPL CMS` is the reliable cancellation path.
* CMS folds output at column 80. Concatenate wrapped fragments before parsing
  long OIDs or summaries.

## Tests

```bash
.venv/bin/python -m unittest test_cms_telnet_driver -v
```

The tests use a fake line-mode server and cover login, prompt detection,
streaming, timeout + interrupt, and Telnet option stripping.

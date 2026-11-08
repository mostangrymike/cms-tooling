# Hercules / z/VM on EC2 startup record

Last verified: 2026-10-21 (EC2 `admin@3.17.164.13`). This records the live
startup that restored z/VM and its CMS TCP/IP path. It does not store the PEM
key or CMS password.

## Host and files

- SSH host: `admin@3.17.164.13`; local key: `~/Downloads/ibm.pem`.
- Hercules config and RC: `/home/admin/vm630/hercules.cnf` and
  `/home/admin/vm630/hercules.rc`.
- Executable: `/home/admin/ht/aethra/build/hercules` (libtool wrapper; it starts
  `/home/admin/ht/aethra/build/.libs/hercules`).
- Run directory: `/home/admin/vm630`.
- DASD devices in the config: `0123`–`0128`, files `dasd1`–`dasd6`.
- Host `tap0` must exist for the configured QETH device `0600.3`:
  `192.168.200.1/24`; z/VM uses `192.168.200.2`.
- Hercules accepts 3270 connections on port `3270`. The guest TCP/IP Telnet
  endpoint is `192.168.200.2:23` over `tap0` (not a host-local port-23
  listener).

## Start procedure

SSH to EC2, then check before creating resources or processes:

```sh
ip -brief addr show tap0
pgrep -af '\.libs/hercules.*hercules.cnf'
tmux has-session -t hercules
```

When `tap0` is absent, create and configure it (the `admin` account needs the
existing sudo rights):

```sh
sudo ip tuntap add dev tap0 mode tap user admin
sudo ip addr add 192.168.200.1/24 dev tap0
sudo ip link set tap0 up
```

Start the configured VM in a persistent tmux session only if it is not already
running:

```sh
tmux new-session -d -s hercules \
  'cd /home/admin/vm630 && /home/admin/ht/aethra/build/hercules -f hercules.cnf -r hercules.rc'
```

Inspect the emulator/HMC console with:

```sh
tmux capture-pane -p -t hercules -S -100
```

The saved config IPLs DASD `0123` (`M01RES`); device `0127` is `VMCOM1`.
At the z/VM HMC start prompt, Hercules HMC commands need a leading period.
The validated sequence on this recovery was `.warm`, `.no` at the TOD-change
question (the EC2 clock was correct), then `.force` after the saved warm-start
recovery was rejected. CP reported `HCPWRM904E System recovery failure;
incorrect warm start data` and explicitly offered FORCE or STOP. The FORCE
start reached the z/VM nucleus, autologged its system users, started TCPIP, and
attached QETH to `tap0`. FORCE may discard spool/accounting recovery state.
Only choose FORCE on a matching CP recovery prompt when recovery is intended.

## Persistent startup on EC2 (configured 2026-10-21)

- `/etc/systemd/system/hercules-tap0.service` is enabled. It creates TAP
  `tap0` for user `admin` when absent, assigns `192.168.200.1/24`, and brings
  the link up. It is ordered after `network-online.target`.
- `/etc/systemd/system/hercules.service` is enabled and requires the TAP unit.
  It runs Hercules as `admin` from `/home/admin/vm630`, with output in the
  systemd journal. `systemd-analyze verify` passed for both units.
- The service uses `/home/admin/vm630/hercules-autoboot.rc`. That file runs
  `ipl 0123`, waits for the z/VM start prompt, replies `.warm`, then replies
  `.no` after the warm-start/TOD interval. This brings up the normal warm-start
  path so z/VM can autolog TCPIP and attach QETH. It deliberately does not
  answer a rejected warm start with FORCE; if CP reports incorrect recovery
  data, the guest remains at the FORCE/STOP prompt for an operator to decide.
- These units and the autoboot RC are enabled but were not exercised across a
  reboot. The current Hercules process remains in its original tmux session;
  the systemd emulator service was not started in parallel. The next EC2 reboot
  is the end-to-end persistence check. Do not start `hercules.service` while
  the current Hercules process is still running.
- Inspect after reboot with `systemctl status hercules-tap0 hercules`,
  `journalctl -b -u hercules-tap0 -u hercules`, `ip -brief address show tap0`,
  and a TCP connect to `192.168.200.2:23`. The service is managed with
  `systemctl start|stop|restart hercules`; avoid killing the process directly.

## Evidence and caveats from 2026-10-21

- Hercules PID `19161` remained alive in tmux session `hercules`; port `3270`
  listened on `0.0.0.0:3270`.
- CP loaded the system nucleus from `M01RES`; the guest started `TCPIP` and
  opened QETH on host `tap0`.
- Hercules detected CCKD free-space metadata errors on devices `0123`, `0124`,
  `0125`, and `0127`, then reported `free space rebuilt` for each. This was
  automatic startup repair. Avoid running `dasdls` or other offline DASD tools
  against these images while Hercules has them open.
- A TCP connection to `192.168.200.2:23` succeeded and returned Telnet option
  negotiation. Telnet login for MAINT reached the z/VM 6.3.0 banner and the
  line-mode session displayed `CP`. CMS `Ready;` was not confirmed. A guarded
  `IPL CMS` input was later sent from the observed CP state, but no correlated
  command echo, `VM READ`, or `Ready;` output was captured before the guest
  disconnected the timed-out Telnet session. Treat CMS startup and command
  access as unverified; this is verified z/VM/TCPIP startup only.
- The hostname suffix in the `z/VM ONLINE` Telnet banner (then `TACOTICO`) is
  informational and can change; identify the banner by its z/VM text, not that
  host name.

IBM documents that a line-mode Telnet null entry reports `CP` or `CMS`; after a
fresh logon, `CP` means CP is waiting for a command. The standard CMS startup is
`IPL CMS`, then a null line at `VM READ`, and confirmation of `Ready;`. Use
`BEGIN` only to resume a VM after an interrupt. On the next attempt, capture
the full line-mode response to each step and do not issue CMS commands until a
fresh `Ready;` is visible. CMS action is authorized by the operator's standing
instruction recorded in `AGENTS.md`; log actions and observed results there or
in the validation record.

## IBM references

- [z/VM CMS Primer, “You Have Successfully Entered Your User ID and Password”](https://publibfp.boulder.ibm.com/epubs/pdf/hcsd6c00.pdf): logon, `IPL CMS`, `VM READ`, and `Ready;` sequence.
- [IBM z/VM “Using Commands”](https://www.ibm.com/docs/en/zvm/7.2.0?topic=introduction-using-commands): line-mode `CP`/`CMS` status from a null entry and CP command environment.
- [IBM z/VM “Status Notices”](https://www.ibm.com/docs/en/zvm/7.2.0?topic=started-status-notices): CP READ before `IPL CMS`; `BEGIN` when returning from an interrupt.

## Hercules reference

- [Hercules Version 4: Installation and Operation, `.RC` run commands](https://hercules-390.github.io/html/hercoper.html): the run-command file can execute panel commands at startup and supports timed `pause` commands.

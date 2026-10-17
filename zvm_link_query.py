"""Direct-screen, fixed-command observation of CP minidisk links."""
import re
import time


def link_query_command(vaddr):
    if not isinstance(vaddr, str) or not re.fullmatch(r"[0-9A-Fa-f]{3}", vaddr):
        raise ValueError("Use one three-digit hexadecimal virtual address")
    return "CP QUERY LINKS " + vaddr.upper()


class LinkQuery:
    MAX_PAGES = 64

    def __init__(self, session):
        self.session = session

    def query(self, vaddr, timeout=30):
        s = self.session
        if not s.allow_query_links:
            return {"ok": False, "message": "Link observation requires --allow-query-links",
                    "replacement_safe": False, "link_query_is_lock": False,
                    "host_operations_performed": False}
        try:
            command = link_query_command(vaddr)
            if type(timeout) is not int or not 1 <= timeout <= 60:
                raise ValueError("Link query timeout must be 1..60 seconds")
        except ValueError as exc:
            return {"ok": False, "message": str(exc), "replacement_safe": False,
                    "link_query_is_lock": False, "host_operations_performed": False}

        return self._observe(command, vaddr.upper(), timeout)

    def inspect_g(self, query, timeout=30):
        """Fixed read-only diagnostics for the documented MAINT/0600 G disk.

        Local preflight only; not a new generic-command MCP interface.
        """
        commands = {
            'virtual': 'CP QUERY VIRTUAL DASD',
            'location': 'CP QUERY MDISK 0600 LOCATION',
            'directory': 'CP QUERY MDISK USERID MAINT 0600 LOCATION DIRECTORY',
            'volume': 'CP QUERY SYSTEM 0127',
            'disk': 'QUERY DISK',
        }
        if (not self.session.allow_query_links or not isinstance(query, str) or query not in commands
                or type(timeout) is not int or not 1 <= timeout <= 60):
            return {'ok': False, 'message': 'Enable link observation and choose a fixed G-disk diagnostic',
                    'replacement_safe': False, 'host_operations_performed': False}
        return self._observe(commands[query], '600', timeout)

    def _observe(self, command, vaddr, timeout):
        s = self.session

        def work():
            from zvm_commands import RunnerBridge, ready_rc
            from zvm_mcp import host_display

            if s.em is None:
                raise RuntimeError("Connect and inspect/login before querying links")
            expected_echo = command
            for secret in sorted(s.secrets, key=len, reverse=True):
                if secret:
                    expected_echo = re.sub(re.escape(secret), lambda match: '*' * len(match[0]),
                                           expected_echo, flags=re.I)
            deadline = time.monotonic() + timeout
            before = s.snapshot()
            if before["state"] != "cms_ready" or not RunnerBridge.input_field(before):
                raise RuntimeError("CP QUERY LINKS requires CMS Ready and a verified empty command field")
            s.command("MoveCursor(22,0)")
            check = s.snapshot()
            if (check["state"] != "cms_ready" or not RunnerBridge.input_field(check)
                    or check["cursor"] != {"row": 23, "column": 1, "protected": False}):
                raise RuntimeError("CMS command field changed; link query was not submitted")
            s.command('String("' + command + '")')
            s.command("Ascii")
            s.command("Enter")

            pages = []
            previous = check
            echo_seen = False
            released_hold = False
            segments = {}
            page_number = 0
            while time.monotonic() < deadline:
                s.command("Ascii")
                remaining = max(1, min(3, int(deadline - time.monotonic())))
                s._wait_output(remaining)
                current = s.snapshot()
                # Keyboard/output events alone can repeat the same held page.
                # Never send a second paging key without a changed host display.
                fresh = host_display(current) != host_display(previous)
                if fresh:
                    pages.append(current)
                    if len(pages) > self.MAX_PAGES:
                        raise RuntimeError("CP QUERY LINKS exceeded the 64-page capture limit")
                    matching_echoes = [i for i, row in enumerate(current["rows"])
                                       if row.strip().upper() == expected_echo]
                    if matching_echoes:
                        echo_seen = True
                    start = max(matching_echoes) + 1 if matching_echoes else (0 if released_hold else None)
                    if start is not None:
                        rows = current['rows'][start:22]
                        end = next((i for i, row in enumerate(rows) if ready_rc(row) is not None), len(rows))
                        segments[page_number] = [row.rstrip() for row in rows[:end] if row.strip()]
                    previous = current

                    if current["state"] in {"more", "holding"}:
                        if not echo_seen:
                            raise RuntimeError("Paging appeared before the CP query echo; refusing to advance")
                        # CMS line-mode MORE/HOLDING is advanced with one Clear
                        # after capture, as in the native command bridge.
                        s.command("Clear")
                        released_hold = True
                        page_number += 1
                        continue

                    ready_rows = [i for i, row in enumerate(current["rows"][:22])
                                  if ready_rc(row) is not None]
                    echo_rows = [i for i, row in enumerate(current["rows"])
                                 if row.strip().upper() == expected_echo]
                    visible_rows = [i for i, row in enumerate(current['rows'][:22]) if row.strip()]
                    if (current["state"] == "cms_ready" and echo_seen and ready_rows
                            and visible_rows and max(ready_rows) == max(visible_rows)
                            and ((echo_rows and max(ready_rows) > max(echo_rows)) or released_hold)):
                        return {"vaddr": vaddr.upper(), "command": s.redact(command),
                                "pages": pages, "page_count": len(pages),
                                "output_rows": [row for segment in segments.values() for row in segment],
                                "output_complete": True, "completion_observed": True,
                                "cms_command_complete": None, "replacement_safe": False,
                                "link_query_is_lock": False,
                                "host_operations_performed": False}
                    # A cleared output page can arrive in pieces before Ready.
                    # Observe unknown/RUNNING passively; never advance it.
                    if current["state"] not in {"cms_ready", "more", "holding", "unknown"}:
                        raise RuntimeError("Unexpected terminal state during CP QUERY LINKS")
            raise TimeoutError("No fresh echoed CP QUERY LINKS result followed by CMS Ready")

        return s._run("query_links", work, timeout + 2)

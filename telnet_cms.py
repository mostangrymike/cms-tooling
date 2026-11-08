"""Native macOS telnet line-mode CMS transport prototype."""
from __future__ import annotations
import re
import pexpect

class CmsTelnet:
    def __init__(self, host='192.168.200.2', port=23, password=''):
        self.host, self.port, self.password = host, port, password
        self.child = None

    def connect(self, timeout=15):
        self.child = pexpect.spawn('telnet', [self.host, str(self.port)], encoding='utf-8', timeout=timeout)
        self.child.expect('PRESS BREAK KEY TO BEGIN SESSION')
        self.child.sendline('')
        self.child.expect(r'\.\x11')
        self.child.sendline('logon maint')
        self.child.expect('Enter password:')
        self.child.sendline(self.password)
        result = self.child.expect([r'z/VM V6\.3\.0', r'\bCP\r\n'])
        if result == 1:
            self.child.sendline('ipl')
            self.child.expect(r'z/VM V6\.3\.0')
        # Line-mode CMS may print the version banner before the first Ready
        # prompt. Use one benign query to synchronize the command boundary.
        self.child.sendline('q names')
        self.child.expect(r'Ready(?:\(-?\d+\))?;')
        return self.read()

    def command(self, command, timeout=120):
        if self.child is None:
            raise RuntimeError('not connected')
        self.child.timeout = timeout
        self.child.expect(r'\.\x11')
        self.child.sendline(command)
        self.child.expect(r'Ready(?:\(-?\d+\))?;')
        return self.read()

    def read(self):
        return self.child.before

    def close(self):
        if self.child is not None:
            self.child.sendline('logoff')
            self.child.close(force=True)
            self.child = None

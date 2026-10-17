"""Capture integrity, REXX flow-control and read-only policy tests. No network."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import zlib

from zvm_capture import Capture, CaptureError, frames, mask_frames, readonly_command
from zvm_commands import SOURCE, ready_rc
from zvm_mcp import classify

TOKEN = "0123456789ABCDEF"


def transcript(records, rc=0, token=TOKEN):
    seq = 0
    result = [f"ZM1 {token} B 0 {rc} {len(records)} {sum(map(len,records))} {zlib.adler32(b''.join(records))}"]
    for index, record in enumerate(records, 1):
        seq += 1
        result.append(f"ZM1 {token} R {seq} {index} {len(record)}")
        for offset in range(0,len(record),24):
            seq += 1
            result.append(f"ZM1 {token} D {seq} {record[offset:offset+24].hex().upper()}")
    result.append(f"ZM1 {token} Z {seq+1} DONE")
    return result


class CaptureTests(unittest.TestCase):
    def test_lossless_long_blank_duplicate_and_trailing_records(self):
        records = [b"", b"HELLO  ", bytes(range(256)), b"HELLO  "]
        cap = Capture(TOKEN)
        for line in transcript(records,28):
            self.assertTrue(cap.accept(line))
            self.assertFalse(cap.accept(line))
        self.assertEqual(cap.records, records)
        result = cap.result(lambda text:text, encoding="latin-1")
        self.assertEqual(result["cms_rc"],28)
        self.assertTrue(result["output_complete"])

    def test_empty_output_and_negative_rc(self):
        cap=Capture(TOKEN)
        for line in transcript([], -3):
            cap.accept(line)
        self.assertEqual(cap.result(str)["records"],[])
        self.assertEqual(cap.result(str)["cms_rc"],-3)

    def test_cp037_and_credentials_redacted_after_validation(self):
        cap=Capture(TOKEN)
        for line in transcript(["TESTUSER  ".encode("cp037")]):
            cap.accept(line)
        result=cap.result(lambda text:text.replace("TESTUSER","<REDACTED>"))
        self.assertEqual(result["records"],["<REDACTED>  "])

    def test_missing_end_never_returns_success(self):
        cap=Capture(TOKEN)
        for line in transcript([b"value"])[:-1]:
            cap.accept(line)
        with self.assertRaises(CaptureError):
            cap.result(str)

    def test_missing_frame_and_foreign_nonce_rejected(self):
        cap=Capture(TOKEN)
        lines=transcript([b"value"])
        cap.accept(lines[0])
        with self.assertRaises(CaptureError):
            cap.accept(lines[2])
        with self.assertRaises(CaptureError):
            cap.accept(lines[1].replace(TOKEN,"FEDCBA9876543210"))

    def test_tampered_data_checksum_and_lengths_rejected(self):
        lines=transcript([b"value"])
        for mutation in (lambda line:line.replace("76616C7565","76616C7564"),
                         lambda line:line.replace(" R 1 1 5"," R 1 1 6"),
                         lambda line:line.replace(" B 0 0 1 5 "," B 0 0 1 6 ")):
            with self.subTest(mutation=mutation), self.assertRaises(CaptureError):
                cap=Capture(TOKEN)
                for line in lines:
                    cap.accept(mutation(line))

    def test_conflicting_duplicate_rejected(self):
        cap=Capture(TOKEN)
        cap.accept(transcript([b"a"])[0])
        with self.assertRaises(CaptureError):
            cap.accept(transcript([b"b"])[0])

    def test_limits_and_host_failure_are_explicit(self):
        for line in (f"ZM1 {TOKEN} B 0 0 4097 0 1",f"ZM1 {TOKEN} F 0 LIMIT"):
            with self.assertRaises(CaptureError):
                Capture(TOKEN).accept(line)

    def test_screen_hex_payloads_are_never_diagnostic_output(self):
        line=f"ZM1 {TOKEN} D 3 E3C5E2E3E4E2C5D9"
        safe=mask_frames([line.ljust(80)])
        self.assertNotIn("E3C5E2E3E4E2C5D9",json.dumps(safe))
        self.assertEqual(len(safe[0]),80)
        self.assertIn(3,frames([line],TOKEN))
        self.assertFalse(frames([line],"FEDCBA9876543210"))

    def test_readonly_policy_excludes_write_options_and_injection(self):
        self.assertEqual(readonly_command("  query cmslevel "),"QUERY CMSLEVEL")
        self.assertEqual(readonly_command("listfile * * a"),"LISTFILE * * A")
        self.assertEqual(readonly_command("state ABSENT EXEC A"),"STATE ABSENT EXEC A")
        for cmd in ("ERASE X Y A","LISTFILE * * A (EXEC","QUERY DISK|ERASE X Y A",
                    "QUERY DISK\nERASE X Y A","STATE * * A","EXEC GITRUN","QUERY DISK #CP IPL CMS",
                    "STATE #ERASE X A", "LISTFILE #ERASE X A"):
            with self.subTest(cmd=cmd), self.assertRaises(ValueError):
                readonly_command(cmd)

    def test_ready_rc_formats(self):
        for message,rc in (("Ready; T=0.01/0.01",0),("Ready(00028); T=0.01",28),
                           ("Ready; (00028)",28),("Ready(-00003);",-3)):
            self.assertEqual(ready_rc(message),rc)
            self.assertEqual(classify([message])["state"],"cms_ready")

    def test_runner_source_fixed80_and_no_file_output(self):
        source=SOURCE.read_text()
        self.assertTrue(all(len(line)<=80 for line in source.splitlines()))
        self.assertNotRegex(source.upper(),r"\b(ERASE|DISKW|GENMOD|REPLACE)\b")
        self.assertIn("cmdrc=rc",source)

    @unittest.skipUnless(shutil.which("rexx"),"Local REXX interpreter is not installed")
    def test_real_rexx_framing_and_acknowledgements_offline(self):
        # Replace ONLY the CMS-specific capture instruction with synthetic data;
        # the REXX framing, checksum, chunking and PULL handshake execute for real.
        source=SOURCE.read_text().replace("'PIPE CMS' cmd '| TAKE 4097 | STEM out.'\ncmdrc=rc",
             "out.0=3\nout.1='HELLO  '\nout.2=''\nout.3=copies('A',80)\ncmdrc=28")
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"runner.rexx"
            path.write_text(source)
            p=subprocess.Popen([shutil.which("rexx"),str(path),TOKEN,"QUERY CMSLEVEL"],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            cap=Capture(TOKEN)
            try:
                while not cap.complete:
                    line=p.stdout.readline().rstrip("\n")
                    self.assertTrue(line, "REXX runner stopped before end frame")
                    cap.accept(line)
                    seq=int(line.split()[3])
                    p.stdin.write(f"ZA1 {TOKEN} {seq}\n")
                    p.stdin.flush()
                p.stdin.close()
                self.assertEqual(p.wait(timeout=3),0,p.stderr.read())
                self.assertEqual(cap.records,[b"HELLO  ",b"",b"A"*80])
                self.assertEqual(cap.header[0],28)
            finally:
                if p.poll() is None:
                    p.kill()
                    p.wait(timeout=3)
                for stream in (p.stdin,p.stdout,p.stderr):
                    stream.close()

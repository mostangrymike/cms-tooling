"""Offline qualification for exact long-record MODULE reconstruction."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from test_zvm_capture import Capture, TOKEN
from test_zvm_download import capture
from zvm_fixture_output import ModuleReader, SOURCE, module_metadata, policy, unpack, retained_outputs
from zvm_mcp import Session
from zvm_edit import canonical, sha, validate_manifest
from zvm_download import metadata, save_snapshot


META = 'ZTQUAL MODULE A1 V 52312 3 14 10/17/26 11:11:54 MNT191'


def packed(records):
    layout = ('ZMO1 3 ' + ' '.join(str(len(record)) for record in records)).encode('cp037')
    raw = b''.join(records)
    return capture([layout, *[raw[i:i+4096] for i in range(0, len(raw), 4096)]])


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True, capture_output=True)
        self.records = [bytes(range(256)) * 204 + bytes(range(88)), b'', b'\x00\x40\xff']
        self.assertEqual(len(self.records[0]), 52312)

    def service(self, responses=None):
        session = Session(allow_commands=True, allow_downloads=True)
        reader = ModuleReader(session, self.repo / 'outputs', 'ZMABCDEF')
        reader.reader.verified = True
        responses = responses or [capture([META.encode('cp037')]), packed(self.records),
                                  packed(self.records), capture([META.encode('cp037')])]
        reader.reader.run = Mock(side_effect=responses)
        return session, reader

    def test_exact_output_policy_and_geometry(self):
        self.assertEqual(policy('FILEREAD ZTQUAL MODULE A1'), 'FILEREAD ZTQUAL MODULE A1')
        for command in ('FILEREAD GITC26 MODULE G1', 'FILEMETA ZTQUAL C A1',
                        'FILEREAD ZTQUAL MODULE A', 'FILEREAD ZTQUAL MODULE A1 # ERASE X'):
            with self.assertRaises(ValueError): policy(command)
        self.assertEqual(module_metadata([META])['lrecl'], 52312)
        for rows in ([META, META], [META.replace('52312', '52313')],
                     [META.replace('MNT191', 'OTHER')], [META.replace(' V ', ' F ')]):
            with self.assertRaises(ValueError): module_metadata(rows)

    def test_native_long_records_binary_empty_and_boundaries_roundtrip(self):
        self.assertEqual(unpack(packed(self.records)), self.records)
        _, reader = self.service()
        result = reader.download()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['record_lengths'], [52312, 0, 3])
        raw = Path(result['native_file']).read_bytes()
        self.assertEqual(raw, b''.join(self.records))
        self.assertEqual(result['sha256'], sha(raw))
        self.assertFalse(result['source_editing_supported'])
        with self.assertRaises(ValueError): validate_manifest(Path(result['manifest']).read_bytes(), raw)
        self.assertEqual([call.args[0] for call in reader.reader.run.call_args_list],
                         ['FILEMETA ZTQUAL MODULE A1', 'FILEREAD ZTQUAL MODULE A1',
                          'FILEREAD ZTQUAL MODULE A1', 'FILEMETA ZTQUAL MODULE A1'])
        self.assertTrue(all(1 <= call.args[1] <= 600 for call in reader.reader.run.call_args_list))

    def test_malformed_layout_counts_lengths_checksum_and_credentials_refused(self):
        for key, value in (('cms_rc', 12), ('integrity_verified', False),
                           ('output_complete', False), ('cms_command_complete', False),
                           ('redaction_applied', True), ('adler32', '00000000'), ('record_count', 1)):
            result = packed(self.records)
            result[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): unpack(result)
        raw = b''.join(self.records)
        for layout in ('ZMO1 2 52312 3', 'ZMO1 3 52313 0 2', 'ZMO1 3 52312 0 4'):
            result = capture([layout.encode('cp037'), *[raw[i:i+4096] for i in range(0, len(raw), 4096)]])
            with self.assertRaises(ValueError): unpack(result)

    def test_different_reads_or_metadata_stop_without_snapshot(self):
        for changed in ('bytes', 'metadata'):
            other = [*self.records[:-1], b'ABC']
            responses = [capture([META.encode('cp037')]), packed(self.records),
                         packed(other if changed == 'bytes' else self.records),
                         capture([META.replace('11:11:54', '11:11:55').encode('cp037')])]
            _, reader = self.service(responses)
            result = reader.download()
            self.assertFalse(result['ok'])
            self.assertFalse((self.repo / 'outputs').exists())

    def test_failure_stops_before_next_capture_without_retry(self):
        responses = [capture([META.encode('cp037')]), {'ok': False, 'message': 'synthetic interrupted read'}]
        _, reader = self.service(responses)
        result = reader.download()
        self.assertFalse(result['ok'])
        self.assertEqual(reader.reader.run.call_count, 2)
        self.assertFalse((self.repo / 'outputs').exists())

    def test_verification_and_capabilities_required_before_read(self):
        for changed in ('verified', 'downloads', 'commands'):
            session, reader = self.service()
            if changed == 'verified': reader.reader.verified = False
            if changed == 'downloads': session.allow_downloads = False
            if changed == 'commands': session.allow_commands = False
            self.assertFalse(reader.download()['ok'])
            reader.reader.run.assert_not_called()

    def test_standard_runner_deadline_stays_bounded(self):
        session = Session(allow_commands=True)
        session.runner.verified = True
        self.assertFalse(session.runner.run('QUERY DISK', timeout=600)['ok'])

    def test_retained_output_receipts_revalidate_all_native_artifacts(self):
        import validate_zvm_fixture as fixture
        declared = fixture.contract()
        journal = {'contract': declared, 'contract_sha256': sha(canonical(declared)),
                   'prior_evidence_sha256': '1' * 64, 'steps': []}
        for ft in ('ASSEMBLE', 'TEXT', 'LISTING'):
            meta = metadata([f'ZTQUAL {ft} A1 F 8 2 1 10/17/26 11:11:54 MNT191'], ('ZTQUAL', ft, 'A1'))
            result = save_snapshot(self.repo / 'outputs', self.repo, meta, [b'A' * 8, b'B' * 8], [])
            result.update(ok=True, manifest_sha256=sha(Path(result['manifest']).read_bytes()))
            journal['steps'].append({'step': f'audit native output ZTQUAL {ft} A1',
                                     'state': 'complete', 'result': result})
        path = self.repo / 'journal.json'
        path.write_bytes(canonical(journal))
        digest = sha(path.read_bytes())
        outputs = retained_outputs(path, digest, '1' * 64)
        self.assertEqual(len(outputs), 3)
        self.assertTrue(all(not result['fresh_host_read'] for result in outputs.values()))
        with self.assertRaises(ValueError): retained_outputs(path, '0' * 64)
        with self.assertRaises(ValueError): retained_outputs(path, digest, '2' * 64)
        Path(journal['steps'][0]['result']['native_file']).write_bytes(b'changed')
        with self.assertRaises(ValueError): retained_outputs(path, digest, '1' * 64)

    @unittest.skipUnless(shutil.which('rexx'), 'Local REXX interpreter unavailable')
    def test_real_rexx_long_native_chunks_reconstruct_original_records(self):
        source = SOURCE.read_text()
        self.assertTrue(all(len(line) <= 80 for line in source.splitlines()))
        source = source.replace("'PIPE <' fn ft fm '| TAKE 4 | STEM out.'\n cmdrc=rc",
            "out.0=3\n out.1=copies('A',52312)\n out.2=''\n out.3='END  '\n cmdrc=0")
        script = self.repo / 'output.rexx'
        script.write_text(source)
        process = subprocess.Popen([shutil.which('rexx'), str(script), TOKEN,
                                    'FILEREAD', 'ZTQUAL', 'MODULE', 'A1'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        cap = Capture(TOKEN)
        try:
            while not cap.complete:
                line = process.stdout.readline().rstrip('\n')
                self.assertTrue(line, 'Native reader ended before terminal marker')
                cap.accept(line)
                process.stdin.write(f'ZA1 {TOKEN} {line.split()[3]}\n')
                process.stdin.flush()
            process.stdin.close()
            self.assertEqual(process.wait(timeout=5), 0, process.stderr.read())
            # Regina's literals are ASCII; emulate only the host character set
            # for the layout record. Native data itself must remain unchanged.
            records = cap.records
            records[0] = records[0].decode('ascii').encode('cp037')
            self.assertEqual(unpack(capture(records)), [b'A' * 52312, b'', b'END  '])
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=3)
            for stream in (process.stdin, process.stdout, process.stderr): stream.close()


if __name__ == '__main__':
    unittest.main()

"""Offline native-file download safety, consistency, and local snapshot tests."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib

from test_zvm_capture import Capture, TOKEN
from zvm_download import (SOURCE, file_id, reader_command, metadata, native_records,
                          git_root_for, save_snapshot)
from zvm_mcp import Session


META = 'TEST EXEC A1 F 8 2 1 10/16/2026 15:00:00 USER01'


def capture(records, rc=0):
    raw=b''.join(records)
    return {'ok':True,'cms_rc':rc,'records':[r.decode('cp037') for r in records],
        'encoding':'cp037','record_count':len(records),'byte_count':len(raw),
        'adler32':f'{zlib.adler32(raw):08x}','integrity_verified':True,
        'output_complete':True,'cms_command_complete':True,'redaction_applied':False,
        'request_id':TOKEN,'frames_verified':3}


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.repo=Path(self.temp.name).resolve()
        subprocess.run(['git','init','-q',str(self.repo)],check=True,capture_output=True)
        self.root=self.repo/'sources'
        self.records=['HELLO   '.encode('cp037'),'NEXT    '.encode('cp037')]

    def tearDown(self):
        self.temp.cleanup()

    def service(self, results=None):
        s=Session(allow_commands=True,allow_downloads=True,download_root=self.root,
                  download_runner_name='ZMABCDEF')
        d=s.downloader
        d.reader.verified=True
        responses=results or [capture([META.encode('cp037')]),capture(self.records),
                              capture(self.records),capture([META.encode('cp037')])]
        calls=[]
        def run(command, timeout):
            calls.append(command)
            return responses.pop(0)
        d.reader.run=run
        return s,d,calls

    def test_fixed_download_preserves_native_bytes_and_trailing_blanks(self):
        s,d,calls=self.service()
        result=d.download('test','exec','a')
        self.assertTrue(result['ok'],result)
        self.assertTrue(result['download_complete'])
        self.assertEqual(Path(result['native_file']).read_bytes(),b''.join(self.records))
        self.assertEqual(Path(result['text_file']).read_text(),'HELLO   \nNEXT    \n')
        manifest=json.loads(Path(result['manifest']).read_text())
        self.assertEqual(manifest['record_lengths'],[8,8])
        self.assertEqual(manifest['cms']['filemode'],'A1')
        self.assertEqual(manifest['sha256'],hashlib.sha256(b''.join(self.records)).hexdigest())
        self.assertEqual(calls,['FILEMETA TEST EXEC A','FILEREAD TEST EXEC A1',
                                'FILEREAD TEST EXEC A1','FILEMETA TEST EXEC A1'])
        self.assertFalse(result['atomic_host_snapshot'])
        self.assertFalse(result['host_source_modified'])

    def test_variable_empty_duplicate_and_long_records_preserve_boundaries(self):
        records=[b'',b'\xc1\x40',b'\xc1\x40',b'\xc2'*100]
        meta=metadata(['TEST EXEC A1 V 100 4 1 10/16/26 15:00:00 USER01'],('TEST','EXEC','A'))
        decoded=native_records(capture(records),meta)
        root,worktree=git_root_for(self.root)
        out=save_snapshot(root,worktree,meta,decoded,[])
        m=json.loads(Path(out['manifest']).read_text())
        self.assertEqual(m['record_lengths'],[0,2,2,100])
        self.assertEqual(Path(out['native_file']).read_bytes(),b''.join(records))
        self.assertEqual(len(m['records_sha256']),4)

    def test_new_snapshot_never_replaces_prior_snapshot(self):
        _,d,_=self.service(); first=d.download('TEST','EXEC','A')
        _,d,_=self.service(); second=d.download('TEST','EXEC','A')
        self.assertNotEqual(first['snapshot_directory'],second['snapshot_directory'])
        self.assertEqual(Path(first['native_file']).read_bytes(),b''.join(self.records))

    def test_empty_file_and_empty_variable_records(self):
        for count in (0,2):
            meta=metadata([f'TEST EXEC A1 V 0 {count} 1 10/16/26 15:00:00 USER01'],('TEST','EXEC','A'))
            self.assertEqual(native_records(capture([b'']*count),meta),[b'']*count)

    def test_changed_data_or_metadata_refuses_local_snapshot(self):
        for change in ('bytes','metadata'):
            with self.subTest(change=change):
                results=[capture([META.encode('cp037')]),capture(self.records),
                         capture([b'\xc2'*8]*2 if change=='bytes' else self.records),
                         capture([META.replace('15:00:00','15:00:01').encode('cp037')])]
                _,d,_=self.service(results)
                out=d.download('TEST','EXEC','A')
                self.assertFalse(out['ok'])
                self.assertIn('changed during capture',out['message'])
                self.assertFalse(self.root.exists())

    def test_credentials_redaction_refuses_native_export(self):
        result=capture(self.records); result['redaction_applied']=True
        _,d,_=self.service([capture([META.encode('cp037')]),result])
        out=d.download('TEST','EXEC','A')
        self.assertFalse(out['ok'])
        self.assertIn('credentials',out['message'])
        self.assertFalse(self.root.exists())

    def test_invalid_identifiers_and_disabled_download_never_run_terminal(self):
        s,d,calls=self.service()
        for ident in [('../X','EXEC','A'),('*','EXEC','A'),('X','EXEC','*'),('X\nERASE','EXEC','A'),('#ERASE','X','A')]:
            self.assertFalse(d.download(*ident)['ok'])
        s.allow_downloads=False
        self.assertFalse(d.download('TEST','EXEC','A')['ok'])
        self.assertEqual(calls,[])
        self.assertFalse(self.root.exists())
        for command in ('FILEMETA X EXEC A (EXEC','FILEREAD * EXEC A','ERASE X EXEC A'):
            with self.assertRaises(ValueError): reader_command(command)

    def test_bad_return_code_is_not_download_success(self):
        _,d,_=self.service([capture([],28)])
        result=d.download('ABSENT','EXEC','A')
        self.assertFalse(result['ok'])
        self.assertEqual(result['evidence'][0]['cms_rc'],28)
        self.assertFalse(self.root.exists())

    def test_lengths_checksum_and_metadata_must_match(self):
        meta=metadata([META],('TEST','EXEC','A'))
        for result in [capture([b'\xc1'*7]*2),capture(self.records)]:
            if result['byte_count']==16: result['adler32']='00000000'
            with self.assertRaises(ValueError): native_records(result,meta)
        for rows in [[META,META],[META.replace('A1','B1')],[META.replace(' F ',' U ')],[]]:
            with self.assertRaises(ValueError): metadata(rows,('TEST','EXEC','A'))

    def test_symlink_and_non_git_destinations_refused(self):
        link=self.repo/'alias'; link.symlink_to(self.repo,target_is_directory=True)
        with self.assertRaises(ValueError): git_root_for(link/'sources')
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaises(ValueError): git_root_for(Path(outside)/'sources')

    def test_binary_records_have_no_misleading_text_view(self):
        records=[bytes(range(8))]*2
        meta=metadata([META],('TEST','EXEC','A'))
        root,worktree=git_root_for(self.root)
        out=save_snapshot(root,worktree,meta,records,[])
        self.assertIsNone(out['text_file'])
        self.assertEqual(Path(out['native_file']).read_bytes(),b''.join(records))

    def test_disconnect_invalidates_reader_verification(self):
        s,d,_=self.service()
        s.disconnect()
        self.assertFalse(d.reader.verified)

    def test_reader_requires_verified_source_before_capture(self):
        s,d,calls=self.service(); d.reader.verified=False
        d.reader.prepare=lambda create,timeout: {'ok':False,'message':'source differs'}
        out=d.download('TEST','EXEC','A')
        self.assertFalse(out['ok'])
        self.assertEqual(out['stage'],'prepare_reader')
        self.assertEqual(calls,[])

    def test_reader_preparation_respects_short_download_deadline(self):
        _,d,_=self.service();d.reader.verified=False
        budgets=[]
        def prepare(create,timeout):
            budgets.append(timeout)
            return {'ok':False,'message':'synthetic stop before host access'}
        d.reader.prepare=prepare
        self.assertFalse(d.download('TEST','EXEC','A',timeout=30)['ok'])
        self.assertTrue(1<=budgets[0]<=30)

    def test_local_write_failure_removes_only_new_partial_snapshot(self):
        _,d,_=self.service()
        original=Path.open
        def fail_manifest(path,*args,**kwargs):
            if path.name=='manifest.json':raise PermissionError('synthetic local failure')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',fail_manifest):
            result=d.download('TEST','EXEC','A')
        self.assertFalse(result['ok'])
        self.assertEqual(list(self.root.iterdir()),[])

    def test_command_and_reader_share_correlated_completion_boundary(self):
        from test_zvm_commands import CommandEmulator
        fake=CommandEmulator(records=[b'\xc1'*8])
        s=Session(factory=lambda:fake,allow_commands=True,allow_downloads=True,
                  download_root=self.root,download_runner_name='ZMABCDEF')
        s.connect('0200@')
        s.runner.name='ZM123456';s.runner.verified=True
        s.downloader.reader.verified=True
        self.assertTrue(s.runner.run('QUERY CMSLEVEL')['ok'])
        self.assertTrue(s.downloader.reader.run('FILEREAD TEST EXEC A1')['ok'])
        self.assertTrue(s.runner.run('QUERY DISK')['ok'])

    def test_reader_source_fixed80_and_no_output_commands(self):
        source=SOURCE.read_text()
        self.assertTrue(all(len(line)<=80 for line in source.splitlines()))
        self.assertNotRegex(source.upper(),r'\b(ERASE|DISKW|REPLACE|COPYFILE|PUNCH)\b')
        self.assertIn("'PIPE <' fn ft fm",source)
        self.assertIn("'(LABEL | TAKE 4097 | STEM out.'",source)

    @unittest.skipUnless(shutil.which('rexx'),'Local REXX interpreter unavailable')
    def test_real_reader_rexx_frames_with_synthetic_host_input(self):
        source=SOURCE.read_text().replace("'PIPE CMS LISTFILE' fn ft fm '(LABEL | TAKE 4097 | STEM out.'\n cmdrc=rc", "out.0=1\n out.1='TEST EXEC A1 V 8 2 1 10/16/26 15:00:00 USER01'\n cmdrc=0")
        source=source.replace("'PIPE <' fn ft fm '| TAKE 4097 | STEM out.'\n cmdrc=rc", "out.0=2\n out.1=''\n out.2='VALUE   '\n cmdrc=0")
        script=self.repo/'reader.rexx'; script.write_text(source)
        for verb in ('FILEMETA','FILEREAD'):
            p=subprocess.Popen([shutil.which('rexx'),str(script),TOKEN,verb,'TEST','EXEC','A'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            cap=Capture(TOKEN)
            try:
                while not cap.complete:
                    line=p.stdout.readline().rstrip('\n')
                    self.assertTrue(line,'Reader stopped before terminal marker')
                    cap.accept(line)
                    p.stdin.write(f'ZA1 {TOKEN} {line.split()[3]}\n');p.stdin.flush()
                p.stdin.close()
                self.assertEqual(p.wait(timeout=3),0,p.stderr.read())
                self.assertEqual(cap.header[0],0)
                if verb=='FILEREAD': self.assertEqual(cap.records,[b'',b'VALUE   '])
            finally:
                if p.poll() is None:p.kill();p.wait(timeout=3)
                for stream in (p.stdin,p.stdout,p.stderr):stream.close()


if __name__=='__main__': unittest.main()

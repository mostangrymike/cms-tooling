"""Offline edit baselines, exact record encoding, review plans, and failure guards."""
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import Mock, patch

from zvm_download import metadata, save_snapshot
from zvm_edit import encode_edit, read_file
from zvm_credentials import Credentials
from zvm_mcp import Session


class EditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.repo=Path(self.temp.name).resolve()
        subprocess.run(['git','init','-q',str(self.repo)],check=True,capture_output=True)
        self.root=self.repo/'sources'
        self.s=Session(allow_local_edits=True,download_root=self.root,
                       factory=Mock(side_effect=AssertionError('No terminal allowed')))
        self.meta=metadata(['TEST EXEC A1 F 8 2 1 10/16/26 15:00:00 USER01'],('TEST','EXEC','A1'))
        self.records=[b'\xc1\xc2'+b'\x40'*6,b'\xc3'+b'\x40'*7]
        self.snapshot=save_snapshot(self.root,self.repo,self.meta,self.records,[])
        self.sid=Path(self.snapshot['snapshot_directory']).name

    def tearDown(self):self.temp.cleanup()

    def prepare(self):
        r=self.s.edits.prepare(self.sid)
        self.assertTrue(r['ok'],r)
        return r

    def test_noop_fixed_edit_is_exact_native_roundtrip_and_never_connects(self):
        prepared=self.prepare()
        self.assertEqual(Path(prepared['editable_file']).read_bytes(),b'AB\nC\n')
        result=self.s.edits.plan(prepared['edit_id'])
        self.assertTrue(result['ok'],result)
        self.assertFalse(result['changed'])
        self.assertEqual(Path(result['candidate_file']).read_bytes(),b''.join(self.records))
        self.assertEqual(Path(result['diff_file']).read_bytes(),b'')
        self.assertFalse(result['upload_authorized'])
        self.assertFalse(result['upload_implemented'])
        self.assertIsNone(self.s.em)
        self.s.factory.assert_not_called()

    def test_fixed_edit_diff_hashes_and_pinned_original(self):
        prepared=self.prepare()
        Path(prepared['editable_file']).write_bytes(b'AB\nCHANGED\nNEW\n')
        result=self.s.edits.plan(prepared['edit_id'])
        self.assertTrue(result['ok'],result)
        plan=json.loads(Path(result['plan_file']).read_text())
        self.assertTrue(result['changed'])
        self.assertEqual(plan['proposed']['record_lengths'],[8,8,8])
        self.assertEqual(plan['expected_original']['sha256'],hashlib.sha256(b''.join(self.records)).hexdigest())
        self.assertEqual(plan['proposed']['sha256'],result['candidate_sha256'])
        self.assertEqual(hashlib.sha256(Path(result['plan_file']).read_bytes()).hexdigest(),result['plan_sha256'])
        diff=Path(result['diff_file']).read_text()
        self.assertIn('-C\n',diff);self.assertIn('+CHANGED\n',diff)
        self.assertEqual(Path(self.snapshot['native_file']).read_bytes(),b''.join(self.records))
        self.assertFalse(plan['upload_authorized'])

    def test_variable_blank_duplicate_records_and_trailing_spaces_preserved(self):
        records=[b'',b'\xc1\x40',b'\xc1\x40',b'\xc2'*8]
        meta=metadata(['VAR DATA A1 V 8 4 1 10/16/26 15:00:00 USER01'],('VAR','DATA','A1'))
        out=save_snapshot(self.root,self.repo,meta,records,[])
        p=self.s.edits.prepare(Path(out['snapshot_directory']).name)
        self.assertTrue(p['ok'],p)
        self.assertEqual(Path(p['editable_file']).read_bytes(),b'\nA \nA \nBBBBBBBB\n')
        result=self.s.edits.plan(p['edit_id'])
        self.assertTrue(result['ok'],result)
        self.assertFalse(result['changed'])
        self.assertEqual(Path(result['candidate_file']).read_bytes(),b''.join(records))
        Path(p['editable_file']).write_bytes(b'\nA\nA \nB\n')
        result=self.s.edits.plan(p['edit_id'])
        self.assertTrue(result['ok'],result)
        plan=json.loads(Path(result['plan_file']).read_text())
        self.assertEqual(plan['proposed']['record_lengths'],[0,1,2,1])
        self.assertEqual(plan['proposed']['lrecl'],2)

    def test_overlong_unencodable_controls_and_missing_lf_are_refused(self):
        prepared=self.prepare()
        for content in [b'123456789\n',b'AB\r\n',b'AB',b'AB\x00\n','A😀\n'.encode(),b'\xef\xbb\xbfAB\n']:
            with self.subTest(content_length=len(content)):
                Path(prepared['editable_file']).write_bytes(content)
                r=self.s.edits.plan(prepared['edit_id'])
                self.assertFalse(r['ok'])
                self.assertEqual(list(Path(prepared['definition']).parent.glob('plan-*')),[])

    def test_snapshot_native_or_manifest_tampering_refuses_preparation(self):
        raw=Path(self.snapshot['native_file']);original=raw.read_bytes()
        raw.write_bytes(b'\xc2'*len(original))
        self.assertFalse(self.s.edits.prepare(self.sid)['ok'])
        raw.write_bytes(original)
        manifest=Path(self.snapshot['manifest']);m=json.loads(manifest.read_text())
        m['record_lengths']=[7,9];manifest.write_text(json.dumps(m))
        self.assertFalse(self.s.edits.prepare(self.sid)['ok'])

    def test_original_changed_after_prepare_even_if_rehashed_is_refused(self):
        prepared=self.prepare()
        manifest=Path(self.snapshot['manifest']);m=json.loads(manifest.read_text())
        raw=b'\xc2'*16
        Path(self.snapshot['native_file']).write_bytes(raw)
        m['sha256']=hashlib.sha256(raw).hexdigest()
        m['records_sha256']=[hashlib.sha256(raw[:8]).hexdigest()]*2
        manifest.write_text(json.dumps(m))
        r=self.s.edits.plan(prepared['edit_id'])
        self.assertFalse(r['ok']);self.assertIn('changed',r['message'])

    def test_baseline_tampering_or_target_retargeting_is_refused(self):
        prepared=self.prepare();folder=Path(prepared['definition']).parent
        (folder/'baseline.ebcdic').write_bytes(b'\xc2'*16)
        self.assertFalse(self.s.edits.plan(prepared['edit_id'])['ok'])
        (folder/'baseline.ebcdic').write_bytes(b''.join(self.records))
        d=json.loads(Path(prepared['definition']).read_text());d['cms']['filename']='OTHER'
        Path(prepared['definition']).write_text(json.dumps(d))
        self.assertFalse(self.s.edits.plan(prepared['edit_id'])['ok'])

    def test_repeated_plans_and_id_collisions_never_replace_or_delete_prior_work(self):
        prepared=self.prepare()
        first=self.s.edits.plan(prepared['edit_id'])
        second=self.s.edits.plan(prepared['edit_id'])
        self.assertNotEqual(first['plan_id'],second['plan_id'])
        original=Path(first['plan_file']).read_bytes()
        with patch('zvm_edit.secrets.token_hex',return_value=first['plan_id'][5:]):
            self.assertFalse(self.s.edits.plan(prepared['edit_id'])['ok'])
        self.assertEqual(Path(first['plan_file']).read_bytes(),original)
        with patch('zvm_edit.secrets.token_hex',return_value=prepared['edit_id'][5:]):
            self.assertFalse(self.s.edits.prepare(self.sid)['ok'])
        self.assertTrue(Path(prepared['editable_file']).exists())

    def test_symlink_snapshot_file_edit_file_or_parent_is_refused(self):
        prepared=self.prepare();working=Path(prepared['editable_file'])
        outside=self.repo/'outside';outside.write_bytes(b'AB\n')
        working.unlink();working.symlink_to(outside)
        self.assertFalse(self.s.edits.plan(prepared['edit_id'])['ok'])
        working.unlink();working.parent.rmdir();working.parent.symlink_to(self.repo,target_is_directory=True)
        self.assertFalse(self.s.edits.plan(prepared['edit_id'])['ok'])
        native=Path(self.snapshot['native_file']);native.unlink();native.symlink_to(outside)
        self.assertFalse(self.s.edits.prepare(self.sid)['ok'])

    def test_credential_provider_is_used_without_login_and_values_never_returned(self):
        provider=Mock();provider.load.return_value=Credentials('LOCALUSR','SECRET12')
        self.s.credential_provider=provider
        prepared=self.prepare()
        provider.load.assert_called()
        Path(prepared['editable_file']).write_bytes(b'SECRET12\n')
        result=self.s.edits.plan(prepared['edit_id'])
        self.assertFalse(result['ok']);self.assertNotIn('SECRET12',json.dumps(result))
        self.assertIn('credentials',result['message'])
        self.s.factory.assert_not_called()

    def test_credential_containing_baseline_is_refused_before_new_files(self):
        self.s.secrets.add('AB')
        self.assertFalse(self.s.edits.prepare(self.sid)['ok'])
        self.assertFalse((self.root/'edits').exists())

    def test_disabled_invalid_ids_or_paths_do_not_touch_files_or_terminal(self):
        for value in ('../snapshot-123','/tmp/x','snapshot-'+'0'*23,'SNAPSHOT-'+'0'*24):
            self.assertFalse(self.s.edits.prepare(value)['ok'])
            self.assertFalse(self.s.edits.plan(value)['ok'])
        self.s.allow_local_edits=False
        self.assertFalse(self.s.edits.prepare(self.sid)['ok'])
        self.assertFalse((self.root/'edits').exists())
        self.s.factory.assert_not_called()

    def test_empty_file_and_empty_fixed_record_are_distinct(self):
        self.assertEqual(encode_edit(b'',self.meta),[])
        self.assertEqual(encode_edit(b'\n',self.meta),[b'\x40'*8])
        self.assertEqual(encode_edit(b'\n\n',self.meta),[b'\x40'*8]*2)
        with self.assertRaises(ValueError):encode_edit(b'A\n'*4097,self.meta)

    def test_binary_baseline_is_not_opened_as_text(self):
        out=save_snapshot(self.root,self.repo,self.meta,[bytes(range(8))]*2,[])
        result=self.s.edits.prepare(Path(out['snapshot_directory']).name)
        self.assertFalse(result['ok']);self.assertIn('Binary',result['message'])

    def test_reserved_cms_names_are_isolated_from_edit_control_files(self):
        meta=metadata(['EDIT JSON A1 F 8 2 1 10/16/26 15:00:00 USER01'],('EDIT','JSON','A1'))
        out=save_snapshot(self.root,self.repo,meta,self.records,[])
        p=self.s.edits.prepare(Path(out['snapshot_directory']).name)
        self.assertTrue(p['ok'],p)
        self.assertTrue(self.s.edits.plan(p['edit_id'])['ok'])

    def test_partial_local_write_failure_cleans_only_new_directory(self):
        with patch.object(self.s.edits,'write',side_effect=PermissionError('synthetic write failure')):
            self.assertFalse(self.s.edits.prepare(self.sid)['ok'])
        self.assertEqual(list((self.root/'edits').iterdir()),[])
        self.assertTrue(Path(self.snapshot['native_file']).exists())
        prepared=self.prepare()
        with patch.object(self.s.edits,'write',side_effect=PermissionError('synthetic write failure')):
            self.assertFalse(self.s.edits.plan(prepared['edit_id'])['ok'])
        self.assertTrue(Path(prepared['editable_file']).exists())
        self.assertEqual(list(Path(prepared['definition']).parent.glob('plan-*')),[])

    def test_fifo_and_oversized_files_are_refused(self):
        import os
        fifo=self.repo/'fifo';os.mkfifo(fifo)
        with self.assertRaises(ValueError):read_file(fifo,100)
        path=self.repo/'large';path.write_bytes(b'x'*101)
        with self.assertRaises(ValueError):read_file(path,100)


if __name__=='__main__':unittest.main()

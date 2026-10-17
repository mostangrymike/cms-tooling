"""Offline terminal integration for provisioning, framing and terminal completion."""
import json
from pathlib import Path
import re
import time
import unittest
from unittest.mock import Mock

from test_cms_mcp import FakeEmulator, buffer, screen
from test_cms_capture import transcript
from cms_mcp import Session


class CommandEmulator(FakeEmulator):
    def __init__(self, records=None, rc=0, final_ready=True):
        super().__init__(screen("Ready;", " "*60+"RUNNING"))
        self.buffer=buffer({1759:"01",1899:"20",1918:"20",1919:"20"})
        self.records=records if records is not None else [b"RESULT"]
        self.rc=rc
        self.final_ready=final_ready
        self.queued=""
        self.stream=[]
        self.index=0
        self.host_files={}
        self.corrupt_source=False
        self.aid_wait=False
        self.transfer_restoring=0
        self.transfer_count=0

    def publish(self):
        self.rows=screen("Ready; old prompt", " "*60+"RUNNING")
        if self.index<len(self.stream):
            self.rows[1]=self.stream[self.index].ljust(80)
        elif self.final_ready:
            self.rows[1]=self.stream[-1].ljust(80)
            self.rows[2]="Ready; T=0.01/0.01".ljust(80)

    def exec_command(self, action):
        text=action.decode()
        if text=="Set(AidWait,true)":
            self.aid_wait=True
        elif text=="Set(AidWait,false)":
            self.aid_wait=False
        if text.startswith('String("'):
            self.queued=text[8:-2]
        elif text.startswith("HexString("):
            self.queued=bytes.fromhex(text[10:-1]).decode("cp037")
        if text=="Enter":
            if self.queued.startswith("EXEC "):
                token=self.queued.split()[2]
                self.stream=transcript(self.records,self.rc,token)
                self.index=0
                self.publish()
            elif self.queued.startswith("ZA1 "):
                expected=int(self.stream[self.index].split()[3])
                assert int(self.queued.split()[2])==expected
                self.index+=1
                self.publish()
            elif self.queued.startswith("STATE "):
                name=self.queued.split()[1]
                rc=0 if name in self.host_files else 28
                self.rows=screen(self.queued," "*60+"RUNNING")
                self.rows[1]=(f"Ready({rc:05d});" if rc else "Ready;").ljust(80)
        if text.startswith("Transfer("):
            assert self.aid_wait, "Transfer must block until completion"
            assert not self.transfer_restoring, "Must wait for CMS command field restoration"
            name=re.search(r"HostFile=(ZM[0-9A-F]{6}) EXEC A",text)[1]
            path=Path(re.search(r"LocalFile=([^,)]+)",text)[1])
            if "Direction=send" in text:
                assert name not in self.host_files, "Must never replace host source"
                assert "Exist=keep" in text
                self.host_files[name]=path.read_text()
            else:
                data=self.host_files[name]
                path.write_text("bad source" if self.corrupt_source else
                                "\n".join(line.ljust(80) for line in data.splitlines())+"\n")
            self.transfer_count+=1
            self.transfer_restoring=2
            self.rows=screen("", "")
        if text=="Wait(1,Output)" and self.transfer_restoring:
            self.transfer_restoring-=1
            if not self.transfer_restoring:
                self.rows=screen(f"Ready; transfer {self.transfer_count}", " "*60+"RUNNING")
        result=super().exec_command(action)
        if text=="Snap(Status)":
            result.data=[b"U F U C(127.0.0.1) I 2 24 80 22 0 0x0 -"]
        return result


class CommandTests(unittest.TestCase):
    def session(self, **kwargs):
        fake=CommandEmulator(**kwargs)
        s=Session(factory=lambda:fake,allow_commands=True)
        s.connect("0200@")
        return s,fake

    def test_prepare_creates_only_absent_file_and_roundtrip_verifies(self):
        s,fake=self.session()
        result=s.runner.prepare(create=True)
        self.assertTrue(result["ok"],result)
        self.assertTrue(result["source_verified"])
        self.assertTrue(result["created"])
        self.assertFalse(result["existing_files_replaced"])
        self.assertEqual(len(fake.host_files),1)
        self.assertFalse(fake.aid_wait)

    def test_disconnect_invalidates_runner_verification(self):
        s,fake=self.session()
        s.runner.name="ZMABCDEF"
        s.runner.verified=True
        s.runner.completed_token="0123456789ABCDEF"
        self.assertTrue(s.disconnect()["ok"])
        self.assertFalse(s.runner.verified)
        self.assertIsNone(s.runner.completed_token)
        self.assertFalse(s.runner.run("QUERY CMSLEVEL")["ok"])

    def test_partial_state_echo_cannot_select_older_ready_above_it(self):
        class PartialStateEmulator(CommandEmulator):
            phase=0
            def exec_command(self, action):
                text=action.decode()
                if text=='Snap(Save)' and self.phase:
                    self.phase+=1
                    self.rows=screen('Ready; old prompt', ' '*60+'RUNNING')
                    self.rows[2]='STATE ABSENT EXEC A'.ljust(80)
                    if self.phase>=3:self.rows[4]='Ready(00028);'.ljust(80)
                result=super().exec_command(action)
                if text=='Enter' and self.queued=='STATE ABSENT EXEC A':self.phase=1
                return result
        fake=PartialStateEmulator()
        s=Session(factory=lambda:fake,allow_commands=True)
        s.connect('0200@')
        result=s.runner._simple('STATE ABSENT EXEC A',time.monotonic()+3)
        self.assertEqual(result['rc'],28)
        self.assertGreaterEqual(len(result['snapshots']),2)

    def test_visible_matching_state_echo_is_refused_before_input(self):
        from cms_capture import CaptureError
        for old_rc in (0, 28):
            with self.subTest(old_rc=old_rc):
                s, fake = self.session()
                command = 'STATE ZV1234AB EXEC A1'
                fake.rows[0] = command.ljust(80)
                fake.rows[1] = f'Ready({old_rc:05d});'.ljust(80)
                s.runner._input = Mock()
                with self.assertRaisesRegex(CaptureError, 'Prior matching STATE echo'):
                    s.runner._simple(command, time.monotonic() + 1)
                s.runner._input.assert_not_called()
                self.assertFalse(any(call == 'Clear' for call in fake.calls))

    def test_prepare_corrupt_roundtrip_never_executes(self):
        s,fake=self.session()
        fake.corrupt_source=True
        result=s.runner.prepare(create=True)
        self.assertFalse(result["ok"])
        self.assertFalse(any('String("EXEC ' in call for call in fake.calls))

    def test_prepare_reuses_verified_source_without_send(self):
        from cms_commands import SOURCE
        s,fake=self.session()
        s.runner.name="ZMABCDEF"
        fake.host_files["ZMABCDEF"]=SOURCE.read_text()
        result=s.runner.prepare()
        self.assertTrue(result["ok"],result)
        self.assertFalse(result["created"])
        self.assertFalse(any("Direction=send" in call for call in fake.calls))

    def test_complete_output_beyond_one_screen_and_actual_nonzero_rc(self):
        records=[("RECORD %03d  "%n).encode("cp037") for n in range(30)]
        s,fake=self.session(records=records,rc=28)
        s.runner.name="ZMABCDEF"
        s.runner.verified=True
        result=s.runner.run("STATE ABSENT EXEC A")
        self.assertTrue(result["ok"],result)
        self.assertTrue(result["cms_command_complete"])
        self.assertEqual(result["cms_rc"],28)
        self.assertEqual(len(result["records"]),30)
        self.assertEqual(result["records"][-1],"RECORD 029  ")
        self.assertFalse(s.send("Enter")["ok"])

    def test_arbitrary_cms_command_uses_correlated_capture_and_hex_input(self):
        from cms_capture import any_cms_command
        s, fake = self.session(records=[b"OUTPUT"])
        s.runner.policy = any_cms_command
        s.runner.name = "ZMABCDEF"
        s.runner.verified = True
        command = 'GlobalV Select TEST Set "MiXeD Value"'
        result = s.runner.run(command)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["cms_command_complete"])
        self.assertEqual(result["command"], "<submitted; input omitted from diagnostics>")
        self.assertNotIn(command, str(result))
        self.assertTrue(any(call.startswith("HexString(") for call in fake.calls))
        self.assertEqual(fake.queued, "ZA1 " + result["request_id"] + " 3")

    def test_old_ready_does_not_verify_wrapper_return(self):
        s,fake=self.session(final_ready=False)
        s.runner.name="ZMABCDEF"
        s.runner.verified=True
        result=s.runner.run("QUERY DISK",timeout=1)
        self.assertFalse(result["ok"])
        self.assertFalse(result["output_complete"])
        self.assertFalse(result["cms_command_complete"])
        self.assertTrue(result["snapshots"])
        self.assertEqual(list(s.completed_capture_tokens), [])

    def test_older_completed_frames_do_not_block_later_short_commands(self):
        s, fake = self.session(records=[])
        s.runner.name = 'ZMABCDEF'
        s.runner.verified = True
        first = s.runner.run('STATE FIRST EXEC A1')
        second = s.runner.run('STATE SECOND EXEC A1')
        self.assertTrue(first['ok'], first)
        self.assertTrue(second['ok'], second)
        # The real CMS console can retain an older DONE frame as well as the
        # latest completed response. A third request must not reject that page.
        fake.rows[4] = ('ZM1 ' + first['request_id'] + ' Z 1 DONE').ljust(80)
        third = s.runner.run('STATE THIRD EXEC A1')
        self.assertTrue(third['ok'], third)
        self.assertEqual(list(s.completed_capture_tokens),
                         [first['request_id'], second['request_id'], third['request_id']])

    def test_unknown_frame_still_refuses_input_despite_completed_history(self):
        s, fake = self.session(records=[])
        s.runner.name = 'ZMABCDEF'
        s.runner.verified = True
        self.assertTrue(s.runner.run('QUERY DISK')['ok'])
        fake.rows[4] = 'ZM1 0000000000000000 B 0 0 0 0 1'.ljust(80)
        before = len([call for call in fake.calls if call.startswith('String(')])
        result = s.runner.run('QUERY DISK')
        self.assertFalse(result['ok'])
        self.assertIn('Unresolved runner output', result['message'])
        self.assertEqual(before, len([call for call in fake.calls if call.startswith('String(')]))

    def test_completion_history_is_bounded_and_disconnect_scoped(self):
        s, fake = self.session()
        tokens = [f'{number:016X}' for number in range(129)]
        s.completed_capture_tokens.extend(tokens)
        self.assertEqual(len(s.completed_capture_tokens), 128)
        self.assertNotIn(tokens[0], s.completed_capture_tokens)
        s.disconnect()
        self.assertEqual(list(s.completed_capture_tokens), [])

    def test_encoded_credentials_are_redacted_from_screens_and_records(self):
        s,fake=self.session(records=["TESTUSER".encode("cp037")])
        s.secrets.add("TESTUSER")
        s.runner.name="ZMABCDEF"
        s.runner.verified=True
        result=s.runner.run("QUERY DISK")
        self.assertTrue(result["ok"],result)
        self.assertNotIn("TESTUSER",json.dumps(result))
        self.assertNotIn("TESTUSER".encode("cp037").hex().upper(),json.dumps(result))

    def test_disabled_and_invalid_commands_do_not_send_input(self):
        s=Session()
        self.assertFalse(s.runner.run("QUERY DISK")["ok"])
        self.assertFalse(s.runner.prepare(create=True)["ok"])
        s,fake=self.session()
        initial=list(fake.calls)
        self.assertFalse(s.runner.run("ERASE FILE EXEC A")["ok"])
        self.assertEqual(fake.calls,initial)


if __name__=="__main__":
    unittest.main()

"""Fixed compiler observations fail closed and never run an EXEC or transfer."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_cms_commands import CommandEmulator
from test_cms_mcp import screen
from validate_cms_compiler import QUERIES, observe, validate, release_startup_hold
from cms_capture import readonly_command
from cms_mcp import Session


class CompilerObservationTests(unittest.TestCase):
    def test_all_queries_are_existing_readonly_commands_with_literal_file_ids(self):
        self.assertEqual(len(QUERIES), 13)
        for command in QUERIES.values():
            self.assertEqual(readonly_command(command), command)
            self.assertFalse(any(c in command for c in '*%#'))

    def test_disabled_unknown_and_invalid_timeout_never_touch_terminal(self):
        session = Mock(allow_commands=False)
        for query, timeout in [('disks', 20), ('EXEC GCCE', 20), ('disks', True), ('disks', 31)]:
            result = observe(session, query, timeout)
            self.assertFalse(result['ok'])
        session.allow_commands = True
        self.assertFalse(observe(session, 'STATE OTHER EXEC A')['ok'])
        self.assertFalse(observe(session, [])['ok'])
        self.assertFalse(observe(session, 'disks', True)['ok'])
        session._run.assert_not_called()

    def test_actual_fixed_state_echo_and_ready_rc_without_helper_execution(self):
        fake = CommandEmulator()
        session = Session(factory=lambda: fake, allow_commands=True)
        session.connect('0200@')
        result = observe(session, 'wrapper_F')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['terminal_ready_rc'], 28)
        self.assertTrue(result['screen_observation_complete'])
        for key in ('native_output_integrity_verified', 'helper_executed',
                    'compiler_executed', 'host_file_operations_performed', 'replacement_safe', 'source_verified'):
            self.assertIs(result[key], False)
        self.assertFalse(any('String("EXEC ' in action or 'Transfer(' in action for action in fake.calls))
        self.assertTrue(session.disconnect()['terminated'])

    def test_paged_state_captures_more_before_clear_and_fresh_ready(self):
        class Paged(CommandEmulator):
            def exec_command(self, action):
                result = super().exec_command(action)
                if action == b'Enter':
                    self.rows = screen(self.queued, ' ' * 60 + 'MORE...')
                elif action == b'Clear':
                    self.rows = screen('DMSSTT002E File not found', ' ' * 60 + 'RUNNING')
                    self.rows[2] = 'Ready(00028);'.ljust(80)
                return result
        fake = Paged()
        session = Session(factory=lambda: fake, allow_commands=True)
        session.connect('0200@')
        result = observe(session, 'wrapper_F')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['terminal_ready_rc'], 28)
        self.assertEqual(result['snapshots'][0]['state'], 'more')
        self.assertEqual(fake.calls.count('Clear'), 1)
        session.disconnect()

    def test_missing_new_ready_fails_and_terminates_without_retry(self):
        fake = CommandEmulator()
        session = Session(factory=lambda: fake, allow_commands=True)
        session.connect('0200@')
        session.runner._simple = Mock(side_effect=TimeoutError('No correlated Ready'))
        result = observe(session, 'disks')
        self.assertFalse(result['ok'])
        self.assertTrue(result['session_terminated'])
        session.runner._simple.assert_called_once()
        self.assertIsNone(session.em)

    def test_repeated_held_page_receives_one_clear_and_partial_page_has_no_rc(self):
        class RepeatedPage(CommandEmulator):
            cleared = False
            waits = 0
            def exec_command(self, action):
                result = super().exec_command(action)
                if action == b'Enter':
                    self.rows = screen('Ready; old unrelated command', ' ' * 60 + 'MORE...')
                    self.rows[20] = self.queued.ljust(80)
                elif action == b'Clear':
                    self.cleared = True
                elif action == b'Wait(1,Output)' and self.cleared:
                    self.waits += 1
                    if self.waits == 1:
                        self.rows[-1] = (' ' * 60 + 'HOLDING').ljust(80)
                    elif self.waits == 2:
                        self.rows[-1] = (' ' * 60 + 'RUNNING').ljust(80)
                        self.rows[20] = ' ' * 80
                        self.rows[21] = 'OUTPUT STILL ARRIVING'.ljust(80)
                    elif self.waits == 3:
                        self.rows = screen('DMSSTT002E File not found', ' ' * 60 + 'RUNNING')
                        self.rows[1] = 'Ready(00028);'.ljust(80)
                return result
        fake = RepeatedPage()
        session = Session(factory=lambda: fake, allow_commands=True)
        session.connect('0200@')
        result = observe(session, 'wrapper_F')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['terminal_ready_rc'], 28)
        self.assertEqual(fake.calls.count('Clear'), 1)
        self.assertEqual(fake.waits, 3)
        session.disconnect()

    def test_live_gate_evidence_exclusive_and_session_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp).resolve()
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            args = argparse.Namespace(live=False, credential_file=repo / 'not-read', output=repo / 'evidence.json')
            session = Mock()
            with self.assertRaises(ValueError):
                validate(args, session)
            session.connect.assert_not_called()
            args.live = True
            session.connect.return_value = {'ok': False, 'message': 'Synthetic failure'}
            session.disconnect.return_value = {'ok': True, 'connected': False}
            result = validate(args, session)
            self.assertFalse(result['observation_complete'])
            self.assertEqual(args.output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(args.output.read_bytes()), result)
            session.disconnect.assert_called_once()
            session.runner._simple.assert_not_called()
            session.reset_mock()
            with self.assertRaises(FileExistsError):
                validate(args, session)
            session.connect.assert_not_called()
            symlink = repo / 'symlink.json'
            symlink.symlink_to(args.output)
            args.output = symlink
            with self.assertRaises((ValueError, FileExistsError)):
                validate(args, session)
            session.connect.assert_not_called()

    def test_driver_requires_explicit_flag_before_startup_release_and_queries(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp).resolve()
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            for authorized, recovered in ((False, False), (True, False), (True, True)):
                session = Mock()
                for name in ('connect', 'screen', 'login', 'disconnect'):
                    getattr(session, name).return_value = {'ok': True}
                startup = {'ok': False, 'outcome': 'startup_page_hold_observed'}
                session.startup.return_value = startup
                args = argparse.Namespace(live=True, credential_file=repo / 'not-read',
                    output=repo / (str(authorized) + str(recovered) + '.json'), advance_startup_more=authorized)
                with patch('validate_cms_compiler.release_startup_hold', return_value={'ok': recovered}) as release, \
                        patch('validate_cms_compiler.observe', return_value={'ok': True, 'terminal_ready_rc': 28}) as query:
                    result = validate(args, session)
                    self.assertEqual(result['observation_complete'], authorized and recovered)
                    if authorized:
                        release.assert_called_once_with(session, startup, authorized=True)
                    else:
                        release.assert_not_called()
                    if authorized and recovered:
                        self.assertEqual([call.args[1] for call in query.call_args_list], list(QUERIES))
                    else:
                        query.assert_not_called()
                    session.disconnect.assert_called_once()


class StartupHoldReleaseTests(unittest.TestCase):
    def session(self, next_state='ready'):
        class Held(CommandEmulator):
            cleared = False
            def exec_command(self, action):
                result = super().exec_command(action)
                if action == b'Clear':
                    self.cleared = True
                if action == b'Wait(1,Output)' and self.cleared:
                    if next_state == 'blank':
                        self.rows = screen('', ' ' * 60 + 'RUNNING')
                    else:
                        self.rows = screen('Ready;' if next_state == 'ready' else 'Another output page',
                            ' ' * 60 + ('RUNNING' if next_state == 'ready' else 'MORE...'))
                return result
        fake = Held()
        fake.rows = screen('z/VM Version 6 Release 3.0', ' ' * 60 + 'MORE...')
        fake.rows[5] = 'RECONNECTED AT 00:00:00'.ljust(80)
        fake.rows[6] = 'BEGIN'.ljust(80)
        session = Session(factory=lambda: fake, allow_commands=True)
        session.connect('0200@')
        startup = {'ok': False, 'outcome': 'startup_page_hold_observed',
            'actions': ['BEGIN', 'Enter'], 'screen': session.snapshot()}
        self.addCleanup(session.disconnect)
        return session, fake, startup

    def test_default_denies_release_and_exact_authority_is_required(self):
        session, fake, startup = self.session()
        self.assertFalse(release_startup_hold(session, startup)['ok'])
        self.assertNotIn('Clear', fake.calls)
        startup['actions'] = []
        self.assertFalse(release_startup_hold(session, startup, authorized=True)['ok'])
        self.assertNotIn('Clear', fake.calls)

    def test_one_clear_then_passive_wait_handles_unchanged_page(self):
        session, fake, startup = self.session()
        result = release_startup_hold(session, startup, authorized=True)
        self.assertTrue(result['ok'], result)
        self.assertEqual(fake.calls.count('Clear'), 1)
        self.assertNotIn('Enter', fake.calls)
        self.assertFalse(any(action.startswith('String') for action in fake.calls))
        self.assertIsNone(result['cms_command_complete'])

    def test_second_page_stops_without_second_clear_or_other_input(self):
        session, fake, startup = self.session('more')
        result = release_startup_hold(session, startup, authorized=True)
        self.assertFalse(result['ok'])
        self.assertEqual(result['clear_count'], 1)
        self.assertEqual(fake.calls.count('Clear'), 1)
        self.assertNotIn('Enter', fake.calls)

    def test_blank_running_after_clear_never_becomes_ready_or_additional_input(self):
        session, fake, startup = self.session('blank')
        result = release_startup_hold(session, startup, timeout=1, authorized=True)
        self.assertFalse(result['ok'])
        self.assertEqual(result['outcome'], 'ready_not_observed_after_single_clear')
        self.assertEqual(result['screen']['state'], 'unknown')
        self.assertEqual(fake.calls.count('Clear'), 1)
        self.assertNotIn('Enter', fake.calls)
        self.assertFalse(any(action.startswith('String') for action in fake.calls))

    def test_changed_page_and_nonempty_input_are_refused_before_clear(self):
        for changed in ('page', 'input'):
            session, fake, startup = self.session()
            if changed == 'page':
                fake.rows[4] = 'UNRELATED PAGE'.ljust(80)
            else:
                fake.rows[22] = 'EXISTING INPUT'.ljust(80)
            result = release_startup_hold(session, startup, authorized=True)
            self.assertFalse(result['ok'])
            self.assertIs(result['clear_sent'], False)
            self.assertNotIn('Clear', fake.calls)


if __name__ == '__main__':
    unittest.main()

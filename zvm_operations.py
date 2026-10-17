"""Local replacement/build review manifests. No terminal or execution interface."""
from __future__ import annotations

import json
import re
import secrets
import shutil

from zvm_download import MAX_BYTES, file_id, git_root_for
from zvm_edit import MAX_TEXT, canonical, encode_edit, read_file, sha


def literal_file(value):
    if (not isinstance(value, str) or any(ord(c) < 32 or ord(c) > 126 for c in value)
            or len(value.split()) != 3):
        raise ValueError('Use a literal CMS filename, filetype and numeric filemode')
    identity = file_id(*value.split())
    if len(identity[2]) != 2:
        raise ValueError('Operation file IDs require numeric filemodes')
    return ' '.join(identity)


def exact_hash(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('An exact lowercase SHA-256 is required')
    return value


def review_source(edits, edit_id, plan_id, plan_hash):
    edits.identifier(edit_id, 'edit')
    edits.identifier(plan_id, 'plan')
    exact_hash(plan_hash)
    root, worktree = edits.context()
    edit = root / 'edits' / edit_id
    directory = edit / plan_id
    git_root_for(directory)
    payload = read_file(directory / 'plan.json', 2 * MAX_BYTES)
    if sha(payload) != plan_hash:
        raise ValueError('Review plan hash does not match')
    plan = json.loads(payload)
    if (plan.get('schema') != 'zvm-cms-upload-review-v1' or plan.get('edit_id') != edit_id
            or plan.get('changed') is not True or plan.get('upload_authorized') is not False
            or plan.get('upload_implemented') is not False or plan.get('host_operations_performed') is not False):
        raise ValueError('Expected a changed, unauthorized local review plan')
    definition_bytes = read_file(edit / 'edit.json', MAX_BYTES)
    definition = json.loads(definition_bytes)
    if (definition.get('schema') != 'zvm-cms-local-edit-v1'
            or sha(definition_bytes) != plan['edit_definition_sha256']
            or definition['snapshot'] != plan['source_snapshot']):
        raise ValueError('Edit definition differs from the reviewed plan')
    manifest_bytes, original, manifest, _ = edits.snapshot(root, definition['snapshot'])
    cms = manifest['cms']
    working_name = 'working/' + cms['filename'] + '.' + cms['filetype']
    if (definition['cms'] != cms or definition['editable_file'] != working_name
            or definition['source_manifest_sha256'] != sha(manifest_bytes)
            or plan['source_manifest_sha256'] != sha(manifest_bytes)
            or definition['base_sha256'] != sha(original)
            or definition['base_record_lengths'] != manifest['record_lengths']
            or read_file(edit / 'baseline.ebcdic', MAX_BYTES) != original
            or read_file(edit / 'baseline-manifest.json', 2 * MAX_BYTES) != manifest_bytes
            or plan['expected_original'] != {'cms': cms, 'sha256': sha(original),
                                             'record_lengths': manifest['record_lengths']}):
        raise ValueError('Original snapshot or pinned baseline differs from review')
    git_root_for(edit / 'working')
    working = read_file(edit / working_name, MAX_TEXT)
    records = encode_edit(working, cms)
    candidate = read_file(directory / 'candidate.ebcdic', MAX_BYTES)
    proposed = plan['proposed']
    if (sha(working) != plan['edited_text_sha256'] or b''.join(records) != candidate
            or candidate == original or sha(candidate) != proposed['sha256']
            or proposed['record_lengths'] != list(map(len, records))
            or proposed['record_count'] != len(records) or proposed['byte_count'] != len(candidate)
            or proposed['records_sha256'] != list(map(sha, records))
            or any(proposed[key] != cms[key] for key in ('filename', 'filetype', 'filemode', 'recfm'))
            or proposed['lrecl'] != (cms['lrecl'] if cms['recfm'] == 'F' else max(map(len, records), default=0))
            or sha(read_file(directory / 'source.diff', 2 * MAX_TEXT)) != plan['diff_sha256']):
        raise ValueError('Working source, native candidate or diff differs from review')
    edits.reject_credentials(payload.decode(), working.decode(), candidate.decode('cp037'))
    return root, worktree, edit, plan


def review_recipe(recipe, target, snapshot, base_hash):
    if not isinstance(recipe, dict) or set(recipe) - {'steps', 'writer_exclusion', 'rollback', 'input_hashes'}:
        raise ValueError('Recipe keys are steps, writer_exclusion, rollback and input_hashes')
    steps = recipe.get('steps', [])
    if not isinstance(steps, list) or len(steps) > 16:
        raise ValueError('A review recipe supports at most sixteen exact steps')
    hashes = recipe.get('input_hashes', {})
    if not isinstance(hashes, dict):
        raise ValueError('input_hashes must map exact CMS file IDs to SHA-256 values')
    normalized_hashes = {}
    for file, digest in hashes.items():
        normalized = literal_file(file)
        if normalized in normalized_hashes or normalized == target:
            raise ValueError('Duplicate or source-overriding input hash')
        normalized_hashes[normalized] = exact_hash(digest)
    normalized_steps = []
    output_owners = {}
    names = set()
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or set(step) != {'name', 'command', 'inputs', 'outputs', 'expected_rc', 'expect'}:
            raise ValueError('Each step needs name, command tokens, inputs, outputs, expected_rc and expect')
        name = step['name']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}', name) or name in names:
            raise ValueError('Step names must be distinct simple identifiers')
        names.add(name)
        command = step['command']
        if (not isinstance(command, list) or not 1 <= len(command) <= 32
                or any(not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9@$_.:+()=-]{1,64}', token) for token in command)):
            raise ValueError('Commands must be explicit printable tokens without separators, quotes or wildcards')
        if len(' '.join(command)) > 139:
            raise ValueError('Reviewed command exceeds the known 139-character CMS input field')
        if command[0].upper() in {'CP', 'IPL', 'LOGON', 'LOGOFF', 'ERASE', 'FORMAT', 'ACCESS', 'RELEASE', 'LINK', 'EXECIO', 'PIPE'}:
            raise ValueError('Administrative, destructive and generic terminal commands are not review recipes')
        if type(step['expected_rc']) is not int or not -(2 ** 31) <= step['expected_rc'] < 2 ** 31:
            raise ValueError('Expected RC must be a signed 32-bit integer')
        inputs, outputs, markers = step['inputs'], step['outputs'], step['expect']
        if not isinstance(inputs, list) or len(inputs) > 64 or not isinstance(outputs, list) or len(outputs) > 64:
            raise ValueError('Each step supports at most 64 input and output files')
        inputs = [literal_file(file) for file in inputs]
        if len(inputs) != len(set(inputs)):
            raise ValueError('Duplicate step input file')
        normalized_outputs = []
        for output in outputs:
            if not isinstance(output, dict) or set(output) != {'file', 'policy'} or output['policy'] != 'create_only':
                raise ValueError('Every output needs an exact file and create_only policy')
            file = literal_file(output['file'])
            if not file.endswith(' A1') or file == target or file in inputs or file in output_owners or file in normalized_hashes:
                raise ValueError('Output collision or protected output disk')
            if re.fullmatch(r'Z[MV][0-9A-F]{6}', file.split()[0]):
                raise ValueError('Helper and retained scratch namespaces are protected')
            output_owners[file] = index
            normalized_outputs.append({'file': file, 'policy': 'create_only'})
        if (not isinstance(markers, list) or len(markers) > 32
                or any(not isinstance(value, str) or not 1 <= len(value) <= 160
                       or any(ord(c) < 32 or ord(c) > 126 for c in value) for value in markers)):
            raise ValueError('Expected markers must be bounded printable ASCII strings')
        normalized_steps.append({**step, 'inputs': inputs, 'outputs': normalized_outputs})
    missing = [] if steps else ['build_test_recipe']
    if steps and not any(target in step['inputs'] for step in normalized_steps):
        missing.append('source_not_consumed_by_recipe')
    available = {target, *normalized_hashes}
    for index, step in enumerate(normalized_steps):
        for file in step['inputs']:
            if file in output_owners and output_owners[file] >= index:
                raise ValueError('Step consumes an output before its producer completes')
            if file not in available:
                missing.append('input_hash:' + file)
        if not step['expect']:
            missing.append('output_expectations:' + step['name'])
        available.update(file['file'] for file in step['outputs'])
    writer = recipe.get('writer_exclusion')
    if writer is None:
        missing.append('operator_writer_exclusion_procedure')
    elif (not isinstance(writer, dict) or set(writer) != {'owner', 'procedure', 'evidence_ref', 'disk'}
          or writer['disk'] != target.split()[2]
          or any(not isinstance(writer[key], str) or not writer[key].strip() or len(writer[key]) > 2048
                 or any(ord(c) < 32 or ord(c) > 126 for c in writer[key]) for key in writer)):
        raise ValueError('Writer exclusion needs bounded owner/procedure/evidence_ref and matching disk')
    rollback = recipe.get('rollback')
    if rollback is None:
        missing.append('rollback_procedure')
    elif (not isinstance(rollback, dict) or set(rollback) != {'snapshot', 'sha256', 'target', 'procedure'}
          or rollback['snapshot'] != snapshot or rollback['sha256'] != base_hash
          or literal_file(rollback['target']) != target
          or not isinstance(rollback['procedure'], str) or not rollback['procedure'].strip()
          or len(rollback['procedure']) > 2048
          or any(ord(c) < 32 or ord(c) > 126 for c in rollback['procedure'])):
        raise ValueError('Rollback must pin the original snapshot/hash, exact target and procedure')
    return {'steps': normalized_steps, 'input_hashes': normalized_hashes,
            'writer_exclusion': writer, 'rollback': rollback}, sorted(set(missing))


def operation_receipt(source, edit_id, plan_id, plan_sha256, recipe, worktree):
    """Construct the review consistently for creation and later local revalidation."""
    cms = source['expected_original']['cms']
    target = literal_file(' '.join(cms[key] for key in ('filename', 'filetype', 'filemode')))
    normalized, missing = review_recipe(recipe, target, source['source_snapshot'], source['expected_original']['sha256'])
    blockers = ['execution_not_implemented', 'exact_target_authorization_required',
                'writer_exclusion_not_verified', 'fresh_host_baseline_required',
                'rollback_not_qualified', 'command_semantics_not_verified',
                'output_inventory_not_verified']
    if cms['filemode'] != 'A1' or re.fullmatch(r'Z[MV][0-9A-F]{6}', cms['filename']):
        blockers.append('protected_source_target')
    return {'schema': 'zvm-cms-operation-review-v1', 'edit_id': edit_id,
        'source_plan_id': plan_id, 'source_plan_sha256': plan_sha256,
        'source_snapshot': source['source_snapshot'], 'target': target,
        'expected_original': source['expected_original'], 'candidate': source['proposed'],
        'recipe': normalized, 'missing_inputs': missing, 'blocking_conditions': blockers,
        'review_complete': not missing, 'execution_authorized': False,
        'execution_implemented': False, 'host_operations_performed': False,
        'replacement_safe': False, 'writer_exclusion_verified': False,
        'input_hashes_host_verified': False, 'git_worktree': str(worktree)}


class OperationPlans:
    def __init__(self, session):
        self.session = session

    def plan(self, edit_id, plan_id, plan_sha256, recipe):
        with self.session.lock:
            directory = None
            try:
                root, worktree, edit, source = review_source(self.session.edits, edit_id, plan_id, plan_sha256)
                if len(canonical(recipe)) > 65536:
                    raise ValueError('Recipe exceeds 64 KiB')
                self.session.edits.reject_credentials(canonical(recipe).decode())
                receipt = operation_receipt(source, edit_id, plan_id, plan_sha256, recipe, worktree)
                operation_id = 'operation-' + secrets.token_hex(12)
                destination = edit / operation_id
                git_root_for(destination)
                destination.mkdir(mode=0o700)
                directory = destination
                payload = canonical(receipt)
                self.session.edits.write(directory, 'operation.json', payload)
                if read_file(directory / 'operation.json', 2 * MAX_BYTES) != payload:
                    raise ValueError('Operation manifest readback failed')
                return {'ok': True, 'operation_id': operation_id, 'operation_file': str(directory / 'operation.json'),
                        'operation_sha256': sha(payload), 'target': receipt['target'],
                        'candidate_sha256': source['proposed']['sha256'], 'review_complete': receipt['review_complete'],
                        'missing_inputs': receipt['missing_inputs'], 'blocking_conditions': receipt['blocking_conditions'],
                        'execution_authorized': False, 'execution_implemented': False,
                        'host_operations_performed': False, 'replacement_safe': False}
            except Exception as exc:
                if directory is not None:
                    shutil.rmtree(directory)
                return {'ok': False, 'message': self.session.redact(str(exc)),
                        'execution_authorized': False, 'execution_implemented': False,
                        'host_operations_performed': False, 'replacement_safe': False}

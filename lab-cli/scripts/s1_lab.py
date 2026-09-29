"""Standalone S1 Lab: direct Python Wi-Fi client with automatic discovery.

No DJI installation, vendor DLL, Python packages or ADB prerequisite.
The CLI deliberately exposes only Python Lab upload/run/exit and readback.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid
from xml.sax.saxutils import escape

from s1_discovery import private_host
from s1_native import LabClient, SCRATCH_VERSION, CONTROL, STATE, ERROR, OUTPUT
JSON_OUTPUT = False
COLOR = False
STDOUT_BROKEN = False


def console_line(text='', color=None):
    codes = {'blue': '36', 'green': '32', 'yellow': '33', 'red': '31', 'dim': '90'}
    if COLOR and color:
        text = '\x1b[' + codes[color] + 'm' + text + '\x1b[0m'
    print(text, file=sys.stderr, flush=True)


def write_result(text):
    """Flush each result immediately; a closed pipe still permits robot cleanup."""
    global STDOUT_BROKEN
    if STDOUT_BROKEN:
        return
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except BrokenPipeError:
        STDOUT_BROKEN = True
        raise


def value_of(row):
    payload = row['payload']
    return payload.get('value', payload.get('Value')) if isinstance(payload, dict) else None


def script_source(source, guid):
    """Keep the Lab start() convention and add an observable completion marker."""
    source = source.replace('\r\n', '\n').strip()
    ast.parse(source, feature_version=(3, 6))
    if '_s1_lab_' in source:
        raise ValueError('Names beginning _s1_lab_ are reserved for execution receipts')
    # Firmware uses text matching to inject stop checkpoints. Reject ambiguous
    # matches (including one-line loops) rather than upload altered Python.
    for line in source.splitlines():
        if re.match(r'^[^\w]*#+', line):
            continue
        if 'while' in line or ('for ' in line and ' in ' in line and ':' in line):
            if not re.match(r'^ *(?:while .+|for .+ in .+): *(?:#.*)?$', line):
                raise ValueError('Unsupported S1 loop checkpoint syntax: ' + line.strip())
    return source + '''

_s1_lab_original_start = start
def start():
    print('S1LAB_STARTED_%s')
    try:
        _s1_lab_original_start()
    except Exception as _s1_lab_error:
        print('S1LAB_FAILED_%s ' + str(_s1_lab_error))
        return
    print('S1LAB_DONE_%s')
''' % (guid, guid, guid)


def emit(kind, **fields):
    if JSON_OUTPUT:
        write_result(json.dumps(dict(event=kind, **fields), ensure_ascii=True) + '\n')
        return
    if kind == 'output':
        content = fields['value'].get('infoContent', '')
        content = re.sub(r'^\[[^\]\r\n]+\]: ?', '', content, count=1)
        if content.startswith(('S1LAB_STARTED_', 'S1LAB_DONE_', 'S1LAB_FAILED_')):
            return
        write_result(content + ('' if content.endswith('\n') else '\n'))
    elif kind == 'status':
        state = fields['state']
        label = {0: 'Ready', 1: 'Uploading', 2: 'Program running', 3: 'Skill running',
                 4: 'Autonomous program running', 5: 'Program error'}.get(state.get('state'), 'Unknown')
        write_result('Lab: ' + label + '\nVersion: ' + str(fields['lab_version'].get('value', '?')) + '\n')
    elif kind == 'receipt':
        write_result(json.dumps(fields['receipt'], indent=2, ensure_ascii=True) + '\n')
    elif kind == 'connecting':
        console_line('  · Connecting to S1…', 'dim')
    elif kind == 'connected':
        console_line('  ✓ Connected' + (' to ' + fields['host'] if fields.get('host') else ''), 'green')
    elif kind == 'uploading':
        console_line('  ↑ Uploading ' + fields['name'], 'blue')
    elif kind == 'uploaded':
        console_line('  ✓ Program uploaded', 'green')
    elif kind == 'starting':
        console_line('  ▶ Running', 'blue')
        console_line('    The stock Lab may recenter the gimbal at start and exit.', 'dim')
    elif kind in ('completed', 'stopped', 'already_idle'):
        console_line('  ✓ ' + {'completed': 'Finished', 'stopped': 'Program stopped', 'already_idle': 'Lab already idle'}[kind], 'green')
    elif kind == 'script_error':
        console_line('  ! ' + fields['value'].get('errorMsg', 'Robot reports a program error'), 'red')
    elif kind in ('error', 'stop_unconfirmed', 'discovery_unavailable'):
        console_line('  ✗ ' + fields['message'], 'red')


def project(source: str, title: str, guid: str | None = None):
    """Plain DSP accepted by the original firmware parser (no AES for FTP)."""
    source = source.replace('\r\n', '\n').strip()
    ast.parse(source, feature_version=(3, 6))
    # The stock DSP parser unescapes these sequences even in Python literals.
    # Refuse silently changed programs; do not work around Lab stop checkpoints.
    if source.replace('\\n', '\n').replace('\\"', '"') != source:
        raise ValueError('The S1 DSP parser changes escaped newlines/quotes; use chr(10)/chr(34) instead')
    guid = guid or uuid.uuid4().hex
    if not re.fullmatch('[0-9a-f]{32}', guid):
        raise ValueError('Invalid project GUID')
    date = datetime.now().strftime('%Y/%m/%d')
    creator, firmware = 'S1 Lab CLI', '00.00.0000'
    signature = hashlib.md5(('wwxnMmF8' + date + title + creator + firmware + guid + source + 'Python').encode()).hexdigest()[7:23]
    attrs = dict(creation_date=date, title=title, creator=creator,
                 firmware_version_dependency=firmware, guid=guid, sign=signature, code_type='python')
    xml = '<dji><attribute>' + ''.join('<%s>%s</%s>' % (k, escape(v), k) for k, v in attrs.items())
    xml += '</attribute><code><python_code>' + escape(source) + '</python_code><scratch_description></scratch_description></code></dji>'
    return dict(guid=guid, sign=signature, xml=xml)


def idle(client):
    state = client.request(1, STATE)
    if not isinstance(state, dict) or state.get('state') != 0:
        raise RuntimeError('Lab is busy; leaving the existing program untouched: %r' % state)
    return state


def prepare_upload(source_path, title):
    """Validate and package the supplied file before opening a robot connection."""
    source = source_path.read_text(encoding='utf-8-sig')
    guid = uuid.uuid4().hex
    packed = project(script_source(source, guid), title, guid)
    receipt = dict(schema=1, guid=guid, sign=packed['sign'],
                   source=str(source_path.resolve()), source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                   title=title, uploaded=False)
    # Preserve the bytes previously produced by the host's UTF-8 text file.
    data = packed['xml'].replace('\n', os.linesep).encode('utf-8')
    return data, receipt


def upload(client, data, receipt):
    emit('uploading', name=Path(receipt['source']).name)
    # Returns only after FTP, creation ACK and fresh Idle have succeeded.
    client.upload(data)
    emit('uploaded', guid=receipt['guid'])
    return dict(receipt, host=client.host, uploaded=True)


def read_receipt(path, host):
    # PowerShell 5 redirection writes UTF-16; newer shells normally use UTF-8.
    raw = path.read_bytes()
    receipt = json.loads(raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'))
    receipt_host = private_host(receipt.get('host', ''))
    if (receipt.get('schema') != 1 or (host is not None and receipt_host != host) or receipt.get('uploaded') is not True
            or not re.fullmatch('[0-9a-f]{32}', receipt.get('guid', ''))
            or not re.fullmatch('[0-9a-f]{16}', receipt.get('sign', ''))):
        raise ValueError('A successful upload receipt for this robot is required')
    return receipt


def stop(client, receipt):
    state = client.request(1, STATE)
    if isinstance(state, dict) and state.get('state') == 0:
        emit('already_idle')
        return
    if not isinstance(state, dict) or state.get('key') != receipt['guid']:
        raise RuntimeError('Active program does not match this receipt; no stop sent')
    client.request(3, CONTROL, dict(type=5, guid=receipt['guid'], sign=receipt['sign']))
    client.wait(lambda: isinstance(client.values.get(STATE), dict) and client.values[STATE].get('state') == 0, 10)
    emit('stopped', guid=receipt['guid'])


def run(client, receipt, timeout):
    idle(client)
    guid = receipt['guid']
    beginning = len(client.history)
    finished = False
    try:
        emit('starting', guid=guid, note='The stock Lab framework recenters the gimbal at start and exit')
        client.request(3, CONTROL, dict(type=2, guid=guid, sign=receipt['sign']))
        deadline = time.monotonic() + timeout
        cursor = beginning
        done = False
        active = False
        state = None
        failure = None
        while time.monotonic() < deadline:
            client.poll()
            if not client.connected:
                raise RuntimeError('Robot connection lost; program completion is unconfirmed')
            for row in client.history[cursor:]:
                value = value_of(row)
                if row['operation'] != 4 or not isinstance(value, dict):
                    continue
                if row['key'] == hex(OUTPUT):
                    content = value.get('infoContent', '')
                    if 'S1LAB_FAILED_' + guid in content:
                        failure = 'Program failed: ' + content.split('S1LAB_FAILED_' + guid, 1)[1].strip()
                    done |= 'S1LAB_DONE_' + guid in content
                elif row['key'] == hex(ERROR) and value.get('key') == guid:
                    failure = 'Script error: %r' % value
                elif row['key'] == hex(STATE):
                    state = value
                    active |= value.get('key') == guid and value.get('state') == 2
                    if value.get('state') == 5:
                        failure = failure or 'Robot reported Lab error: %r' % value
            cursor = len(client.history)
            if state and state.get('state') in (0, 5) and failure:
                # Let the stock framework finish cleanup; Exit racing cleanup
                # can leave its stop flag latched and reject the next upload.
                finished = True
                raise RuntimeError(failure)
            if active and state and state.get('state') == 0 and done:
                finished = True
                emit('completed', guid=guid)
                return
            if active and state and state.get('state') == 0 and not done:
                # Output and state may arrive separately; allow bounded draining.
                deadline = min(deadline, time.monotonic() + 2)
            time.sleep(.02)
        raise TimeoutError('No confirmed completion marker and idle state before the deadline')
    finally:
        if not finished and client.connected:
            try:
                stop(client, receipt)
            except Exception as error:
                emit('stop_unconfirmed', message=str(error))


def main():
    parser = argparse.ArgumentParser(prog='s1-lab',
        description='S1 LAB — Upload and run your Python programs from the terminal.')
    parser.add_argument('--host', type=private_host,
                        help='explicit robot IPv4 address (default: automatic S1 discovery)')
    parser.add_argument('--json', action='store_true', help='structured output for scripts')
    parser.add_argument('--connect-timeout', type=float, default=15,
                        help='connection/discovery timeout in seconds (1-60; default: 15)')
    commands = parser.add_subparsers(dest='command', title='commands')
    commands.add_parser('status', help='check connection and Lab state')
    for name in ('upload', 'run'):
        command = commands.add_parser(name, help='upload a Python file' if name == 'upload' else 'upload, run and show live output')
        command.add_argument('file', type=Path, help='Python source file')
        command.add_argument('--title', help='project title (default: file name)')
        if name == 'run':
            command.add_argument('--timeout', type=float, default=60)
    command = commands.add_parser('run-project', help='run a previously uploaded project')
    command.add_argument('receipt', type=Path, help='JSON receipt from: upload file.py > receipt.json')
    command.add_argument('--timeout', type=float, default=60)
    commands.add_parser('stop', help='stop the exact project in a saved receipt').add_argument('receipt', type=Path)
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    global JSON_OUTPUT, COLOR
    JSON_OUTPUT = args.json
    COLOR = sys.stderr.isatty() and 'NO_COLOR' not in os.environ
    if hasattr(args, 'timeout') and not 1 <= args.timeout <= 3600:
        parser.error('timeout must be between 1 and 3600 seconds')
    if not 1 <= args.connect_timeout <= 60:
        parser.error('connect-timeout must be between 1 and 60 seconds')
    perform(args)
    return 0


def perform(args):
    saved = read_receipt(args.receipt, args.host) if args.command in ('stop', 'run-project') else None
    if args.command in ('upload', 'run'):
        data, receipt = prepare_upload(args.file, args.title or args.file.stem)
    host = saved['host'] if saved else args.host
    client = LabClient(emit=emit)
    try:
        emit('connecting')
        client.connect(host, timeout=args.connect_timeout)
        if args.command == 'status':
            emit('status', lab_version=client.request(1, SCRATCH_VERSION), state=client.request(1, STATE))
        elif args.command == 'stop':
            stop(client, saved)
        else:
            if args.command == 'run-project':
                receipt = saved
            else:
                receipt = upload(client, data, receipt)
            if args.command == 'upload':
                emit('receipt', receipt=receipt)
            else:
                run(client, receipt, args.timeout)
    finally:
        client.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    result = 0
    try:
        result = main() or 0
    except BrokenPipeError:
        result = 1
    except (Exception, KeyboardInterrupt) as error:
        emit('error', message=str(error) or 'Interrupted'); result = 1
    except SystemExit as error:
        result = error.code or 0
    if STDOUT_BROKEN:
        # Avoid a second BrokenPipeError during interpreter shutdown.
        sys.stdout = open(os.devnull, 'w')
    raise SystemExit(result)

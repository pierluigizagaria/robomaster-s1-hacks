"""Inspect the user's private firmware reference without distributing its code."""
import ast
import hashlib
from pathlib import Path
import re
import sys
import xml.dom.minidom
from unittest.mock import Mock

path = Path(sys.argv[1])
source = path.read_bytes()
assert hashlib.sha256(source).hexdigest() == 'f939a0f896ab03f4cbab9ecf955758776cbc3bb7db66889363c498d781e91338'
root = Path(__file__).resolve().parents[1]
parser_source = (path.parent.parent / 'lib/dji_scratch_project_parser.py').read_bytes()
assert hashlib.sha256(parser_source).hexdigest() == 'f700d3417c5508c042ce1ebe8c0d4446a8b544a1c27ffbe61263947b5e85dad9'
parser_class = [node for node in ast.parse(parser_source).body
                if isinstance(node, ast.ClassDef) and node.name == 'DSPXMLParser']
parser_namespace = {'xml': xml, 'logger': Mock()}
exec(compile(ast.Module(body=parser_class, type_ignores=[]), 'private-dsp-parser', 'exec'), parser_namespace)
parser = parser_namespace['DSPXMLParser']()

manager_source = (path.parent.parent / 'lib/script_manage.py').read_bytes()
assert hashlib.sha256(manager_source).hexdigest() == '0f470d12c2ff856f98c36decc45a50fc55a9b85d96a1c679ba3b5d335d6d594c'
transforms = [node for node in ast.walk(ast.parse(manager_source))
              if isinstance(node, ast.FunctionDef) and node.name in ('script_add_check_point', 'script_add_indent')]
transform_namespace = {'regex': re}
exec(compile(ast.Module(body=transforms, type_ignores=[]), 'private-lab-transforms', 'exec'), transform_namespace)

def decode_project(code):
    project = '<dji><attribute><code_type>python</code_type></attribute><code><python_code><![CDATA['
    project += code + ']]></python_code></code></dji>'
    assert parser.parseDSPString(project) == 0
    return parser.dsp_dict['python_code']

broken = "def broken():\n    return b'\\n'\n"
compile(broken, 'valid-original', 'exec')
try:
    compile(decode_project(broken), 'dji-decoded', 'exec')
except SyntaxError:
    pass
else:
    raise AssertionError('original parser did not reproduce the reported error')

generated = (root / 'scripts/xt30_battery.py').read_text()
for mode in ('INSTALL', 'STATUS', 'DISABLE', 'UNINSTALL'):
    selected = generated.replace("MODE = 'INSTALL'", "MODE = '%s'" % mode, 1)
    decoded = decode_project(selected)
    assert decoded == selected.strip()
    checkpoints = transform_namespace['script_add_check_point'](None, decoded)
    indented = transform_namespace['script_add_indent'](None, checkpoints)
    complete = source.decode().replace('SCRATCH_PYTHON_CODE', indented)
    ast.parse(complete, feature_version=(3, 6))
    compile(complete, 'private-full-lab-program', 'exec')
print('PASS: original DSP parser reproduces old syntax error; all four fixed modes compile through actual DJI transforms/framework.')
tree = ast.parse(source.replace(b'SCRATCH_PYTHON_CODE', b'    pass'))
names = ('robot_reset', 'robot_exit')
functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
finalizer = [node for node in tree.body if isinstance(node, ast.Try)][-1].finalbody
names_in_finalizer = {node.id for stmt in finalizer for node in ast.walk(stmt) if isinstance(node, ast.Name)}
namespace = {name: Mock() for name in names_in_finalizer}
namespace.update(robot_ctrl=Mock(), gimbal_ctrl=Mock(), chassis_ctrl=Mock(), gun_ctrl=Mock(),
                 mobile_ctrl=Mock(), armor_ctrl=Mock(), media_ctrl=Mock(), multi_comm_ctrl=Mock(), rm_define=Mock())
exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), namespace)
namespace['robot_reset']()  # The original ready() calls this before injected user code.
gimbal = namespace['gimbal_ctrl']
gimbal.recenter.assert_called_once_with(90)
gimbal.recenter.reset_mock()
launcher = ast.parse((root / 'src/lab_launcher.template.py').read_text())
replacement = [node for node in launcher.body if isinstance(node, ast.FunctionDef) and node.name == 'robot_reset']
exec(compile(ast.Module(body=replacement, type_ignores=[]), 'maintenance-reset', 'exec'), namespace)
event = namespace['event']
exec(compile(ast.Module(body=finalizer, type_ignores=[]), str(path), 'exec'), namespace)
gimbal.recenter.assert_not_called()
for name in ('gun_ctrl', 'chassis_ctrl', 'gimbal_ctrl', 'media_ctrl', 'vision_ctrl', 'armor_ctrl'):
    namespace[name].stop.assert_called_once()
for name in ('robot_ctrl', 'gimbal_ctrl', 'chassis_ctrl', 'gun_ctrl', 'mobile_ctrl', 'armor_ctrl', 'media_ctrl', 'multi_comm_ctrl'):
    namespace[name].exit.assert_called_once()
event.stop.assert_called_once()
assert 'event' not in namespace
print('PASS: exact private DJI finalizer preserves all stop/exit/event cleanup; no second recenter task.')

"""Prepare the reviewed files for a robot-side autostart installation."""
import argparse
from pathlib import Path


def payload_files():
    source = Path(__file__).resolve().parent
    sources = {'boot.py': source / 'boot.py', 'manage.py': source / 'manage.py',
               'lab_manage.py': source / 'lab_manage.py',
               'controller_settings.py': source / 'controller_settings.py',
               's1_battery_autostart.pth': source / 's1_battery_autostart.pth',
               'worker.py': source / 'worker.py',
               'warning_filter.py': source / 'warning_filter.py',
               'warning_hook_blob.py': source / 'warning_hook_blob.py',
               'telemetry.py': source / 'telemetry.py'}
    result = {}
    for name, path in sources.items():
        data = path.read_text(encoding='utf-8')
        if name.endswith('.py'):
            compile(data, name, 'exec')
        result[name] = data
    return result


def build(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in payload_files().items():
        (destination / name).write_text(data, encoding='utf-8', newline='\n')
    print(destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination')
    build(parser.parse_args().destination)

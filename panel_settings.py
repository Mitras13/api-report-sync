"""Validated, atomic operator settings shared by the robot and local panel."""
import json
import os
from pathlib import Path
import tempfile

PATH = Path(__file__).resolve().parent / 'panel' / 'settings.json'


def read_settings():
    if not PATH.exists():
        return {}
    return json.loads(PATH.read_text(encoding='utf-8'))


def validate_settings(value, labels):
    if not isinstance(value, dict) or set(value) - {'windows', 'disabled', 'delay'}:
        raise ValueError('Invalid settings fields')
    windows = value.get('windows', {})
    disabled = value.get('disabled', [])
    delay = value.get('delay', 30)
    if not isinstance(windows, dict) or any(k not in labels or type(v) is not int or not 0 <= v <= 90 for k, v in windows.items()):
        raise ValueError('Replacement window must be 0–90 days')
    if not isinstance(disabled, list) or any(x not in labels for x in disabled):
        raise ValueError('Unknown downloader')
    if type(delay) not in (int, float) or not 0 <= delay <= 600:
        raise ValueError('Delay must be 0–600 seconds')
    return {'windows': windows, 'disabled': sorted(set(disabled)), 'delay': delay}


def save_settings(value, labels):
    value = validate_settings(value, labels)
    PATH.parent.mkdir(exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=PATH.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return value

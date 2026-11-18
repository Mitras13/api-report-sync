from unittest.mock import patch

import pytest

import panel_settings as settings
from panel.server import Handler


@pytest.mark.parametrize('value', [
    {'windows': {'unknown': 7}}, {'windows': {'VP_HK': -1}},
    {'windows': {'VP_HK': True}}, {'disabled': ['unknown']},
    {'delay': 601}, {'delay': float('nan')}, {'delay': float('inf')},
    {'sql': 'arbitrary'}, [],
])
def test_reject_invalid_operator_settings(value):
    with pytest.raises(ValueError):
        settings.validate_settings(value, {'VP_HK'})


def test_atomic_settings_roundtrip(tmp_path):
    path = tmp_path / 'settings.json'
    value = {'windows': {'VP_HK': 3}, 'disabled': ['VP_HK'], 'delay': 10}
    with patch.object(settings, 'PATH', path):
        assert settings.read_settings() == {}
        settings.save_settings(value, {'VP_HK'})
        assert settings.read_settings() == value
        assert list(tmp_path.iterdir()) == [path]
        with pytest.raises(ValueError):
            settings.save_settings({'delay': -2}, {'VP_HK'})
        assert settings.read_settings() == value


def test_host_check_rejects_rebinding():
    handler = object.__new__(Handler)
    handler.headers = {'Host': 'attacker.example:8876'}
    assert not handler.allowed()
    handler.headers = {'Host': '127.0.0.1:8876'}
    assert handler.allowed()

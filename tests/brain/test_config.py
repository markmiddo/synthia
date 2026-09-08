from pathlib import Path

import yaml

from synthia.brain.config import BrainConfig, load_brain_config


def test_defaults_when_no_file(tmp_path):
    cfg = load_brain_config(path=tmp_path / "missing.yaml", env={})
    assert cfg.cwd == Path.home() / "dev" / "eventflo"
    assert cfg.max_workers == 2
    assert cfg.job_timeout_s == 1800
    assert cfg.confirm_timeout_s == 120
    assert cfg.telegram_token == ""
    assert cfg.telegram_allowed_users == []
    assert "eventflo" in cfg.phrase_hints


def test_yaml_and_env_override(tmp_path):
    p = tmp_path / "brain.yaml"
    p.write_text(
        yaml.dump(
            {
                "cwd": "/srv/eventflo",
                "repos": ["/srv/eventflo/eva-ai"],
                "max_workers": 1,
                "voice": "en-AU-Neural2-D",
                "telegram_allowed_users": [42],
                "telegram_chat_id": 42,
                "phrase_hints": ["FloSale"],
            }
        )
    )
    cfg = load_brain_config(path=p, env={"BRAIN_TELEGRAM_TOKEN": "tok"})
    assert cfg.cwd == Path("/srv/eventflo")
    assert cfg.repos == [Path("/srv/eventflo/eva-ai")]
    assert cfg.max_workers == 1
    assert cfg.voice == "en-AU-Neural2-D"
    assert cfg.telegram_allowed_users == [42]
    assert cfg.telegram_chat_id == 42
    assert cfg.telegram_token == "tok"
    assert cfg.phrase_hints == ["FloSale"]


def test_unknown_key_ignored_with_warning(tmp_path, caplog):
    p = tmp_path / "brain.yaml"
    p.write_text(yaml.dump({"bogus": 1}))
    cfg = load_brain_config(path=p, env={})
    assert isinstance(cfg, BrainConfig)
    assert "bogus" in caplog.text

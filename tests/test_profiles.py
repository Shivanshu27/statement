"""Profile schema: narrow on purpose, so an agent cannot memorise answers into it."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from statement.adapters.profiles_fs import DirectoryProfiles, ProfileLoadError
from statement.domain.profile import Profile
from tests.conftest import ROOT


def _raw(name: str = "ledger_split") -> dict[str, object]:
    return dict(yaml.safe_load((ROOT / "profiles" / f"{name}.yml").read_text()))


def test_every_repo_profile_loads(all_profiles) -> None:
    assert {p.id for p in all_profiles} >= {
        "ledger_split",
        "signed_single",
        "drcr_suffix",
        "paren_negative",
    }


def test_fingerprints_do_not_overlap(all_profiles) -> None:
    """Each layout's samples classify to exactly its own profile."""
    from statement.domain.outcome import Ok
    from statement.extract.tier1 import classify
    from tests.conftest import read, sample

    for p in all_profiles:
        got = classify(read(sample(p.id, 0).pdf), all_profiles)
        assert isinstance(got, Ok) and got.value.id == p.id


def test_unknown_keys_are_errors() -> None:
    data = _raw()
    data["expected_closing"] = "1,23,456.00"  # the memorisation an agent might try
    with pytest.raises(ValidationError):
        Profile.model_validate(data)


def test_split_mode_requires_debit_and_credit_columns() -> None:
    data = _raw()
    data["columns"] = [c for c in data["columns"] if c["role"] != "credit"]  # type: ignore[union-attr]
    with pytest.raises(ValidationError):
        Profile.model_validate(data)


def test_balance_policy_must_match_columns() -> None:
    data = _raw()
    data["balance_policy"] = "none"
    with pytest.raises(ValidationError):
        Profile.model_validate(data)


def test_period_pattern_needs_two_groups() -> None:
    data = _raw()
    data["period"] = {"pattern": r"From (\S+)", "format": "%d/%m/%Y"}
    with pytest.raises(ValidationError):
        Profile.model_validate(data)


def test_file_name_must_match_id(tmp_path: Path) -> None:
    (tmp_path / "other.yml").write_text(yaml.safe_dump(_raw()))
    with pytest.raises(ProfileLoadError):
        DirectoryProfiles(tmp_path).profiles()

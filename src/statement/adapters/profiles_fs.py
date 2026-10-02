"""Layout profiles from a directory of YAML files."""

from __future__ import annotations

from pathlib import Path

import yaml

from statement.domain.profile import Profile


class ProfileLoadError(ValueError):
    pass


class DirectoryProfiles:
    def __init__(self, root: Path) -> None:
        self._root = root

    def profiles(self) -> tuple[Profile, ...]:
        out: list[Profile] = []
        for path in sorted(self._root.glob("*.yml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            try:
                profile = Profile.model_validate(data)
            except ValueError as exc:
                raise ProfileLoadError(f"{path.name}: {exc}") from exc
            if profile.id != path.stem:
                raise ProfileLoadError(
                    f"{path.name}: id {profile.id!r} must match file name"
                )
            out.append(profile)
        return tuple(out)

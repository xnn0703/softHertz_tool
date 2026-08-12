"""包内资源定位检查。"""

from __future__ import annotations

from pathlib import Path

import pytest

from soft_hertz_tool.shared.resources import resource_path


@pytest.mark.parametrize(
    "name",
    (
        "soft_hertz_logo_deepspace_blue_512.png",
        "soft_hertz_logo_deepspace_blue_512.ico",
    ),
)
def test_packaged_resources_are_available(name: str):
    path = Path(resource_path(name))
    assert path.is_file()
    assert path.stat().st_size > 0


def test_missing_resource_is_reported():
    with pytest.raises(FileNotFoundError, match="未找到 SoftHertz Tool 资源"):
        resource_path("missing-resource.bin")

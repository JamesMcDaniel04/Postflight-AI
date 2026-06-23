"""Parse a target spec string into a concrete Driver."""

from __future__ import annotations

from .base import Driver, TargetSpec

SCHEMES = ("web", "api", "ios", "android")


def parse_target(target: str) -> TargetSpec:
    for scheme in SCHEMES:
        prefix = f"{scheme}://"
        if target.startswith(prefix):
            return TargetSpec(scheme=scheme, address=target[len(prefix):])
    raise ValueError(
        f"unrecognized target {target!r} — expected one of: "
        + ", ".join(f"{s}://" for s in SCHEMES)
    )


def make_driver(target: str) -> Driver:
    """Build a Driver for the target. Returns the driver without launching it
    (launch happens in ``driver.start()``). Raises ValueError for an unknown
    scheme; api/ios/android construct a driver whose ``available()`` is False
    until that surface is implemented."""
    spec = parse_target(target)
    if spec.scheme == "web":
        from .web import WebDriver
        return WebDriver(spec.address)
    if spec.scheme == "api":
        from .api import ApiDriver
        return ApiDriver(spec.address)
    from .mobile import MobileDriver
    return MobileDriver(spec.scheme, spec.address)

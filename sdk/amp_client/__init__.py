from amp_client.async_client import AsyncAMPClient
from amp_client.client import AMPClient
from amp_client.exceptions import AMPError

# Read the version from the installed package metadata so pyproject.toml stays
# the single source of truth. Falls back to the current release when running
# from a source checkout that was never installed.
try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _version

    __version__ = _version("amp-client")
except PackageNotFoundError:  # pragma: no cover - source-only checkout
    __version__ = "0.1.0"

__all__ = ["AMPClient", "AsyncAMPClient", "AMPError", "__version__"]

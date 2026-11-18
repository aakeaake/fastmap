import importlib.metadata

try:
    __version__ = importlib.metadata.version("fastmap")
except importlib.metadata.PackageNotFoundError:  # running from an uninstalled checkout
    __version__ = "0.0.0+unknown"

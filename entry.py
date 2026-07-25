"""Entry point for PyInstaller: imports the package with context (relative imports
work) and launches the app. Do not run this directly; use `uv run voooxly`."""
from voooxly.__main__ import main

if __name__ == "__main__":
    main()
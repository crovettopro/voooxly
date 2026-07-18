"""Entry point para PyInstaller: importa el paquete con contexto (imports relativos
funcionan) y lanza la app. No usar directamente para ejecutar; usa `uv run dictador`."""
from dictador.__main__ import main

if __name__ == "__main__":
    main()
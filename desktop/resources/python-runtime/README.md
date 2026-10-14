# Bundled Python runtime (optional)

Place a **portable / embeddable CPython** distribution here to make the desktop
installer fully self-contained — i.e. it will run on a machine that has no
Python at all.

Expected layout after extraction:

```
desktop/resources/python-runtime/
├── python.exe            (Windows)
├── python311.zip
├── Lib/  or  Lib/site-packages/
└── ...                   (the rest of the embeddable distribution)
```

On Linux/macOS use `bin/python`.

## How to build it (Windows, offline-friendly)

```bat
REM 1. download the "Windows embeddable package (64-bit)" for CPython 3.11+
REM    from https://www.python.org/downloads/windows/
REM 2. unzip it into desktop\resources\python-runtime\
REM 3. enable site-packages + pip (edit python311._pth: uncomment "import site")
REM 4. install the backend dependencies into the embedded interpreter:
desktop\resources\python-runtime\python.exe -m ensurepip
desktop\resources\python-runtime\python.exe -m pip install -r requirements.txt
```

The main process resolves the interpreter in this order (see
`desktop/src/main.js::pythonCandidates`):

1. `resources/python-runtime/python.exe` — the bundled interpreter above;
2. `app/.venv/Scripts/python.exe` — a venv shipped inside the app payload;
3. the repository `.venv` — development only;
4. `python` on `PATH` — last resort, reported honestly in the diagnostics.

If this folder is empty the installer still works, but the target machine must
have a Python 3.11+ interpreter with the backend dependencies installed.  The
first-launch diagnostic refuses to start (and tells the user exactly what is
missing) instead of showing a blank window.

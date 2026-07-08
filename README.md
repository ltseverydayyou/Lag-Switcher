Build VyperiaLagSwitch.exe
==========================

Open the project folder in Visual Studio, then open:

View > Terminal

Make sure the terminal is in the project root, the same folder as:

VyperiaLagSwitch.py
VyperiaLagSwitch.spec

Install PyInstaller if needed:

RUN THIS:

```
python -m pip install pyinstaller
```

Build the exe from the saved spec file:

RUN THIS:

```
python -m PyInstaller --clean --noconfirm VyperiaLagSwitch.spec
```

The finished exe will be created here:

```
dist\VyperiaLagSwitch.exe
```

Notes
-----

The spec file includes:

uac_admin=True

That makes the exe request administrator privileges when it starts.

The build folder is temporary and can be deleted after building.

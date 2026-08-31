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
python -m pip install customtkinter keyboard psutil pillow
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

## Android

The repository now also includes **Vyperia Lag Switch for Android** under `android/`.

It uses Android's local `VpnService` as a packet blackhole rather than disabling Wi-Fi or mobile data. You can target the whole device or one installed app, use the same anti-timeout active/pause cycle as the desktop version, and enable a draggable floating button over games/apps.

### Android features

- Whole-system or per-app lag switching
- Draggable floating overlay button
- Anti-timeout cycle
- Reactivate-after-pause cycle
- Configurable active and pause times
- Compact overlay mode
- Overlay size, initial position, and ON/OFF colors
- Foreground notification with a quick toggle
- No root required

Android only allows one ordinary `VpnService` at a time, so the non-root build cannot run alongside another VPN app.

### Build

```bash
cd android
gradle :app:assembleRelease
```

The GitHub Actions workflow builds the APK on Android source changes. Running the workflow manually publishes the reproducible APK to the `android-v1.0.0` GitHub release.

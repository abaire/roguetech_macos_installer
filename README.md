# roguetech_macos_installer
Script to install [RogueTech](https://roguetech.fandom.com/wiki/Installation#macOS) on macOS without relying on Wine.

# Prerequisites
* A Steam install of Battletech (it should be easy to extend this to other distributions by extending the basic `STEAM_INSTALL_DIR` check, contributions welcome)
* `mono`
* `git`
* `python3` - should be bundled with macOS
* `json5` Python module
* `xmltodict` Python module

## Optional for GUI
* `rich` Python module
* `sshkeyboard` Python module

The script checks for missing requirements and gives hints for how to install them.

# Limitations
* The script does not support all install task methods, so some options may not be available even if they are manually enabled.
* The script ignores some of the install task attributes that may actually be needed. I have not run the actual RogueTechLauncher and do not know what things like `difficultyModifier` and `influenceMode` are meant to do, so if they're anything more than informational displays in the launcher itself, they're not wired up right now.
* The script does not provide any mechanism to uninstall. Outside of running ModTek `/restore` and deleting the Mod directory I'm not sure what else would need to be cleaned up.
* The `RogueTechPerfFix` does not seem to be compatible with my M1, resulting in a black screen after the ModTek loader (with "Press [ESC] to skip" if the mouse is moved). This persists for over 2 hours, so I assume it's a bug. The script skips installing the perf fix if it detects an ARM-based CPU, which seems to work on my machine.

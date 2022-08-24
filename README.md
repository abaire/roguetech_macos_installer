# roguetech_macos_installer
Script to install [RogueTech](https://roguetech.fandom.com/wiki/Installation#macOS) on macOS without relying on Wine.

# Prerequisites
* A Steam install of Battletech (it should be easy to extend this to other distributions by extending the basic `STEAM_INSTALL_DIR` check, contributions welcome)
* `mono`
* `git`
* `xpath` - should be bundled with macOS or Xcode command line tools
* `python3` - should be bundled with macOS
* `json5` Python module

The script should check for missing requirements and give hints for how to install them.

# Limitations
* The script just uses the default RogueTech selections from [the config file](https://github.com/BattletechModders/RogueTech/blob/master/RtConfig.xml). In theory you could modify the copy of the file in the `RtlCache/RtCache` directory created next to your `BattleTech.app` binary and change `<isSelected>false</isSelected>` to `<isSelected>true</isSelected>` for items you'd like to enable and then rerun the installer script, but this is not tested.
* The script does not support all install task methods, so some options may not be available even if they are manually enabled.
* The script ignores some of the install task attributes that may actually be needed. I have not run the actual RogueTechLauncher and do not know what things like `difficultyModifier` and `influenceMode` are meant to do, so if they're anything more than informational displays in the launcher itself, they're not wired up right now.
* The script does not provide any mechanism to uninstall. Outside of running ModTek `/restore` and deleting the Mod directory I'm not sure what else would need to be cleaned up.

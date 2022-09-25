#!/usr/bin/env python3

import argparse
import collections
from collections import defaultdict
import glob
import json
import logging
import os
import shutil
import subprocess
import sys
import textwrap
from typing import Set

try:
    import json5
except ImportError:
    print("Missing required Python module 'json5'.")
    print("Try 'pip3 install json5'")
    sys.exit(1)
try:
    import xmltodict
except ImportError:
    print("Missing required Python module 'xmltodict'.")
    print("Try 'pip3 install xmltodict'")
    sys.exit(1)

try:
    import sshkeyboard
    import rich
    from rich import console
    from rich.align import Align
    from rich.columns import Columns
    from rich.layout import Layout
    from rich.prompt import Prompt
    from rich.rule import Rule
    from rich.style import Style
    from rich.table import Table
    from rich.text import Text

    _GUI_ENABLED = True
except ImportError:
    _GUI_ENABLED = False

_STEAM_INSTALL_DIR = (
    "~/Library/Application Support/Steam/steamapps/common/BATTLETECH/BattleTech.app"
)
_RT_CONFIG_FILENAME = "RtConfig.xml"

# As of f459d6a some tasks are skipped:
_TASK_BLACKLIST = {
    "modtekInstall",  # Handled by this install script directly.
    "perfixInstall",  # Appears to cause the game to become stuck when prewarming cache or loading blocks.
    "CommanderPortraitLoader",  # Included in the Core by default.
}


def _merge_dicts(a: dict, b: dict, path=None):
    """Merges b into a, replacing any non-container values."""
    if path is None:
        path = []

    for key, b_value in b.items():
        if key not in a:
            a[key] = b_value
            continue

        a_value = a[key]
        if isinstance(a_value, dict):
            if not isinstance(b_value, dict):
                raise ValueError(f"a[{key}] is a dict, but b[{key}] is not!")
            _merge_dicts(a_value, b_value, path + [str(key)])
            continue

        if isinstance(a_value, list):
            if not isinstance(b_value, list):
                raise ValueError(f"a[{key}] is a list, but b[{key}] is not!")

            a_value.extend(b_value)
            continue

        a[key] = b_value

    return a


def _merge_json_files(infile_path: str, outfile_path: str):
    with open(infile_path, encoding="utf-8") as infile:
        new_data = json5.load(infile)

    with open(outfile_path, encoding="utf-8") as infile:
        old_data = json5.load(infile)

    _merge_dicts(old_data, new_data)

    with open(outfile_path, "w", encoding="utf-8") as outfile:
        json.dump(old_data, outfile, indent=4)


def _find_install_dir():
    steam_path = os.path.abspath(os.path.expanduser(_STEAM_INSTALL_DIR))
    if os.path.isdir(steam_path):
        return steam_path

    # TODO: Search alternative paths.
    return None


def symlink_dir_if_needed(target: str, link: str):
    if os.path.islink(link):
        return
    os.symlink(target, link, target_is_directory=True)


def _load_xml_dict(path: str) -> dict:
    with open(path, encoding="utf-8") as infile:
        return xmltodict.parse(infile.read())


def _index_tasks_by_option_group(config: dict) -> dict:
    """Returns a dict mapping optionGroupId -> [InstallTask]"""
    ret = defaultdict(list)
    tasks = config["RogueTechConfig"]["Tasks"]["InstallTask"]
    for task in tasks:
        group = task["optionGroupId"]
        ret[group].append(task)
    return ret


def _index_tasks_by_id(config: dict) -> dict:
    """Returns a dict mapping Id -> [InstallTask]"""
    tasks = config["RogueTechConfig"]["Tasks"]["InstallTask"]
    ret = {}
    for task in tasks:
        ret[task["Id"]] = task
    return ret


def _get_selected_tasks(config: dict) -> list:
    tasks = config["RogueTechConfig"]["Tasks"]["InstallTask"]
    return [task for task in tasks if task["isSelected"] == "true"]


def _get_deselected_tasks(config: dict) -> list:
    tasks = config["RogueTechConfig"]["Tasks"]["InstallTask"]
    return [task for task in tasks if task["isSelected"] == "false"]


def _filtered_copy(source_path: str, target_path: str, excludes: Set[str]):
    if os.path.isdir(source_path):
        os.makedirs(target_path, exist_ok=True)
        for item in glob.glob(os.path.join(source_path, "*")):
            basename = os.path.basename(item)
            if basename in excludes:
                continue

            if os.path.isdir(item):
                target = os.path.join(target_path, basename)
                logging.debug(f"Copydir '{item}' => {target}")
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                logging.debug(f"Copyfile '{item}' into '{target_path}")
                shutil.copy2(item, target_path)
    elif os.path.exists(source_path):
        shutil.copy2(source_path, target_path)
    else:
        logging.warning(f"Missing expected file {source_path}' during copy operation.")


class Installer:
    """RogueTech installer."""

    def __init__(self, bt_install_path: str, check_updates=True, dry_run=False):
        self.base = bt_install_path
        self.contents = os.path.join(self.base, "Contents")
        self.resources = os.path.join(self.contents, "Resources")
        self.mod_dir = os.path.join(self.resources, "Mods")
        self.battletech_data_dir = os.path.join(
            self.contents, "MacOS", "BattleTech_Data"
        )
        self.rtlcache = os.path.abspath(os.path.join(self.base, "..", "RtlCache"))
        self.rtcache = os.path.join(self.rtlcache, "RtCache")
        self.rtconfig = os.path.join(self.rtcache, _RT_CONFIG_FILENAME)
        self.cabcache = os.path.join(self.rtlcache, "CabCache")

        self.check_updates = check_updates
        self.dry_run = dry_run

    def git(self, target_path: str, repo_url: str):
        """Fetches or updates a git repository."""

        if os.path.isdir(target_path):
            if not self.check_updates:
                logging.debug(
                    f"Skipping update on repo '{repo_url}' in '{target_path}'"
                )
                return
            logging.info(f"Checking for updates in '{target_path}...")

            output = subprocess.check_output(
                ["git", "checkout", "--"], stderr=subprocess.STDOUT, cwd=target_path
            )
            logging.debug(f"git checkout -- in {target_path}: {output}")
            output = subprocess.check_output(
                ["git", "fetch", "origin", "--depth", "1"],
                stderr=subprocess.STDOUT,
                cwd=target_path,
            )
            logging.debug(f"git fetch in {target_path}: {output}")
            return

        logging.info(
            f"Cloning '{repo_url}' into '{target_path}, this may take a very long time..."
        )
        output = subprocess.check_output(
            ["git", "clone", "--depth", "1", repo_url, target_path]
        )
        logging.debug(f"git clone {repo_url} in {target_path}: {output}")

    def _cache_community_asset_bundles(self):
        """Fetches the CAB files."""
        os.makedirs(self.cabcache, exist_ok=True)

        support_repo_path = os.path.join(self.cabcache, "CabSupRepoData")
        self.git(
            support_repo_path,
            "https://github.com/BattletechModders/Community-Asset-Bundle-Data.git",
        )

        manifest = _load_xml_dict(os.path.join(support_repo_path, "CabRepos.xml"))
        for repo in manifest["CabRepoData"]["Repos"]["CabRepo"]:
            subpath = repo["cacheSubPath"]
            url = repo["repoUrl"]
            self.git(os.path.join(self.cabcache, subpath), url)

    def cache_roguetech_files(self):
        """Caches the RogueTech mod content."""
        os.makedirs(self.mod_dir, exist_ok=True)
        symlink_dir_if_needed(
            os.path.join(self.resources, "Data"), self.battletech_data_dir
        )
        symlink_dir_if_needed(
            self.mod_dir, os.path.abspath(os.path.join(self.base, "..", "Mods"))
        )
        symlink_dir_if_needed(
            self.mod_dir, os.path.join(self.contents, "MacOS", "Mods")
        )

        os.makedirs(self.rtlcache, exist_ok=True)
        self.git(self.rtcache, "https://github.com/BattletechModders/RogueTech.git")

        self._cache_community_asset_bundles()
        symlink_dir_if_needed(self.cabcache, os.path.join(self.mod_dir, "cabs"))

    def _install_injector(self, injector_dir):
        managed_dir = os.path.join(self.battletech_data_dir, "Managed")
        try:
            output = subprocess.check_output(
                [
                    "mono64",
                    "ModTekInjector.exe",
                    "/install",
                    "/y",
                    f"/manageddir={managed_dir}",
                ],
                stderr=subprocess.STDOUT,
                cwd=injector_dir,
            )
            logging.debug(f"ModTekInjector /install: {output}")
        except subprocess.CalledProcessError as err:
            output = err.output.decode("utf-8")
            logging.error(f"Failed to install ModTek: {output}")
            raise

    def _uninstall_injector(self, injector_dir):
        managed_dir = os.path.join(self.battletech_data_dir, "Managed")
        try:
            output = subprocess.check_output(
                [
                    "mono64",
                    "ModTekInjector.exe",
                    "/restore",
                    f'/manageddir="{managed_dir}"',
                ],
                stderr=subprocess.STDOUT,
                cwd=injector_dir,
            )
            logging.debug(f"ModTekInjector /restore: {output}")
        except subprocess.CalledProcessError as err:
            output = err.output.decode("utf-8")
            logging.error(f"Failed to uninstall ModTek: {output}")
            raise

    def _get_excludes(self, task: dict) -> Set[str]:
        # The RtConfig.xml erroneously lists "Optional" as the path instead of "Optionals"
        exclude_paths = set(task["excludePaths"].split(","))
        if "Optional" in exclude_paths:
            exclude_paths.add("Optionals")
        return exclude_paths

    def _normal_install(self, task: dict):
        exclude_paths = self._get_excludes(task)
        source_path = os.path.join(self.rtcache, task["sourcePath"] or "")
        target_path = os.path.join(self.mod_dir, task["targetPath"] or "")
        _filtered_copy(source_path, target_path, exclude_paths)

    def _multi_component_install(self, task: dict):
        exclude_paths = self._get_excludes(task)
        source_paths = [x.strip() for x in task["sourcePath"].split(",")]
        target_paths = [x.strip() for x in task["targetPath"].split(",")]

        for source_path, target_path in zip(source_paths, target_paths):
            source_path = os.path.join(self.rtcache, source_path or "")
            target_path = os.path.join(self.mod_dir, target_path or "")
            _filtered_copy(source_path, target_path, exclude_paths)

    def _basic_json_merge(self, task: dict):
        source_path = os.path.join(self.rtcache, task["sourcePath"] or "")
        target_path = os.path.join(self.mod_dir, task["targetPath"] or "")
        _merge_json_files(source_path, target_path)

    def _set_boot_config_gfx_jobs(self, job_count):
        boot_config = os.path.join(self.battletech_data_dir, "boot.config")
        with open(boot_config, encoding="utf-8") as infile:
            contents = infile.readlines()

        filter = lambda x: not x.startswith("gfx-enable-native-gfx-jobs=") and not x.startswith("gfx-enable-gfx-jobs=")
        contents = [line for line in contents if filter(line)]

        if job_count:
            contents.extend([
                "gfx-enable-gfx-jobs=1\n",
                f"gfx-enable-native-gfx-jobs={job_count}\n"
            ])
        else:
            contents.append("gfx-enable-native-gfx-jobs=\n")

        with open(boot_config, "w", encoding="utf-8") as outfile:
            outfile.writelines(contents)

    def _run_process_and_install(self, task):
        source_path = os.path.join(self.rtcache, task["sourcePath"] or "")
        installer = task["targetPath"]

        # The only use of this install type appears to be the perfixInstall task, which sets `sourcePath` to the
        # installer directory and `targetPath` to the name of the installer binary.
        try:
            output = subprocess.check_output(
                [
                    "mono64",
                    installer,
                ],
                stderr=subprocess.STDOUT,
                cwd=source_path,
            )
            logging.debug(f"Ran installer {installer}: {output}")
        except subprocess.CalledProcessError as err:
            output = err.output.decode("utf-8")
            logging.error(f"Failed to run installer {source_path}/{installer}: {output}")
            raise

        # The installer then copies the directory with an implicit targetPath of /basename(source_path)
        _filtered_copy(source_path, os.path.join(self.mod_dir, os.path.basename(source_path)), set())

    def _install_task(self, task: dict):
        task_id = task["Id"]
        if task_id in _TASK_BLACKLIST:
            logging.debug(f"Skipping blacklisted task {task_id}")
            return

        jobtype = task["jobType"]
        if jobtype == "NoOp":
            logging.debug(f"Skipping NoOp install task {task_id}")
            return

        if jobtype == "Install":
            self._normal_install(task)
            return

        if jobtype == "MultiComponentInstall":
            self._multi_component_install(task)
            return

        if jobtype == "BasicJsonMerge":
            self._basic_json_merge(task)
            return

        if jobtype == "DefaultBootConfig":
            self._set_boot_config_gfx_jobs(0)
            return

        if jobtype == "MThreadBootConfig":
            self._set_boot_config_gfx_jobs(1)
            return

        if jobtype == "RunProcessAndInstall":
            self._run_process_and_install(task)
            return

        logging.warning(
            f"Skipping unsupported install type {jobtype} for task {task_id}"
        )

    def _load_config(self, preserve_existing=True):
        if preserve_existing:
            try:
                config = _load_xml_dict(self._installed_config_path())
                logging.debug("Using previously installed config file.")
                return config
            except FileNotFoundError:
                return self._load_config(False)

        config = _load_xml_dict(self.rtconfig)
        logging.debug("Using default config file.")
        return config

    def perform_install(self, config=None):
        """Installs RogueTech."""
        if self.dry_run:
            logging.info("Dry-run mode, bypassing install")
            return

        logging.info("Installing ModTek...")
        injector = os.path.join(self.mod_dir, "ModTek")
        if not os.path.isdir(injector):
            shutil.copytree(os.path.join(self.rtcache, "ModTek"), injector)

        self._install_injector(injector)

        if not config:
            config = self._load_config()
            logging.info("Copying RogueTech config...")
            shutil.copy2(self.rtconfig, self._installed_config_path())
        else:
            logging.info("Writing updated RogueTech config...")
            with open(self._installed_config_path(), "w", encoding="utf-8") as outfile:
                 outfile.write(xmltodict.unparse(config, pretty=True))

        logging.info("Performing install...")
        tasks = _get_selected_tasks(config)
        for task in tasks:
            logging.debug(f"InstallTask {task}")
            self._install_task(task)

    def _installed_config_path(self):
        return os.path.join(self.mod_dir, _RT_CONFIG_FILENAME)

    def _print_task_info(self, task: dict, prefix=""):
        id = task["Id"]
        name = task["uiName"]
        descr = task["uiDescription"]

        print(f"{prefix}{id}")
        if name:
            print(
                "\n".join(
                    textwrap.wrap(name, initial_indent=" ", subsequent_indent="    ")
                )
            )
        if descr:
            print(
                "\n".join(
                    textwrap.wrap(descr, initial_indent=" ", subsequent_indent="    ")
                )
            )

    def is_option_enabled(self, config, option_id):
        tasks = config["RogueTechConfig"]["Tasks"]["InstallTask"]
        task_index = _index_tasks_by_option_group(config)
        for task in tasks:
            if task["Id"] != option_id:
                continue
            return task["isSelected"].lower() == "true"
        return False

    def set_option(self, config, group_id: str, task_id: str, new_value: bool):
        groups, task_group_index = self._extract_configuration_tree(config)
        task_index = _index_tasks_by_id(config)
        group = groups[group_id]
        option_type = group["optionType"]
        if option_type == "ExclusiveOption":
            if not new_value:
                raise ValueError("Attempt to disable an exclusive option.")

            task_group = task_group_index[group_id]
            for task in task_group:
                task["isSelected"] = "true" if task["Id"] == task_id else "false"

        elif option_type == "MultiSelectOption":
            task_index[task_id]["isSelected"] = "true" if new_value else "false"
        else:
            raise ValueError(f"Unsupported option type {option_type}")

    @staticmethod
    def _extract_configuration_tree(config):
        task_index = _index_tasks_by_option_group(config)
        groups = {}
        options = config["RogueTechConfig"]["Options"]["InstallOption"]
        for option in options:
            group_id = option["optionId"]
            groups[group_id] = option
        return groups, task_index

    def get_configuration_tree(self, preserve_existing=True):
        """Parses the configuration file into groups and a task index"""
        config = self._load_config(preserve_existing)
        groups, task_index = self._extract_configuration_tree(config)
        return config, groups, task_index

    def list_install_configuration(self):
        """Prints the current install configuration."""
        _, groups, task_index = self.get_configuration_tree()

        for group_id, group in groups.items():
            tasks = filter(lambda x: x["canSelect"] == "true", task_index[group_id])
            if not tasks:
                continue
            group_name = group["optionUiName"]
            print(group_name)
            print("=" * len(group_name))
            for task in tasks:
                if task["isSelected"] == "true":
                    self._print_task_info(task, "+ ")
                else:
                    self._print_task_info(task, "- ")
            print("")


def clamp(val: int, min_val: int, max_val: int) -> int:
    if val < min_val:
        return min_val
    if val > max_val:
        return max_val
    return val


class _App:
    _MENU = "menu"
    _CONTENT = "content"

    def __init__(self, installer: Installer):
        self._installer = installer

        self._current_group_index: int = 0
        self._cursor_row = 0
        self.reset()
        self._console = console.Console()
        self._root = Layout()
        self._running = False
        self._update()
        self._keymap = {
            "left": lambda: self.navigate_group(-1),
            "right": lambda: self.navigate_group(1),
            "up": lambda: self.navigate_task(-1),
            "down": lambda: self.navigate_task(1),
            "pageup": lambda: self.navigate_task(-5),
            "pagedown": lambda: self.navigate_task(5),
            "home": lambda: self.navigate_task(-1000000000),
            "end": lambda: self.navigate_task(1000000000),
            "space": self.toggle_task,
            "enter": self.toggle_task,
            "d": lambda: self.reset(False),
            "r": self.reset,
            "i": self.install,
        }

    def reset(self, preserve_existing=True):
        self._config, groups, self._task_index = self._installer.get_configuration_tree(preserve_existing)
        self._groups = []
        for group_id, group in groups.items():
            tasks = list(filter(lambda x: x["canSelect"] == "true", self._task_index[group_id]))
            if not tasks:
                continue
            self._groups.append((group, tasks))

    def install(self):
        self._installer.perform_install(self._config)

    def navigate_group(self, delta: int):
        new_index = clamp(
            self._current_group_index + delta, 0, len(self._groups) - 1
        )
        if new_index == self._current_group_index:
            return
        self._current_group_index = new_index
        self._cursor_row = 0

    def navigate_task(self, delta: int):
        _, tasks = self._groups[self._current_group_index]
        new_index = clamp(
            self._cursor_row + delta, 0, len(tasks) - 1
        )
        if new_index == self._cursor_row:
            return
        self._cursor_row = new_index

    def toggle_task(self):
        group, tasks = self._groups[self._current_group_index]
        task = tasks[self._cursor_row]
        option_type = group["optionType"]
        required_option = group.get("requiredOption")
        if required_option and not self._installer.is_option_enabled(self._config, required_option):
            return

        current_val = task["isSelected"].lower() == "true"

        if option_type == "ExclusiveOption":
            if current_val:
                # Don't allow exclusive options to be completely deselected.
                return
            current_val = True
        elif option_type == "MultiSelectOption":
            current_val = not current_val
        else:
            raise ValueError(f"Unsupported option type {option_type}")
        self._installer.set_option(self._config, group["optionId"], task["Id"], current_val)
        self._update()

    def _update(self):
        group, tasks = self._groups[self._current_group_index]

        required_option = group.get("requiredOption")
        disabled = False
        if required_option:
            disabled = not self._installer.is_option_enabled(self._config, required_option)
            # TODO: Handle OnHideSelect field when an option is disabled.
        option_type = group["optionType"]

        title = group["optionUiName"]
        description = group.get("optionDescription")

        if disabled:
            title_line = Text(f"{title} <DISABLED, requires {required_option}>", style=Style(dim=True, strike=True))
        else:
            title_line = Text(title)
        cols = [Layout(Align(title_line, align="center"), ratio=0)]
        if description and description != title:
            cols.append(Layout(Text(description), ratio=0))

        if disabled:
            cols.append(Align(Text(f"This content is disabled because it depends on the option {required_option} which is not enabled.", style=Style(bold=True, italic=True)), align="center", vertical="middle"))
        else:
            table = Table(show_lines=True, expand=True)
            table.add_column("", no_wrap=True)
            table.add_column("Option")
            table.add_column("Description")
            table.add_column("Diff")
            table.add_column("Save breaking?")

            for i, task in enumerate(tasks):
                if option_type == "MultiSelectOption":
                    prefix = "X" if task["isSelected"] == "true" else "_"
                else:
                    prefix = "+" if task["isSelected"] == "true" else "-"
                if self._cursor_row == i and not disabled:
                    prefix = Text.styled(f"[{prefix}]", style=Style(bold=True, blink=True))
                else:
                    prefix = f" {prefix} "
                save_breaking = "YES" if task["saveBreaking"] == "true" else " "

                table.add_row(prefix, task["uiName"], task["uiDescription"], task["difficultyModifier"], save_breaking)

            cols.append(table)

        cols.append(Layout(Align(Text(f"{self._current_group_index + 1}/{len(self._groups)}"), align="right"), ratio=0))
        cols.append(
            Layout(Align(Text("ESC: exit, SPACEBAR: toggle, i: install, d: reset options to default, r: reset options to installed, cursor keys: navigate"), align="center"),
                   ratio=0))

        self._root.split_column(*cols)

    def render(self):
        """Draws the application to the console."""
        rich.print(self._root)

    def _handle_key(self, key):
        if key == "esc" or key == "q":
            self._running = False
            return

        action = self._keymap.get(key, None)
        if action:
            action()
            return

        logging.info(f"Unhandled key {key}")

    def run(self):

        input_queue = []

        def handle_key(key):
            input_queue.append(key)
            sshkeyboard.stop_listening()

        self._running = True
        with self._console.screen() as screen:
            screen.update(self._root)

            try:
                while self._running:
                    input_queue.clear()
                    sshkeyboard.listen_keyboard(
                        on_press=handle_key,
                        until=None,
                        sequential=True,
                        delay_second_char=10,
                    )
                    for key in input_queue:
                        self._handle_key(key)
                    if self._running:
                        self._update()
                        screen.update(self._root)
            except KeyboardInterrupt:
                return


def _main(args):
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    bt_install_dir = _find_install_dir()
    if not bt_install_dir:
        print("Failed to find BATTLETECH install directory.")
        return 1

    if not shutil.which("mono64"):
        print(
            "mono must be installed. See https://www.mono-project.com/docs/getting-started/install/mac/"
        )
        return 1

    if not shutil.which("git"):
        print(
            "git must be installed. See https://git-scm.com/book/en/v2/Getting-Started-Installing-Git"
        )
        return 1

    if args.dry_run:
        args.noupdate = True
    installer = Installer(bt_install_dir, not args.noupdate, args.dry_run)
    installer.cache_roguetech_files()

    if _GUI_ENABLED and not args.no_gui:
        app = _App(installer)
        return app.run()

    if args.list:
        installer.list_install_configuration()
    else:
        installer.perform_install()

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)


    def _parse_args():
        parser = argparse.ArgumentParser()

        parser.add_argument(
            "-l",
            "--list",
            action="store_true",
            help="List the enabled and disabled RogueTech options and exit.",
        )

        parser.add_argument(
            "-n",
            "--noupdate",
            action="store_true",
            help="Suppress checking for updates of RogueTech data.",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do not actually modify any content.",
        )

        parser.add_argument(
            "--no-gui",
            action="store_true",
            help="Suppress the graphical user interface.",
        )

        parser.add_argument(
            "-v", "--verbose", action="store_true", help="Print verbose logging output."
        )
        return parser.parse_args()


    sys.exit(_main(_parse_args()))

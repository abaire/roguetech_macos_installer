#!/usr/bin/env python3

import argparse
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


_STEAM_INSTALL_DIR = (
    "~/Library/Application Support/Steam/steamapps/common/BATTLETECH/BattleTech.app"
)
_RT_CONFIG_FILENAME = "RtConfig.xml"

# As of f459d6a some tasks are skipped:
_TASK_BLACKLIST = {"modtekInstall", "perfixInstall", "CommanderPortraitLoader"}


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
    """Returns a dict mappibng optionGroupId -> [InstallTask]"""
    ret = defaultdict(list)
    tasks = config["RogueTechConfig"]["Tasks"]["InstallTask"]
    for task in tasks:
        group = task["optionGroupId"]
        ret[group].append(task)
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

    def __init__(self, bt_install_path: str, check_updates=True):
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

        logging.warning(
            f"Skipping unsupported install type {jobtype} for task {task_id}"
        )

    def perform_install(self):
        """Installs RogueTech."""

        logging.info("Installing ModTek...")
        injector = os.path.join(self.mod_dir, "ModTek")
        if not os.path.isdir(injector):
            shutil.copytree(os.path.join(self.rtcache, "ModTek"), injector)

        self._install_injector(injector)

        #   # TODO: RogueTechPerfFix causes a black screen with "Press [ESC] to skip" on M1.
        #   if [[ ! -d RogueTechPerfFix ]]; then
        #     if [[ "$(uname -p)" == "arm" ]]; then
        #       echo "Skipping install of RogueTechPerfFix due to black screen error on ARM."
        #     else
        #       cp -R "${RTCACHE}/RogueTechPerfFix" .
        #     fi
        #   fi

        logging.info("Copying RogueTech config...")
        shutil.copy2(self.rtconfig, self._installed_config_path())

        logging.info("Performing install...")
        config = _load_xml_dict(self.rtconfig)
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

    def list_install_configuration(self):
        """Prints the current install configuration."""

        try:
            config = _load_xml_dict(self._installed_config_path())
            logging.debug("Using previously installed config file.")
        except FileNotFoundError:
            config = _load_xml_dict(self.rtconfig)
            logging.debug("Using default config file.")

        task_index = _index_tasks_by_option_group(config)

        groups = {}
        options = config["RogueTechConfig"]["Options"]["InstallOption"]
        for option in options:
            group_id = option["optionId"]
            groups[group_id] = option

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

    installer = Installer(bt_install_dir, not args.noupdate)
    installer.cache_roguetech_files()

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
            "-v", "--verbose", action="store_true", help="Print verbose logging output."
        )
        return parser.parse_args()

    sys.exit(_main(_parse_args()))

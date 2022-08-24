#!/usr/bin/env bash
# See https://roguetech.fandom.com/wiki/Installation#macOS

set -eu
set -o pipefail
set -x

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
readonly STEAM_INSTALL_DIR="${HOME}/Library/Application Support/Steam/steamapps/common/BATTLETECH/BattleTech.app"

if [[ ! -d "${STEAM_INSTALL_DIR}" ]]; then
  echo "Failed to find BattleTech.app at '${STEAM_INSTALL_DIR}'"
  exit 1
fi
if [[ ! $(which mono) ]]; then
  echo "mono must be installed. See https://www.mono-project.com/docs/getting-started/install/mac/"
  exit 1
fi
if [[ ! $(which git) ]]; then
  echo "git must be installed. See https://git-scm.com/book/en/v2/Getting-Started-Installing-Git"
  exit 1
fi

NOUPDATE=false

while [[ $# -gt 0 ]] && [[ "$1" == "--"* ]]; do
    opt="$1"
    shift

    case "$opt" in
      "--noupdate" )
        NOUPDATE=true
        ;;
      "--help" )
        echo >&2 "Options:"
        echo >&2 "  --noupdate : Suppress checking for updates of RogueTech data."
        exit 1
        ;;
      *)
        echo >&2 "Invalid option: $@"
        exit 1
        ;;
   esac
done


function SymlinkIfNeeded() {
  local source="${1}"
  local link="${2}"
  if [[ ! -L "${link}" ]]; then
    ln -s "${source}" "${link}"
  fi
}

function GitClone() {
  local target_dir="${1}"
  local repo="${2}"

  if [[ ! -d "${1}" ]]; then
    git clone --depth 1 "${2}" "${1}"
  elif [[ ! ${NOUPDATE} ]]; then
    pushd "${1}" >/dev/null
    git checkout -- .
    git fetch origin --depth 1
    popd >/dev/null
  fi
}


BASE="${STEAM_INSTALL_DIR}"
CONTENTS="${BASE}/Contents"
RESOURCES="${CONTENTS}/Resources"

MOD_DIR="${RESOURCES}/Mods"
BATTLETECH_DATA_DIR="${CONTENTS}/MacOS/BattleTech__Data"

mkdir -p "${MOD_DIR}"
SymlinkIfNeeded "${RESOURCES}/Data" "${BATTLETECH_DATA_DIR}"
SymlinkIfNeeded "${MOD_DIR}" "${BASE}/../Mods"
SymlinkIfNeeded "${MOD_DIR}" "${CONTENTS}/MacOS/Mods"

pushd "${BASE}/.." >/dev/null
mkdir -p RtlCache
pushd RtlCache >/dev/null

GitClone RtCache https://github.com/BattletechModders/RogueTech.git
GitClone RogueData https://github.com/wmtorode/RogueLauncherData.git

mkdir -p CabCache
pushd CabCache >/dev/null
GitClone cabClan https://github.com/BattletechModders/Community-Asset-Bundle-Clan-Mech.git
GitClone cabIs https://github.com/BattletechModders/Community-Asset-Bundle-IS-Mech.git
GitClone cabMisc https://github.com/BattletechModders/Community-Asset-Bundle-Miscellaneous.git
GitClone CabSupRepoData https://github.com/BattletechModders/Community-Asset-Bundle-Data.git
GitClone cabTank https://github.com/BattletechModders/Community-Asset-Bundle-Tanks.git
popd >/dev/null  # CabCache

popd >/dev/null  # RtlCache

RTLCACHE="${BASE}/../RtlCache"

# Symlink the full install repos into the mod directory.
pushd "${MOD_DIR}" >/dev/null
mkdir -p RtlCache

pushd RtlCache >/dev/null
SymlinkIfNeeded "${RTLCACHE}/RogueData" RogueData
SymlinkIfNeeded "${RTLCACHE}/CabCache" CabCache
popd RtlCache >/dev/null

# pop MOD_DIR
popd >/dev/null

# pop BASE/..
popd



function install_rt_subcomponents() {
  local RTCACHE="${BASE}/../RtlCache/RtCache"
  pushd "${MOD_DIR}" >/dev/null

  if [[ ! -d ModTek ]]; then
    cp -R "${RTCACHE}/ModTek" .
  fi

  pushd ModTek >/dev/null
  mono ModTekInjector.exe /restore /manageddir="${BATTLETECH_DATA_DIR}/Managed/"
  mono ModTekInjector.exe /install /y /manageddir="${BATTLETECH_DATA_DIR}/Managed/"
  popd

  if [[ ! -d RogueTechPerfFix ]]; then
    cp -R "${RTCACHE}/RogueTechPerfFix" .
  fi


  # Copy just the non-excluded items from RtConfig.xml.
  EXCLUDES=(
    RtConfig.xml
    .git
    .gitignore
    .modtek
    .vscode
    Documents
    InstallOptions
    Optional
    Eras
    RogueTechPerfFix
  )
  for item in "${RTCACHE}"/*; do
    p="$(basename "${item}")"
    if [[ ! " ${EXCLUDES[*]} " =~ " ${p} " ]]; then
      rm -r "${p}" 2>/dev/null || true
      cp -R "${item}" .
    fi
  done

  # TODO: Handle the optional installs rom RtConfig.xml.

  popd # MOD_DIR
}
install_rt_subcomponents

#!/usr/bin/env bash
# See https://roguetech.fandom.com/wiki/Installation#macOS

set -eu
set -o pipefail

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


function GitClone() {
  local target_dir="${1}"
  local repo="${2}"

  if [[ ! -d "${1}" ]]; then
    git clone --depth 1 "${2}" "${1}"
  else
    pushd "${1}"
    git checkout -- .
    git fetch origin --depth 1
    popd
  fi
}


BASE="${STEAM_INSTALL_DIR}"
CONTENTS="${BASE}/Contents"
RESOURCES="${CONTENTS}/Resources"

MOD_DIR="${RESOURCES}/Mods"
BATTLETECH_DATA_DIR="${CONTENTS}/MacOS/BattleTech__Data"

mkdir -p "${MOD_DIR}"
if [[ ! -L "${BATTLETECH_DATA_DIR}" ]]; then
  ln -s "${RESOURCES}/Data" "${BATTLETECH_DATA_DIR}"
fi
if [[ ! -L "${BASE}/../Mods" ]]; then
  ln -s "${MOD_DIR}" "${BASE}/../Mods"
fi
if [[ ! -L "${CONTENTS}/MacOS/Mods" ]]; then
  ln -s "${MOD_DIR}" "${CONTENTS}/MacOS/Mods"
fi

pushd "${BASE}/.."
mkdir -p RtlCache
pushd RtlCache

GitClone RtCache https://github.com/BattletechModders/RogueTech.git
GitClone RogueData https://github.com/wmtorode/RogueLauncherData.git

mkdir -p CabCache
pushd CabCache
GitClone cabClan https://github.com/BattletechModders/Community-Asset-Bundle-Clan-Mech.git
GitClone cabIs https://github.com/BattletechModders/Community-Asset-Bundle-IS-Mech.git
GitClone cabMisc https://github.com/BattletechModders/Community-Asset-Bundle-Miscellaneous.git
GitClone CabSupRepoData https://github.com/BattletechModders/Community-Asset-Bundle-Data.git
GitClone cabTank https://github.com/BattletechModders/Community-Asset-Bundle-Tanks.git
popd

popd

RTLCACHE="${BASE}/../RtlCache"

# Symlink the full install repos into the mod directory.
pushd "${MOD_DIR}"
mkdir -p RtlCache

pushd RtlCache
ln -s "${RTLCACHE}/RogueData" RogueData
ln -s "${RTLCACHE}/CabCache" CabCache
popd RtlCache

# pop RtlCache
popd

# pop MOD_DIR
popd



function install_rt_subcomponents() {
  local RTCACHE="${BASE}/../RtlCache/RtCache"
  pushd "${MOD_DIR}"
  
  if [[ ! -d ModTek ]]; then
    cp -R "${RTCACHE}/ModTek" .
  fi

  pushd ModTek
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

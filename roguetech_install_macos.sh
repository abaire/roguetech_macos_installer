#!/usr/bin/env bash
# See https://roguetech.fandom.com/wiki/Installation#macOS

set -eu
set -o pipefail

readonly SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
readonly STEAM_INSTALL_DIR="${HOME}/Library/Application Support/Steam/steamapps/common/BATTLETECH/BattleTech.app"

if [[ ! -d "${STEAM_INSTALL_DIR}" ]]; then
  echo "Failed to find BattleTech.app at '${STEAM_INSTALL_DIR}'"
  exit 1
fi
if [[ ! $(which mono64) ]]; then
  echo "mono must be installed. See https://www.mono-project.com/docs/getting-started/install/mac/"
  exit 1
fi
if [[ ! $(which git) ]]; then
  echo "git must be installed. See https://git-scm.com/book/en/v2/Getting-Started-Installing-Git"
  exit 1
fi
if [[ ! $(which xpath) ]]; then
  # Should be part of macOS already so hopefully this never fails.
  echo "xpath must be installed."
  exit 1
fi
if [[ ! $(which python3) ]]; then
  # Should be part of macOS already.
  echo "Python 3.x must be installed."
  exit 1
fi
# RT JSON is futuristic and makes use of trailing commas that are not supported by the default json module.
if [[ ! $(python3 -m pip list | grep json5) ]]; then
  echo "The json5 Python module must be installed. Try:"
  echo "pip3 install json5"
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


EXTRACT_XPATH_ARRAY=()
function ExtractXPathArrayFromString() {
  local XMLFILE="${1}"
  local XPATH="${2}"
  local DELIMITER="${3:-,}"

  local ITEMS=$(xpath -q -e "${XPATH}/text()" "${XMLFILE}")
  EXTRACT_XPATH_ARRAY=($(echo ${ITEMS} | tr "${DELIMITER}" "\n"))
}


function ExtractXPathArray() {
  local XMLFILE="${1}"
  local XPATH="${2}"

  EXTRACT_XPATH_ARRAY=($(xpath -q -e "${XPATH}/text()" "${XMLFILE}"))
}



BASE="${STEAM_INSTALL_DIR}"
CONTENTS="${BASE}/Contents"
RESOURCES="${CONTENTS}/Resources"

MOD_DIR="${RESOURCES}/Mods"
BATTLETECH_DATA_DIR="${CONTENTS}/MacOS/BattleTech_Data"

mkdir -p "${MOD_DIR}"
SymlinkIfNeeded "${RESOURCES}/Data" "${BATTLETECH_DATA_DIR}"
SymlinkIfNeeded "${MOD_DIR}" "${BASE}/../Mods"
SymlinkIfNeeded "${MOD_DIR}" "${CONTENTS}/MacOS/Mods"

pushd "${BASE}/.." >/dev/null
mkdir -p RtlCache
pushd RtlCache >/dev/null

GitClone RtCache https://github.com/BattletechModders/RogueTech.git
# TODO: Is this actually used?
GitClone RogueData https://github.com/wmtorode/RogueLauncherData.git

function InstallCommunityAssetBundles() {
  mkdir -p CabCache
  pushd CabCache >/dev/null
  GitClone CabSupRepoData https://github.com/BattletechModders/Community-Asset-Bundle-Data.git
  local REPO_MANIFEST="CabSupRepoData/CabRepos.xml"

  ExtractXPathArray "${REPO_MANIFEST}" //CabRepoData/Repos/CabRepo/cacheSubPath
  local CAB_PATHS=${EXTRACT_XPATH_ARRAY[@]}
  for path in ${CAB_PATHS[@]}; do
    local REPO_URL=$(xpath -q -e "//CabRepoData/Repos/CabRepo[cacheSubPath=\"${path}\"]/repoUrl/text()" "${REPO_MANIFEST}")
    GitClone "${path}" "${REPO_URL}"
  done
  popd >/dev/null  # CabCache
}
InstallCommunityAssetBundles

popd >/dev/null  # RtlCache

RTLCACHE="${BASE}/../RtlCache"
RTCACHE="${RTLCACHE}/RtCache"

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


function _CopyHelper() {
  if [[ -d "${SOURCE_PATH}" ]]; then
    mkdir -p "${TARGET_PATH}"
  fi

  for item in "${SOURCE_PATH}"/*; do
    p="${item#"${SOURCE_PATH}/"}"
    if [[ ! " ${EXCLUDES[*]} " =~ " ${p} " ]]; then
      local TARGET="${TARGET_PATH}/${p}"
      cp -R "${item}" "${TARGET_PATH}"
    fi
  done
}


function DoNormalInstall() {
  local XMLFILE="${1}"
  local TASK_ID="${2}"
  local TASK_NODE_PATH="${3}"

  ExtractXPathArrayFromString "${RT_CONFIG}" ${TASK_NODE_PATH}/excludePaths
  local EXCLUDES=(${EXTRACT_XPATH_ARRAY[@]})

  # The RtConfig.xml erroneously lists "Optional" as the path instead of "Optionals"
  if [[ " ${EXCLUDES[*]} " =~ " Optional " ]]; then
    EXCLUDES+=("Optionals")
  fi

  local SOURCE_PATH=$(xpath -q -e "${TASK_NODE_PATH}/sourcePath/text()" "${XMLFILE}")
  if [[ -z "${SOURCE_PATH}" ]]; then
    SOURCE_PATH="${RTCACHE}"
  else
    SOURCE_PATH="${RTCACHE}/${SOURCE_PATH}"
  fi
  local TARGET_PATH=$(xpath -q -e "${TASK_NODE_PATH}/targetPath/text()" "${XMLFILE}")
  if [[ -z "${TARGET_PATH}" ]]; then
    TARGET_PATH=${MOD_DIR}
  else
    TARGET_PATH="${MOD_DIR}/${TARGET_PATH}"
  fi

  _CopyHelper
}


function DoMultiNormalInstall() {
  local XMLFILE="${1}"
  local TASK_ID="${2}"
  local TASK_NODE_PATH="${3}"

  ExtractXPathArrayFromString "${RT_CONFIG}" ${TASK_NODE_PATH}/excludePaths
  local EXCLUDES=("${EXTRACT_XPATH_ARRAY[@]}")

  ExtractXPathArrayFromString "${RT_CONFIG}" ${TASK_NODE_PATH}/sourcePath ", "
  SOURCE_PATHS=("${EXTRACT_XPATH_ARRAY[@]}")
  ExtractXPathArrayFromString "${RT_CONFIG}" ${TASK_NODE_PATH}/targetPath ", "
  TARGET_PATHS=("${EXTRACT_XPATH_ARRAY[@]}")

  i=0
  for SOURCE_PATH in "${SOURCE_PATHS[@]}"; do
    SOURCE_PATH="${RTCACHE}/${SOURCE_PATH}"
    TARGET_PATH="${MOD_DIR}/${TARGET_PATHS[i]}"
    i+=1

    _CopyHelper
  done
}

function DoBasicJSONMerge() {
  local XMLFILE="${1}"
  local TASK_ID="${2}"
  local TASK_NODE_PATH="${3}"

  local SOURCE_PATH=$(xpath -q -e "${TASK_NODE_PATH}/sourcePath/text()" "${XMLFILE}")
  local TARGET_PATH=$(xpath -q -e "${TASK_NODE_PATH}/targetPath/text()" "${XMLFILE}")
  python3 "${SCRIPT_DIR}/basic_json_merge.py" "${RTCACHE}/${SOURCE_PATH}" "${TARGET_PATH}"
}


# As of f459d6a some tasks are skipped:
#  modtekInstall - Handled explicitly by this script.
#  perfixInstall - Handled explicitly by this script.
#
#  CommanderPortraitLoader - Included in Core by default, so it's not actually optional.
TASK_BLACKLIST=(
  modtekInstall
  perfixInstall
  CommanderPortraitLoader
)

function InstallTask() {
  local XMLFILE="${1}"
  local TASK_ID="${2}"

  if [[ " ${TASK_BLACKLIST[*]} " =~ "${TASK_ID}" ]]; then
    return
  fi

  echo "Installing ${TASK_ID}..."

  local TASK_NODE_PATH=//RogueTechConfig/Tasks/InstallTask[descendant::Id=\"${TASK_ID}\"]

  local INSTALL_TYPE=$(xpath -q -e "${TASK_NODE_PATH}/jobType/text()" "${XMLFILE}")
  case "${INSTALL_TYPE}" in
    "Install" )
      DoNormalInstall "${XMLFILE}" "${TASK_ID}" "${TASK_NODE_PATH}"
      ;;

    "MultiComponentInstall" )
      DoMultiNormalInstall "${XMLFILE}" "${TASK_ID}" "${TASK_NODE_PATH}"
      ;;

    "BasicJsonMerge" )
      DoBasicJSONMerge "${XMLFILE}" "${TASK_ID}" "${TASK_NODE_PATH}"
      ;;

    "NoOp" )
      ;;

    *)
      echo "WARNING: RTConfig install type '${INSTALL_TYPE}' for task '${TASK_ID}' not supported, ignoring."
      ;;
  esac
}

function InstallRTSubcomponents() {
  pushd "${MOD_DIR}" >/dev/null

  if [[ ! -d ModTek ]]; then
    cp -R "${RTCACHE}/ModTek" .
  fi

  pushd ModTek >/dev/null
  mono64 ModTekInjector.exe /restore /manageddir="${BATTLETECH_DATA_DIR}/Managed/"
  mono64 ModTekInjector.exe /install /y /manageddir="${BATTLETECH_DATA_DIR}/Managed/"
  popd >/dev/null

  # TODO: RogueTechPerfFix causes a black screen with "Press [ESC] to skip" on M1.
  if [[ ! -d RogueTechPerfFix ]]; then
    if [[ "$(uname -p)" == "arm" ]]; then
      echo "Skipping install of RogueTechPerfFix due to black screen error on ARM."
    else
      cp -R "${RTCACHE}/RogueTechPerfFix" .
    fi
  fi

  local RT_CONFIG="${RTCACHE}/RtConfig.xml"
  cp "${RT_CONFIG}" .

  ExtractXPathArray "${RT_CONFIG}" //RogueTechConfig/Tasks/InstallTask[descendant::isSelected=\"true\"]/Id
  local SELECTED_TASKS=${EXTRACT_XPATH_ARRAY[@]}

  for task in ${SELECTED_TASKS[@]}; do
    InstallTask "${RT_CONFIG}" "${task}"
  done

  # TODO: Handle the optional installs rom RtConfig.xml.

  popd >/dev/null  # MOD_DIR
}
InstallRTSubcomponents

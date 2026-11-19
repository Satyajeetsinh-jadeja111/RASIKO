#!/usr/bin/env bash
# Local debug build; no provider credentials, Firebase or release signing required.
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Serialize this project's mobile build helpers. Existing builds are never stopped.
if ! command -v flock >/dev/null 2>&1; then
  echo 'This Ubuntu build helper requires flock (util-linux).' >&2
  exit 2
fi
exec 9>"$project_root/mobile/rasiko_rider/.rasiko-build.lock"
if ! flock -n 9; then
  echo 'Another RASIKO mobile build helper is running; wait for it to finish.' >&2
  exit 2
fi
# Also notice a build started directly in Flutter/Gradle, including the current build.
if [[ -d /proc ]] && command -v pgrep >/dev/null 2>&1; then
  while IFS= read -r rider_build_pid; do
    rider_build_cwd="$(readlink "/proc/$rider_build_pid/cwd" 2>/dev/null || true)"
    case "$rider_build_cwd" in
      "$project_root/mobile/rasiko_rider"|"$project_root/mobile/rasiko_rider/android")
        echo 'A RASIKO Flutter/Gradle build is already running; it has been left untouched.' >&2
        exit 2
        ;;
    esac
  done < <(pgrep -f 'org.gradle.wrapper.GradleWrapperMain|flutter_tools.snapshot' || true)
fi
rider_priority=(nice -n 10)
if command -v ionice >/dev/null 2>&1; then
  rider_priority+=(ionice -c 2 -n 7)
fi
rider_tools="${RASIKO_BUILD_TOOLS:-$(dirname "$project_root")/.rasiko-tools}"
export JAVA_HOME="$rider_tools/jdk17"
export ANDROID_HOME="$rider_tools/android-sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
# The SDK CMake package includes Ninja, needed by Flutter native-assets builds.
if [[ -d "$ANDROID_HOME/cmake/3.22.1/bin" ]]; then
  export PATH="$ANDROID_HOME/cmake/3.22.1/bin:$PATH"
fi
if ! command -v ninja >/dev/null 2>&1; then
  echo 'Ninja is missing. Install Android SDK package cmake;3.22.1 before building.' >&2
  exit 2
fi
export PUB_CACHE="$rider_tools/pub-cache"
export CI=true FLUTTER_SUPPRESS_ANALYTICS=true
rider_api="${RASIKO_API_URL:-https://rasiko.in}"
rider_extra_defines=()
rider_artifact="rasiko-rider-debug.apk"
if [[ "${RASIKO_USB_LOCAL_TEST:-false}" == true && "$rider_api" == http://127.0.0.1:8001 ]]; then
  rider_extra_defines+=(--dart-define=RASIKO_USB_LOCAL_TEST=true)
  rider_artifact="rasiko-rider-usb-debug.apk"
elif [[ "$rider_api" != https://* ]]; then
  echo 'RASIKO_API_URL must be an HTTPS server origin.' >&2
  exit 2
fi
for rider_executable in "$JAVA_HOME/bin/java" "$rider_tools/flutter/bin/flutter" "$ANDROID_HOME/platform-tools/adb"; do
  if [[ ! -x "$rider_executable" ]]; then
    echo "Missing build tool: $rider_executable" >&2
    exit 2
  fi
done
cd "$project_root/mobile/rasiko_rider"
"${rider_priority[@]}" "$rider_tools/flutter/bin/flutter" pub get
"${rider_priority[@]}" "$rider_tools/flutter/bin/flutter" analyze --no-pub
"${rider_priority[@]}" "$rider_tools/flutter/bin/flutter" test --no-pub --concurrency=1
"${rider_priority[@]}" "$rider_tools/flutter/bin/flutter" build apk --debug --dart-define="RASIKO_API_URL=$rider_api" "${rider_extra_defines[@]}"
mkdir -p "$project_root/artifacts"
cp build/app/outputs/flutter-apk/app-debug.apk "$project_root/artifacts/$rider_artifact"
sha256sum "$project_root/artifacts/$rider_artifact"

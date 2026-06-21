#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK_ROOT="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-/opt/Android}}"
BUILD_TOOLS="${ANDROID_BUILD_TOOLS:-$SDK_ROOT/build-tools/35.0.0}"
PLATFORM="${ANDROID_PLATFORM:-$SDK_ROOT/platforms/android-35}"
ANDROID_JAR="$PLATFORM/android.jar"
MIN_SDK=23
TARGET_SDK=35

if [[ ! -f "$ANDROID_JAR" ]]; then
  echo "Missing Android platform jar: $ANDROID_JAR" >&2
  exit 1
fi

for tool in aapt2 d8 zipalign apksigner; do
  if [[ ! -x "$BUILD_TOOLS/$tool" ]]; then
    echo "Missing Android build tool: $BUILD_TOOLS/$tool" >&2
    exit 1
  fi
done

OUT="$ROOT/build"
GEN="$OUT/generated"
CLASSES="$OUT/classes"
DEX="$OUT/dex"
INTERMEDIATES="$OUT/intermediates"
APK_OUT="$OUT/outputs/apk/debug"
KEYSTORE="$OUT/debug.keystore"
UNSIGNED="$INTERMEDIATES/reload-ledger-pro-unsigned.apk"
DEXED="$INTERMEDIATES/reload-ledger-pro-dexed.apk"
ALIGNED="$INTERMEDIATES/reload-ledger-pro-aligned.apk"
FINAL_APK="$APK_OUT/reload-ledger-pro-debug.apk"
COMPILED_RES="$INTERMEDIATES/resources.zip"

rm -rf "$GEN" "$CLASSES" "$DEX" "$INTERMEDIATES" "$APK_OUT"
mkdir -p "$GEN" "$CLASSES" "$DEX" "$INTERMEDIATES" "$APK_OUT"

"$BUILD_TOOLS/aapt2" compile --dir "$ROOT/src/main/res" -o "$COMPILED_RES"
"$BUILD_TOOLS/aapt2" link \
  -I "$ANDROID_JAR" \
  --manifest "$ROOT/src/main/AndroidManifest.xml" \
  --java "$GEN" \
  --min-sdk-version "$MIN_SDK" \
  --target-sdk-version "$TARGET_SDK" \
  -o "$UNSIGNED" \
  "$COMPILED_RES"

mapfile -t JAVA_SOURCES < <(find "$ROOT/src/main/java" "$GEN" -name '*.java' -print)
javac -source 8 -target 8 -classpath "$ANDROID_JAR" -d "$CLASSES" "${JAVA_SOURCES[@]}"

mapfile -t CLASS_FILES < <(find "$CLASSES" -name '*.class' -print)
"$BUILD_TOOLS/d8" --min-api "$MIN_SDK" --lib "$ANDROID_JAR" --output "$DEX" "${CLASS_FILES[@]}"

cp "$UNSIGNED" "$DEXED"
zip -q -j "$DEXED" "$DEX/classes.dex"
"$BUILD_TOOLS/zipalign" -p -f 4 "$DEXED" "$ALIGNED"

if [[ ! -f "$KEYSTORE" ]]; then
  keytool -genkeypair \
    -keystore "$KEYSTORE" \
    -storepass android \
    -keypass android \
    -alias androiddebugkey \
    -keyalg RSA \
    -keysize 2048 \
    -validity 10000 \
    -dname "CN=Android Debug,O=Android,C=US" >/dev/null
fi

"$BUILD_TOOLS/apksigner" sign \
  --ks "$KEYSTORE" \
  --ks-pass pass:android \
  --key-pass pass:android \
  --out "$FINAL_APK" \
  "$ALIGNED"

"$BUILD_TOOLS/apksigner" verify "$FINAL_APK"
echo "$FINAL_APK"

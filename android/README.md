# Reloading Ledger Pro Android

This is a minimal Android WebView shell for Reloading Ledger Pro.

The debug build points to:

```text
https://reload.shanewiseman.co/readonly
```

The `/readonly` entrypoint sets the renderer session to read-only. Users can sign in and browse existing records, but the renderer hides mutation controls and rejects application write routes for that session.

Build a debug APK from the repository root:

```bash
android/build_debug.sh
```

The APK is written to:

```text
android/build/outputs/apk/debug/reload-ledger-pro-debug.apk
```

The build script uses only the local Android SDK command-line tools and does not download Gradle plugins.

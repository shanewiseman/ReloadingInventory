# Reloading Ledger Pro Android

This is a minimal Android WebView shell for Reloading Ledger Pro.

The debug build points to:

```text
https://reload.shanewiseman.co/readonly
```

The `/readonly` entrypoint sets the renderer session to a limited mobile mode. Users can sign in, browse existing records, update batch and container lifecycle state, assign batches to containers, and enter QA measurements, production loss, or reserved returns for batches under production. Other mutation controls are hidden and rejected by the renderer.

Build a debug APK from the repository root:

```bash
android/build_debug.sh
```

The APK is written to:

```text
android/build/outputs/apk/debug/reload-ledger-pro-debug.apk
```

The build script uses only the local Android SDK command-line tools and does not download Gradle plugins.

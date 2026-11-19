# Android

The Kotlin app calls the shared PAL/VHS Rust engine through JNI. Android Advanced uses the desktop parameter schema and visibility rules. The preview offers scrubbing, frame steps and playback. Preview and export use the same picture settings and timeline.

- Requires Android 10 or newer with ARM64 or ARMv7 support.
- Exports 720×576, 25 fps H.264 MP4 with a 4:3 display aspect to `Movies/PAL-VHS/`. AAC audio can pass through from the source.
- Keep the app in the foreground during export. Full RF processing speed depends on the phone.
- Follow the [local Android instructions](../docs/BUILD_AND_PUBLISH.md#android-local-build) or the [GitHub Actions instructions](../docs/BUILD_AND_PUBLISH.md#build-android-in-github-actions).

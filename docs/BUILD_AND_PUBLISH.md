# Build PAL VHS and publish it to GitHub

Start from the directory that contains `Cargo.toml`, `README.md`, `android/`, and the hidden `.github/` directory.

## Windows desktop

1. Install [Git for Windows](https://git-scm.com/install/windows), [Rust through rustup](https://rustup.rs/), and the [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) with **Desktop development with C++** and the Windows SDK.
2. Install x64 MSVC [GStreamer](https://gstreamer.freedesktop.org/download/) with development files. On GStreamer 1.28 or later choose the **devel** installation type. For earlier versions install the matching runtime and development packages. The Rust bindings need GStreamer 1.22 or later.
3. Install [FFmpeg](https://ffmpeg.org/download.html) with `libx264` support and add its `bin` directory to `PATH`. Open a new PowerShell window.
4. Point this PowerShell session at the actual GStreamer directory. Adjust the first line for your installation. Use GStreamer's `pkg-config` if available. For a separate `pkgconf` installation, set `PKG_CONFIG` to the path of its executable.

   ```powershell
   $gst = "C:\Program Files\gstreamer\1.0\msvc_x86_64"
   $env:Path = "$gst\bin;$env:Path"
   $env:PKG_CONFIG_PATH = "$gst\lib\pkgconfig"
   $env:PAL_VHS_GSTREAMER_ROOT = $gst
   $pkg = Get-Command pkg-config,pkgconf -ErrorAction SilentlyContinue | Select-Object -First 1
   if (-not $pkg) { throw "Add pkg-config or pkgconf to PATH first." }
   $env:PKG_CONFIG = $pkg.Source
   & $env:PKG_CONFIG --modversion gstreamer-1.0
   ffmpeg -version
   ffprobe -version
   ```

5. Use the MSVC Rust toolchain and build the desktop folder.

   ```powershell
   rustup toolchain install stable-x86_64-pc-windows-msvc
   $env:RUSTUP_TOOLCHAIN = "stable-x86_64-pc-windows-msvc"
   .\build_windows.ps1
   & '.\dist\PAL-VHS\Launch PAL VHS.cmd'
   ```

6. Open a sample MP4, select a tape preset, scrub the preview, and export a short clip. The release folder has this layout:

   ```text
   dist/PAL-VHS/
   ├── Launch PAL VHS.cmd
   ├── README.md
   ├── docs/
   └── app/
       ├── PAL-VHS.exe
       ├── GStreamer DLLs
       ├── lib/gstreamer-1.0/
       └── libexec/gstreamer-1.0/
   ```

   Zip the entire folder. To run the release, extract the whole ZIP and double-click **Launch PAL VHS.cmd**.

   ```powershell
   Compress-Archive -Path ".\dist\PAL-VHS\*" -DestinationPath ".\dist\PAL-VHS-Windows-x64.zip"
   ```

The executable is linked against the GStreamer SDK. Use its matching DLLs and plugins together. Windows export uses the FFmpeg tools on `PATH`.

## Android local build

1. Install a [JDK 17](https://adoptium.net/temurin/releases/?version=17), [Android Studio](https://developer.android.com/studio), and [Rust](https://rustup.rs/). In Android Studio's SDK Manager install **Android SDK Platform 35**, **Build-Tools 35.0.0**, **Platform-Tools** for ADB, and **NDK (Side by side) 28.0.13004108**. Enable **Show Package Details** to choose the NDK version.
2. In a terminal at the project root, set the JDK and SDK locations. Replace the example paths with your own. The SDK is the same directory shown at the top of SDK Manager.

   ```powershell
   $env:JAVA_HOME = "C:\Path\To\jdk-17"
   $env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
   $env:ANDROID_NDK_HOME = "$env:ANDROID_HOME\ndk\28.0.13004108"
   $env:Path = "$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:Path"
   rustup target add aarch64-linux-android armv7-linux-androideabi
   cargo install cargo-ndk --version 4.1.2 --locked
   cargo ndk --version
   ```

3. Build using the project's Gradle wrapper. On macOS or Linux use `bash ./gradlew` in place of `.\gradlew.bat`.

   ```powershell
   Set-Location android
   .\gradlew.bat :app:assembleDebug
   ```

4. Install `app/build/outputs/apk/debug/app-debug.apk` from this directory on an ARM64 or ARMv7 device running Android 10 or newer. For a device with USB debugging enabled, use `adb install -r app/build/outputs/apk/debug/app-debug.apk`. Open a short clip, try **Advanced settings**, preview a frame, and check that export appears in **Movies → PAL-VHS**.
5. Verify the debug package signature. Android app updates require the same signing key as the installed copy.

   ```powershell
   & "$env:ANDROID_HOME\build-tools\35.0.0\apksigner.bat" verify --verbose app/build/outputs/apk/debug/app-debug.apk
   ```

Gradle downloads its pinned 8.9 distribution on the first run. The build creates the two Rust libraries using NDK API 29 and puts them in the APK. Generated libraries, local SDK configuration and build products are ignored by Git.

## Publish the repository

1. Sign in to GitHub and create an empty repository. Leave the **Add a README**, **Add .gitignore** and **Choose a license** initialization options unchecked when importing these files. Copy the new repository's HTTPS URL.
2. From the extracted project root, run the following. Replace `OWNER/pal-vhs` with your repository. If Git requests your name or email, configure those first and retry the commit.

   ```powershell
   git init -b main
   git add .
   git status --short
   git commit -m "Import PAL VHS for Windows and Android"
   git remote add origin https://github.com/OWNER/pal-vhs.git
   git push -u origin main
   ```

3. Authenticate in the browser or with a Git credential helper when prompted. Refresh the repository in GitHub and check that the README image and `.github/workflows/android.yml` are visible. [GitHub's import documentation](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)

## Build Android in GitHub Actions

1. Open the repository's **Actions** tab and select **Android APK**. The workflow starts after a push to `main`, for pull requests, and for version tags. To start it manually, choose **Run workflow**, select `main`, and confirm.
2. Open the run. Check that **Build debug APK** and **Verify APK signature** finish successfully.
3. Scroll to **Artifacts** and download **pal-vhs-debug-apk**. Extract the downloaded ZIP to get `app-debug.apk`. Test that APK on a phone before sharing it. [GitHub's artifact download guide](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)

## Create a GitHub Release

1. From your tested commit, create and push a version tag. Change the example tag if it already exists.

   ```powershell
   git tag -a v0.2.0 -m "PAL VHS 0.2.0"
   git push origin v0.2.0
   ```

2. Download the Android APK from the tagged workflow. Build the Windows ZIP from the same commit using the Windows steps above.
3. On GitHub open **Releases → Draft a new release**, select that tag, and attach `PAL-VHS-Windows-x64.zip` and the extracted APK. Describe the platform requirements and label the Android asset as debug-signed. Select **Publish release** when ready.

## Refresh the app icons

The cassette artwork and existing platform resources are checked in. To edit the design, install Pillow and run `python tools/make_icons.py`. To rebuild the Windows icon resource files, use LLVM's `llvm-rc` and `llvm-cvtres` from `assets/icons/`:

```powershell
llvm-rc /fo pal-vhs.res pal-vhs.rc
llvm-cvtres /machine:X64 /out:pal-vhs-x86_64.o pal-vhs.res
llvm-cvtres /machine:X86 /out:pal-vhs-x86.o pal-vhs.res
llvm-cvtres /machine:ARM64 /out:pal-vhs-aarch64.o pal-vhs.res
```

The Rust desktop build picks the Windows resource for its toolchain and uses the PNG as the window icon. Android uses the adaptive icon in `android/app/src/main/res/`.

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.palvhs.app"
    compileSdk = 35
    buildToolsVersion = "35.0.0"
    ndkVersion = "28.0.13004108"
    defaultConfig {
        applicationId = "com.palvhs.app"
        minSdk = 29
        targetSdk = 35
        versionCode = 2
        versionName = "0.2"
        ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
    }
    buildTypes {
        release { isMinifyEnabled = false }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

// Build the Rust engine for Android with cargo-ndk before packaging.
// Needs: `cargo install cargo-ndk`, the Android NDK (ANDROID_NDK_HOME) and
// `rustup target add aarch64-linux-android armv7-linux-androideabi`.
val cargoNdk by tasks.registering(Exec::class) {
    workingDir = file("../rust")
    commandLine(
        "cargo", "ndk",
        "-t", "arm64-v8a", "-t", "armeabi-v7a",
        "-p", "29",
        "-o", file("src/main/jniLibs").absolutePath,
        "build", "--release", "--locked",
    )
}
tasks.matching { it.name == "preBuild" }.configureEach { dependsOn(cargoNdk) }

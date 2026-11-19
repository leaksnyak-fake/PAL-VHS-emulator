package com.palvhs.app

/** Thin wrapper over the Rust engine (android/rust). Errors surface as RuntimeException. */
object Native {
    init { System.loadLibrary("palvhs") }

    @JvmStatic external fun nativeCreate(preset: String, overridesJson: String): Long
    @JvmStatic external fun nativeDestroy(handle: Long)
    @JvmStatic external fun nativeAspect(handle: Long): String
    @JvmStatic external fun nativePresets(): String
    @JvmStatic external fun nativeSchema(): String
    @JvmStatic external fun nativeControlState(preset: String, overridesJson: String): String
    /** I420 frame of any (even) size -> 720x576 RGB24 canvas. */
    @JvmStatic external fun nativeFit(i420: ByteArray, w: Int, h: Int, rotation: Int, aspect: String, bt709: Boolean): ByteArray
    /** Returns RGB24 for preview or packed BT.601 I420 for export. */
    @JvmStatic external fun nativeRender(
        handle: Long, canvas: ByteArray, secondCanvas: ByteArray?, frameIdx: Long, forExport: Boolean,
    ): ByteArray

    const val W = 720
    const val H = 576
}

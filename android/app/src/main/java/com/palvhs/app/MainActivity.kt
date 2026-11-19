package com.palvhs.app

import android.app.Activity
import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.MediaStore
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.Spinner
import android.widget.Switch
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Locale
import java.util.concurrent.CancellationException
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : Activity() {
    private data class Settings(val uri: Uri, val preset: String, val overrides: String, val temporal: Boolean)
    private data class PreviewRequest(val settings: Settings, val index: Long, val generation: Long)

    private val io = Executors.newSingleThreadExecutor()
    private val ui = Handler(Looper.getMainLooper())
    private val cancel = AtomicBoolean(false)
    private var video: Uri? = null
    private var totalFrames = 0
    private var busy = false
    private var generation = 0L
    private var previewRunning = false
    private var playing = false
    private var pending: PreviewRequest? = null
    private val previewTick = Runnable { launchPreview() }

    // Owned by the I/O executor.
    private var previewSettings: Settings? = null
    private var previewRenderer: Exporter.Preview? = null

    private lateinit var presets: List<String>
    private var preset = ""
    private var state = JSONObject()
    private val macroOverrides = JSONObject()
    private val advancedOverrides = JSONObject()
    private val macroBars = mutableMapOf<String, SeekBar>()
    private lateinit var easyControls: LinearLayout
    private lateinit var advancedControls: AdvancedControls
    private lateinit var mode: Switch
    private lateinit var presetPicker: Spinner
    private lateinit var pickBtn: Button
    private lateinit var fileText: TextView
    private lateinit var preview: ImageView
    private lateinit var posBar: SeekBar
    private lateinit var frameText: TextView
    private lateinit var prevBtn: Button
    private lateinit var playBtn: Button
    private lateinit var nextBtn: Button
    private lateinit var status: TextView
    private lateinit var progress: ProgressBar
    private lateinit var exportBtn: Button
    private lateinit var cancelBtn: Button

    private fun dp(size: Int) = (size * resources.displayMetrics.density).toInt()
    private fun label(text: String) = TextView(this).apply {
        this.text = text
        setPadding(0, dp(12), 0, dp(2))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val names = JSONArray(Native.nativePresets())
        presets = List(names.length()) { names.getString(it) }
        val default = presets.indexOf("PAL VHS / SP - home recording").coerceAtLeast(0)
        preset = presets.getOrElse(default) { "" }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(24), dp(16), dp(16))
        }
        setContentView(ScrollView(this).apply { addView(root) })

        pickBtn = Button(this).apply {
            text = "Choose video"
            setOnClickListener {
                startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "video/*"
                }, REQ_VIDEO)
            }
        }
        root.addView(pickBtn)
        fileText = TextView(this).apply { text = "No video selected" }
        root.addView(fileText)

        preview = ImageView(this).apply {
            scaleType = ImageView.ScaleType.FIT_XY
            setBackgroundColor(0xFF000000.toInt())
            contentDescription = "Processed PAL VHS preview"
        }
        root.addView(preview, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(200)))
        root.addOnLayoutChangeListener { _, left, _, right, _, _, _, _, _ ->
            val height = (right - left - root.paddingLeft - root.paddingRight) * 3 / 4
            if (height > 0 && preview.layoutParams.height != height) {
                preview.layoutParams = preview.layoutParams.apply { this.height = height }
            }
        }
        frameText = label("Preview")
        root.addView(frameText)
        posBar = SeekBar(this).apply {
            max = 0
            contentDescription = "Preview frame position"
            setOnSeekBarChangeListener(onSeek {
                setPlaying(false)
                queuePreview()
            })
        }
        root.addView(posBar)
        val playback = LinearLayout(this)
        prevBtn = Button(this).apply {
            text = "Previous"
            contentDescription = "Previous frame"
            setOnClickListener { step(-1) }
        }
        nextBtn = Button(this).apply {
            text = "Next"
            contentDescription = "Next frame"
            setOnClickListener { step(1) }
        }
        playBtn = Button(this).apply {
            text = "Play"
            setOnClickListener {
                setPlaying(!playing)
                if (playing) {
                    if (posBar.progress == posBar.max) posBar.progress = 0
                    queuePreview(delayMs = 0)
                }
            }
        }
        playback.addView(prevBtn, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        playback.addView(playBtn, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        playback.addView(nextBtn, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        root.addView(playback)
        status = TextView(this)
        root.addView(status)

        root.addView(label("Tape preset"))
        presetPicker = Spinner(this).apply {
            adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_dropdown_item, presets)
            setSelection(default)
            onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                    if (preset != presets[pos]) {
                        preset = presets[pos]
                        clear(macroOverrides)
                        clear(advancedOverrides)
                        refreshSettings()
                    }
                }
                override fun onNothingSelected(p: AdapterView<*>?) {}
            }
        }
        root.addView(presetPicker)

        mode = Switch(this).apply { text = "Advanced settings" }
        root.addView(mode)
        easyControls = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        for ((key, title) in listOf("wear" to "Tape wear", "colour" to "Colour bleed",
            "unstable" to "Wobble", "smear" to "Tracking smear", "crease" to "Crease")) {
            easyControls.addView(label(title))
            val bar = SeekBar(this).apply {
                max = 100
                contentDescription = title
                setOnSeekBarChangeListener(onSeek { value ->
                    val keys = state.getJSONObject("macros").getJSONObject(key).getJSONArray("keys")
                    for (i in 0 until keys.length()) advancedOverrides.remove(keys.getString(i))
                    macroOverrides.put(key, value)
                    refreshSettings()
                })
            }
            macroBars[key] = bar
            easyControls.addView(bar)
        }
        root.addView(easyControls)
        advancedControls = AdvancedControls(this, JSONArray(Native.nativeSchema())) { key, value ->
            advancedOverrides.put(key, value)
            val current = state.getJSONObject("values")
            // Keep the last edited height authoritative when native settings are replayed.
            if (key == "wr_hmin" && (value as Number).toDouble() > current.getDouble("wr_hmax")) {
                advancedOverrides.put("wr_hmax", value)
            }
            if (key == "wr_hmax" && (value as Number).toDouble() < current.getDouble("wr_hmin")) {
                advancedOverrides.put("wr_hmin", value)
            }
            refreshSettings()
        }
        root.addView(advancedControls)
        mode.setOnCheckedChangeListener { _, _ -> refreshControls() }

        exportBtn = Button(this).apply {
            text = "Export video"
            setOnClickListener { startExport() }
        }
        cancelBtn = Button(this).apply {
            text = "Cancel export"
            isEnabled = false
            setOnClickListener { cancel.set(true) }
        }
        root.addView(exportBtn)
        root.addView(cancelBtn)
        progress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            visibility = View.GONE
        }
        root.addView(progress)
        refreshSettings()
        updateButtons()
    }

    private fun onSeek(change: (Int) -> Unit) = object : SeekBar.OnSeekBarChangeListener {
        override fun onProgressChanged(bar: SeekBar?, value: Int, fromUser: Boolean) {
            if (fromUser) change(value)
        }
        override fun onStartTrackingTouch(bar: SeekBar?) {}
        override fun onStopTrackingTouch(bar: SeekBar?) {}
    }

    private fun clear(json: JSONObject) {
        val keys = json.keys()
        while (keys.hasNext()) { keys.next(); keys.remove() }
    }

    private fun overrides(): String = JSONObject(advancedOverrides.toString())
        .put("macros", macroOverrides).toString()

    private fun refreshSettings() {
        setPlaying(false)
        state = JSONObject(Native.nativeControlState(preset, overrides()))
        refreshControls()
        queuePreview()
    }

    private fun refreshControls() {
        val values = state.getJSONObject("values")
        easyControls.visibility = if (mode.isChecked || values.getBoolean("bypass_tape")) View.GONE else View.VISIBLE
        advancedControls.visibility = if (mode.isChecked) View.VISIBLE else View.GONE
        if (mode.isChecked) advancedControls.refresh(state)
        val macros = state.getJSONObject("macros")
        for ((key, bar) in macroBars) bar.progress = macros.getJSONObject(key).getInt("position")
    }

    private fun settings(): Settings? = video?.let {
        val values = state.getJSONObject("values")
        val temporal = values.getString("field_mode") == "temporal" &&
            values.getString("export_fields") != "field 1 only"
        Settings(it, preset, overrides(), temporal)
    }

    private fun exporter(settings: Settings) =
        Exporter(applicationContext, settings.uri, settings.preset, settings.overrides, settings.temporal)

    private fun closePreview() {
        val renderer = previewRenderer
        previewRenderer = null
        previewSettings = null
        renderer?.close()
    }

    private fun invalidatePreview() {
        setPlaying(false)
        generation++
        pending = null
        ui.removeCallbacks(previewTick)
    }

    private fun updateButtons() {
        pickBtn.isEnabled = !busy
        if (presetPicker.isEnabled == busy) {
            presetPicker.isEnabled = !busy
            mode.isEnabled = !busy
            enableControls(easyControls, !busy)
            enableControls(advancedControls, !busy)
        }
        exportBtn.isEnabled = !busy && totalFrames > 0
        posBar.isEnabled = !busy && totalFrames > 1
        prevBtn.isEnabled = posBar.isEnabled && posBar.progress > 0
        playBtn.isEnabled = posBar.isEnabled
        nextBtn.isEnabled = posBar.isEnabled && posBar.progress < posBar.max
    }

    private fun enableControls(view: View, enabled: Boolean) {
        view.isEnabled = enabled
        if (view is ViewGroup) {
            for (i in 0 until view.childCount) enableControls(view.getChildAt(i), enabled)
        }
    }

    private fun step(delta: Int) {
        setPlaying(false)
        posBar.progress = (posBar.progress + delta).coerceIn(0, posBar.max)
        queuePreview(delayMs = 0)
    }

    private fun setPlaying(enabled: Boolean) {
        playing = enabled
        playBtn.text = if (enabled) "Pause" else "Play"
    }

    private fun queuePreview(delayMs: Long = 160) {
        if (busy || totalFrames == 0) return
        val settings = settings() ?: return
        val index = posBar.progress.toLong()
        val seconds = index * Exporter.FRAME_US / 1_000_000.0
        frameText.text = String.format(Locale.ROOT, "Frame %d / %d  ·  %.2f s", index + 1, totalFrames, seconds)
        updateButtons()
        pending = PreviewRequest(settings, index, ++generation)
        ui.removeCallbacks(previewTick)
        ui.postDelayed(previewTick, delayMs)
    }

    private fun launchPreview() {
        if (previewRunning || busy) return
        val request = pending ?: return
        pending = null
        previewRunning = true
        status.text = "Rendering preview…"
        val startedAt = SystemClock.elapsedRealtime()
        io.execute {
            val result = runCatching {
                if (previewSettings != request.settings) {
                    closePreview()
                    previewRenderer = exporter(request.settings).openPreview()
                    previewSettings = request.settings
                }
                checkNotNull(previewRenderer).frame(request.index)
            }
            if (result.isFailure) runCatching { closePreview() }
            ui.post {
                previewRunning = false
                if (!isDestroyed && request.generation == generation) {
                    result.onSuccess {
                        preview.setImageBitmap(it)
                        status.text = ""
                        if (playing && posBar.progress < posBar.max) {
                            posBar.progress++
                            val elapsed = SystemClock.elapsedRealtime() - startedAt
                            queuePreview(delayMs = (Exporter.FRAME_US / 1000 - elapsed).coerceAtLeast(0))
                            return@post
                        }
                        setPlaying(false)
                    }.onFailure {
                        setPlaying(false)
                        status.text = "Preview failed: ${it.message}"
                    }
                }
                if (pending != null) launchPreview()
            }
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ_VIDEO || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        invalidatePreview()
        video = uri
        totalFrames = 0
        fileText.text = uri.lastPathSegment ?: uri.toString()
        preview.setImageDrawable(null)
        frameText.text = "Preview"
        busy = true
        status.text = "Reading video…"
        updateButtons()
        val source = exporter(checkNotNull(settings()))
        io.execute {
            val result = runCatching {
                closePreview()
                Exporter.frameCount(source.durationUs())
            }
            ui.post {
                if (!isDestroyed) {
                    busy = false
                    result.onSuccess {
                        totalFrames = it
                        posBar.max = it - 1
                        posBar.progress = 0
                        queuePreview(delayMs = 0)
                    }.onFailure { status.text = "Could not open video: ${it.message}" }
                    updateButtons()
                }
            }
        }
    }

    private fun startExport() {
        if (busy || totalFrames == 0) return
        val settings = settings() ?: return
        invalidatePreview()
        cancel.set(false)
        busy = true
        updateButtons()
        cancelBtn.isEnabled = true
        progress.progress = 0
        progress.visibility = View.VISIBLE
        status.text = "Starting export…"
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        io.execute {
            val result = runCatching {
                closePreview()
                if (cancel.get()) throw CancellationException()
                val out = File.createTempFile("pal-vhs-", ".mp4", cacheDir)
                try {
                    val threads = (Runtime.getRuntime().availableProcessors() / 2).coerceIn(1, 4)
                    val start = SystemClock.elapsedRealtime()
                    exporter(settings).export(out, threads, cancel) { done, total ->
                        val elapsed = (SystemClock.elapsedRealtime() - start) / 1000.0
                        val eta = (elapsed / done * (total - done)).toInt()
                        ui.post {
                            if (!isDestroyed) {
                                progress.max = total
                                progress.progress = done
                                status.text = "Exporting $done / $total frames  ·  ${eta / 60}m ${eta % 60}s left"
                            }
                        }
                    }
                    if (cancel.get()) throw CancellationException()
                    saveVideo(out)
                } finally {
                    out.delete()
                }
            }
            ui.post {
                if (!isDestroyed) {
                    busy = false
                    updateButtons()
                    cancelBtn.isEnabled = false
                    window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    status.text = result.fold(
                        onSuccess = { "Saved to Movies/PAL-VHS/$it" },
                        onFailure = {
                            if (it is CancellationException || cancel.get()) "Export cancelled"
                            else "Export failed: ${it.message}"
                        },
                    )
                }
            }
        }
    }

    private fun saveVideo(file: File): String {
        val name = "pal-vhs-${System.currentTimeMillis()}.mp4"
        val values = ContentValues().apply {
            put(MediaStore.Video.Media.DISPLAY_NAME, name)
            put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
            put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/PAL-VHS")
            put(MediaStore.Video.Media.IS_PENDING, 1)
        }
        val dest = contentResolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
            ?: throw IllegalStateException("Cannot create output file")
        try {
            val stream = contentResolver.openOutputStream(dest) ?: error("Cannot open output file")
            stream.use { output -> file.inputStream().use { input -> input.copyTo(output) } }
            if (cancel.get()) throw CancellationException()
            val ready = ContentValues().apply { put(MediaStore.Video.Media.IS_PENDING, 0) }
            check(contentResolver.update(dest, ready, null, null) == 1) { "Cannot publish output file" }
            return name
        } catch (e: Throwable) {
            contentResolver.delete(dest, null, null)
            throw e
        }
    }

    override fun onDestroy() {
        cancel.set(true)
        invalidatePreview()
        io.execute { runCatching { closePreview() } }
        io.shutdown()
        super.onDestroy()
    }

    override fun onStop() {
        setPlaying(false)
        super.onStop()
    }

    companion object { private const val REQ_VIDEO = 1 }
}

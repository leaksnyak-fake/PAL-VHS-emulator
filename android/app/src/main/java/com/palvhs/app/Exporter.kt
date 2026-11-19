package com.palvhs.app

import android.content.Context
import android.graphics.Bitmap
import android.media.Image
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import android.net.Uri
import java.io.File
import java.nio.ByteBuffer
import java.util.concurrent.Callable
import java.util.concurrent.CancellationException
import java.util.concurrent.Executors
import java.util.concurrent.Future
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** A decoded source frame as packed I420 at its native (cropped, even) size. */
internal class SourceFrame(val id: Long, val ptsUs: Long, val width: Int, val height: Int, val i420: ByteArray)

/** Opens a video with MediaExtractor + MediaCodec and yields I420 frames in display order. */
internal class VideoReader(ctx: Context, uri: Uri) : AutoCloseable {
    private val extractor = MediaExtractor()
    private val codec: MediaCodec
    private val info = MediaCodec.BufferInfo()
    private var inputDone = false
    private var outputDone = false
    private var nextFrameId = 0L

    val rotation: Int
    val durationUs: Long
    private val colorStandard: Int

    init {
        var openedCodec: MediaCodec? = null
        try {
            extractor.setDataSource(ctx, uri, null)
            val track = (0 until extractor.trackCount).firstOrNull {
                extractor.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("video/") == true
            } ?: throw IllegalArgumentException("No video track found")
            extractor.selectTrack(track)
            val fmt = extractor.getTrackFormat(track)
            rotation = fmt.getInteger(MediaFormat.KEY_ROTATION, 0)
            durationUs = if (fmt.containsKey(MediaFormat.KEY_DURATION)) fmt.getLong(MediaFormat.KEY_DURATION) else 0L
            colorStandard = fmt.getInteger(MediaFormat.KEY_COLOR_STANDARD, 0)
            fmt.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible)
            codec = MediaCodec.createDecoderByType(fmt.getString(MediaFormat.KEY_MIME)!!)
            openedCodec = codec
            codec.configure(fmt, null, null, 0)
            codec.start()
        } catch (e: Throwable) {
            try { openedCodec?.release() } finally { extractor.release() }
            throw e
        }
    }

    fun isBt709(frame: SourceFrame): Boolean = when (colorStandard) {
        MediaFormat.COLOR_STANDARD_BT709 -> true
        MediaFormat.COLOR_STANDARD_BT601_PAL, MediaFormat.COLOR_STANDARD_BT601_NTSC -> false
        else -> frame.height >= 720
    }

    fun seekTo(timeUs: Long) {
        extractor.seekTo(timeUs, MediaExtractor.SEEK_TO_PREVIOUS_SYNC)
        codec.flush()
        inputDone = false
        outputDone = false
    }

    /** Next frame in presentation order, or null at the end of the stream. */
    fun next(cancel: () -> Boolean = { false }): SourceFrame? {
        while (!outputDone) {
            if (cancel()) throw CancellationException()
            if (!inputDone) {
                val i = codec.dequeueInputBuffer(0)
                if (i >= 0) {
                    val n = extractor.readSampleData(codec.getInputBuffer(i)!!, 0)
                    if (n < 0) {
                        codec.queueInputBuffer(i, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                        inputDone = true
                    } else {
                        codec.queueInputBuffer(i, 0, n, extractor.sampleTime, 0)
                        extractor.advance()
                    }
                }
            }
            val o = codec.dequeueOutputBuffer(info, 10_000)
            if (o >= 0) {
                try {
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) outputDone = true
                    if (info.size > 0) {
                        codec.getOutputImage(o)?.use { return imageToI420(it, info.presentationTimeUs) }
                    }
                } finally {
                    codec.releaseOutputBuffer(o, false)
                }
            }
        }
        return null
    }

    override fun close() {
        try { codec.stop() } catch (_: Exception) {}
        try { codec.release() } finally { extractor.release() }
    }

    private inline fun <T> Image.use(block: (Image) -> T): T = try { block(this) } finally { close() }

    private fun imageToI420(img: Image, ptsUs: Long): SourceFrame {
        val r = img.cropRect
        val w = r.width() and 1.inv()
        val h = r.height() and 1.inv()
        val out = ByteArray(w * h * 3 / 2)
        var off = 0
        for (p in 0 until 3) {
            val plane = img.planes[p]
            val pw = if (p == 0) w else w / 2
            val ph = if (p == 0) h else h / 2
            val left = if (p == 0) r.left else r.left / 2
            val top = if (p == 0) r.top else r.top / 2
            val buf = plane.buffer
            val rs = plane.rowStride
            val ps = plane.pixelStride
            val row = ByteArray(if (ps == 1) pw else (pw - 1) * ps + 1)
            for (y in 0 until ph) {
                buf.position((top + y) * rs + left * ps)
                if (ps == 1) {
                    buf.get(out, off, pw)
                } else {
                    buf.get(row)
                    for (x in 0 until pw) out[off + x] = row[x * ps]
                }
                off += pw
            }
        }
        return SourceFrame(nextFrameId++, ptsUs, w, h, out)
    }
}

/** Renders the PAL/VHS effect over a whole clip and writes an H.264/AAC MP4. */
class Exporter(
    private val ctx: Context,
    private val uri: Uri,
    private val preset: String,
    private val overridesJson: String,
    private val temporal: Boolean,
) {
    /** Samples decoded frames against the same 25 fps grid for preview and export. */
    private class Timeline(private val reader: VideoReader, private val aspect: String) {
        private var before: SourceFrame? = null
        private var after: SourceFrame? = reader.next() ?: throw IllegalStateException("The video has no frames")
        private val originUs = checkNotNull(after).ptsUs
        private val canvases = LinkedHashMap<Long, ByteArray>()

        fun seek(index: Long) {
            reader.seekTo(originUs + index * FRAME_US)
            before = null
            after = reader.next()
            if (after == null) {
                reader.seekTo(originUs)
                after = reader.next() ?: throw IllegalStateException("The video has no frames")
            }
            canvases.clear()
        }

        private fun canvasAt(offsetUs: Long, cancel: () -> Boolean): ByteArray {
            val time = originUs + offsetUs
            while (after != null && after!!.ptsUs <= time) {
                before = after
                after = reader.next(cancel)
            }
            val prev = before
            val next = after
            val frame = when {
                prev == null -> checkNotNull(next)
                next == null || time - prev.ptsUs <= next.ptsUs - time -> prev
                else -> next
            }
            return canvases.getOrPut(frame.id) {
                if (canvases.size == 2) canvases.remove(canvases.keys.first())
                Native.nativeFit(frame.i420, frame.width, frame.height, reader.rotation, aspect, reader.isBt709(frame))
            }
        }

        fun renderInput(index: Long, temporal: Boolean, cancel: () -> Boolean = { false }): Pair<ByteArray, ByteArray?> {
            val time = index * FRAME_US
            val first = canvasAt(time, cancel)
            val second = if (temporal) canvasAt(time + FRAME_US / 2, cancel) else null
            return first to second?.takeUnless { it === first }
        }
    }

    fun openPreview() = Preview()
    fun durationUs(): Long = VideoReader(ctx, uri).use { it.durationUs }

    inner class Preview : AutoCloseable {
        private val handle = Native.nativeCreate(preset, overridesJson)
        private val reader: VideoReader
        private val timeline: Timeline
        private var lastIndex = -1L
        private var lastBitmap: Bitmap? = null

        init {
            var openedReader: VideoReader? = null
            try {
                reader = VideoReader(ctx, uri)
                openedReader = reader
                timeline = Timeline(reader, Native.nativeAspect(handle))
            } catch (e: Throwable) {
                try { openedReader?.close() } finally { Native.nativeDestroy(handle) }
                throw e
            }
        }

        fun frame(index: Long): Bitmap {
            if (lastIndex == index) return checkNotNull(lastBitmap)
            val sequential = index > lastIndex && index - lastIndex <= 12
            if (!sequential) timeline.seek(index)
            val (first, second) = timeline.renderInput(index, temporal)
            return rgbToBitmap(Native.nativeRender(handle, first, second, index, false)).also {
                lastIndex = index
                lastBitmap = it
            }
        }

        override fun close() {
            try { reader.close() } finally { Native.nativeDestroy(handle) }
        }
    }

    /** Render and encode in timestamp order using a bounded queue of full-accuracy frames. */
    fun export(out: File, threads: Int, cancel: AtomicBoolean, progress: (Int, Int) -> Unit) {
        require(threads > 0)
        val pool = Executors.newFixedThreadPool(threads)
        var handle = 0L
        var muxer: MediaMuxer? = null
        var encoder: MediaCodec? = null
        var muxStarted = false
        try {
            val session = Native.nativeCreate(preset, overridesJson).also { handle = it }
            VideoReader(ctx, uri).use { reader ->
                val timeline = Timeline(reader, Native.nativeAspect(session))
                val total = frameCount(reader.durationUs)

                val enc = createEncoder().also { encoder = it }
                val mux = MediaMuxer(out.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4).also { muxer = it }
                var videoTrack = -1
                val info = MediaCodec.BufferInfo()

                fun drain(endOfStream: Boolean) {
                    while (true) {
                        if (cancel.get()) throw CancellationException()
                        val o = enc.dequeueOutputBuffer(info, if (endOfStream) 10_000 else 0)
                        when {
                            o == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                                val format = enc.outputFormat.apply {
                                    // 720×576 storage is displayed as 768×576.
                                    setInteger("sar-width", 16)
                                    setInteger("sar-height", 15)
                                }
                                videoTrack = mux.addTrack(format)
                                val audio = prepareAudio(mux)
                                mux.start()
                                muxStarted = true
                                audio?.let { writeAudio(mux, it, total * FRAME_US) }
                            }
                            o >= 0 -> {
                                val buf = enc.getOutputBuffer(o)!!
                                if (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0) info.size = 0
                                if (info.size > 0 && muxStarted) {
                                    buf.position(info.offset); buf.limit(info.offset + info.size)
                                    mux.writeSampleData(videoTrack, buf, info)
                                }
                                enc.releaseOutputBuffer(o, false)
                                if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) return
                            }
                            else -> if (!endOfStream) return
                        }
                    }
                }

                fun inputBuffer(): Int {
                    var idx = enc.dequeueInputBuffer(10_000)
                    while (idx < 0) {
                        drain(false)
                        idx = enc.dequeueInputBuffer(10_000)
                    }
                    if (cancel.get()) throw CancellationException()
                    return idx
                }

                fun feed(i420: ByteArray, ptsUs: Long) {
                    val idx = inputBuffer()
                    fillImage(enc.getInputImage(idx)!!, i420)
                    enc.queueInputBuffer(idx, 0, i420.size, ptsUs, 0)
                    drain(false)
                }

                val pending = ArrayDeque<Future<ByteArray>>()
                var submitted = 0
                var done = 0
                while (done < total) {
                    if (cancel.get()) throw CancellationException()
                    while (submitted < total && pending.size < threads + 1) {
                        if (cancel.get()) throw CancellationException()
                        val index = submitted.toLong()
                        val (first, second) = timeline.renderInput(index, temporal, cancel::get)
                        pending.addLast(pool.submit(Callable {
                            if (cancel.get()) throw CancellationException()
                            Native.nativeRender(session, first, second, index, true)
                        }))
                        submitted++
                    }
                    val i420 = pending.removeFirst().get()
                    if (cancel.get()) throw CancellationException()
                    feed(i420, done * FRAME_US)
                    done++
                    progress(done, total)
                }
                enc.queueInputBuffer(inputBuffer(), 0, 0, total * FRAME_US, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                drain(true)
                check(muxStarted) { "The encoder produced no output" }
                mux.stop()
                muxStarted = false
            }
        } finally {
            pool.shutdownNow()
            // JNI workers finish their current frame before the shared engine is released.
            var interrupted = false
            while (!pool.isTerminated) {
                try {
                    pool.awaitTermination(1, TimeUnit.SECONDS)
                } catch (_: InterruptedException) {
                    interrupted = true
                }
            }
            if (interrupted) Thread.currentThread().interrupt()
            Native.nativeDestroy(handle)
            try { encoder?.stop() } catch (_: Exception) {}
            encoder?.release()
            try { if (muxStarted) muxer?.stop() } catch (_: Exception) {}
            muxer?.release()
        }
    }

    private fun createEncoder(): MediaCodec {
        fun format(high: Boolean) = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, Native.W, Native.H).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible)
            setInteger(MediaFormat.KEY_BIT_RATE, 10_000_000)
            setInteger(MediaFormat.KEY_FRAME_RATE, 25)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
            setInteger(MediaFormat.KEY_COLOR_RANGE, MediaFormat.COLOR_RANGE_LIMITED)
            setInteger(MediaFormat.KEY_COLOR_STANDARD, MediaFormat.COLOR_STANDARD_BT601_PAL)
            if (high) setInteger(MediaFormat.KEY_PROFILE, MediaCodecInfo.CodecProfileLevel.AVCProfileHigh)
        }
        for (high in listOf(true, false)) {
            val c = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
            try {
                c.configure(format(high), null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
                c.start()
                return c
            } catch (e: Exception) {
                c.release()
                if (!high) throw e
            }
        }
        throw IllegalStateException("No H.264 encoder available")
    }

    private class AudioCopy(val extractor: MediaExtractor, val track: Int)

    /** Register the source's AAC track with the muxer (other audio codecs are skipped). */
    private fun prepareAudio(mux: MediaMuxer): AudioCopy? {
        val ax = MediaExtractor()
        try {
            ax.setDataSource(ctx, uri, null)
            val t = (0 until ax.trackCount).firstOrNull {
                ax.getTrackFormat(it).getString(MediaFormat.KEY_MIME) == MediaFormat.MIMETYPE_AUDIO_AAC
            }
            if (t == null) { ax.release(); return null }
            ax.selectTrack(t)
            return AudioCopy(ax, mux.addTrack(ax.getTrackFormat(t)))
        } catch (e: Exception) {
            ax.release()
            return null
        }
    }

    /** Copy audio samples unchanged, up to the length of the exported video. */
    private fun writeAudio(mux: MediaMuxer, a: AudioCopy, limitUs: Long) {
        try {
            val buf = ByteBuffer.allocate(1 shl 20)
            val info = MediaCodec.BufferInfo()
            while (true) {
                buf.clear()
                val n = a.extractor.readSampleData(buf, 0)
                val t = a.extractor.sampleTime
                if (n < 0 || t > limitUs) break
                info.set(0, n, t, if (a.extractor.sampleFlags and MediaExtractor.SAMPLE_FLAG_SYNC != 0) MediaCodec.BUFFER_FLAG_KEY_FRAME else 0)
                mux.writeSampleData(a.track, buf, info)
                a.extractor.advance()
            }
        } finally {
            a.extractor.release()
        }
    }

    private fun fillImage(img: Image, i420: ByteArray) {
        var off = 0
        for (p in 0 until 3) {
            val plane = img.planes[p]
            val pw = if (p == 0) Native.W else Native.W / 2
            val ph = if (p == 0) Native.H else Native.H / 2
            val buf: ByteBuffer = plane.buffer
            val rs = plane.rowStride
            val ps = plane.pixelStride
            for (y in 0 until ph) {
                if (ps == 1) {
                    buf.position(y * rs); buf.put(i420, off, pw)
                } else {
                    for (x in 0 until pw) buf.put(y * rs + x * ps, i420[off + x])
                }
                off += pw
            }
        }
    }

    companion object {
        const val FRAME_US = 40_000L

        fun frameCount(durationUs: Long): Int =
            (durationUs / FRAME_US + if (durationUs % FRAME_US > 0) 1 else 0)
                .coerceIn(1, Int.MAX_VALUE.toLong()).toInt()

        fun rgbToBitmap(rgb: ByteArray): Bitmap {
            val px = IntArray(Native.W * Native.H)
            for (i in px.indices) {
                val o = i * 3
                px[i] = (0xFF shl 24) or ((rgb[o].toInt() and 0xFF) shl 16) or
                    ((rgb[o + 1].toInt() and 0xFF) shl 8) or (rgb[o + 2].toInt() and 0xFF)
            }
            return Bitmap.createBitmap(px, Native.W, Native.H, Bitmap.Config.ARGB_8888)
        }
    }
}

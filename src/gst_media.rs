//! Persistent, timestamped GStreamer decoding for interactive preview.
use crate::{
    media::VideoInfo,
    model::Params,
    signal::{FIELD_HEIGHT, HEIGHT, WIDTH},
};
use gst::prelude::*;
use gstreamer as gst;
use gstreamer_video as video;
use std::{
    collections::{BTreeMap, VecDeque},
    path::{Path, PathBuf},
    sync::OnceLock,
    time::{Duration, Instant},
};
use video::VideoFrameExt;

const FIELD_NS: u64 = 20_000_000;
const CACHE_FRAMES: usize = 16;

fn initialize() -> Result<(), String> {
    static INITIALIZED: OnceLock<Result<(), String>> = OnceLock::new();
    INITIALIZED
        .get_or_init(|| {
            let root = std::env::var_os("PAL_VHS_GSTREAMER_ROOT")
                .map(PathBuf::from)
                .or_else(|| {
                    std::env::current_exe()
                        .ok()
                        .and_then(|p| p.parent().map(Path::to_owned))
                });
            if let Some(root) = root {
                let limited = root.join("lib/gstreamer-1.0-preview");
                let plugins = if limited.is_dir() {
                    limited
                } else {
                    root.join("lib/gstreamer-1.0")
                };
                if plugins.is_dir() {
                    std::env::set_var("GST_PLUGIN_SYSTEM_PATH_1_0", &plugins);
                }
                let scanner = root.join("libexec/gstreamer-1.0/gst-plugin-scanner.exe");
                if scanner.is_file() {
                    std::env::set_var("GST_PLUGIN_SCANNER_1_0", scanner);
                }
            }
            if std::env::var_os("GST_REGISTRY_1_0").is_none() {
                std::env::set_var(
                    "GST_REGISTRY_1_0",
                    std::env::temp_dir().join("pal-vhs-gst-x64-registry.bin"),
                );
            }
            gst::init().map_err(|e| format!("GStreamer initialization failed: {e}"))
        })
        .clone()
}

struct RunningPipeline {
    pipeline: gst::Pipeline,
    sink: gstreamer_app::AppSink,
}
impl Drop for RunningPipeline {
    fn drop(&mut self) {
        let _ = self.pipeline.set_state(gst::State::Null);
    }
}
impl RunningPipeline {
    fn error(&self) -> Option<String> {
        let message = self
            .pipeline
            .bus()?
            .pop_filtered(&[gst::MessageType::Error])?;
        match message.view() {
            gst::MessageView::Error(e) => Some(format!(
                "GStreamer: {} ({})",
                e.error(),
                e.debug().unwrap_or_default()
            )),
            _ => None,
        }
    }
    fn pull(&self) -> Result<gst::Sample, String> {
        let start = Instant::now();
        loop {
            if let Some(sample) = self.sink.try_pull_sample(gst::ClockTime::from_mseconds(50)) {
                return Ok(sample);
            }
            if let Some(error) = self.error() {
                return Err(error);
            }
            if self.sink.is_eos() {
                return Err("GStreamer reached the end of the video".into());
            }
            if start.elapsed() > Duration::from_secs(10) {
                return Err("GStreamer timed out waiting for a decoded frame".into());
            }
        }
    }
}

fn make_pipeline(path: &Path, aspect: &str) -> Result<RunningPipeline, String> {
    let uri = gst::glib::filename_to_uri(path, None).map_err(|e| e.to_string())?;
    let pipeline = gst::Pipeline::new();
    let source = gst::ElementFactory::make("uridecodebin3")
        .property("uri", uri.as_str())
        .build()
        .map_err(|e| format!("GStreamer playback plugin unavailable: {e}"))?;
    let queue = gst::ElementFactory::make("queue")
        .property("max-size-buffers", 2u32)
        .property("max-size-bytes", 0u32)
        .property("max-size-time", 0u64)
        .build()
        .map_err(|e| e.to_string())?;
    let convert = gst::ElementFactory::make("videoconvert")
        .build()
        .map_err(|e| e.to_string())?;
    let scale = gst::ElementFactory::make("videoscale")
        .property("add-borders", aspect == "fit")
        .build()
        .map_err(|e| e.to_string())?;
    let rate = gst::ElementFactory::make("videorate")
        .build()
        .map_err(|e| e.to_string())?;
    let caps = gst::Caps::builder("video/x-raw")
        .field("format", "RGB")
        .field("width", WIDTH as i32)
        .field("height", HEIGHT as i32)
        .field("pixel-aspect-ratio", gst::Fraction::new(16, 15))
        .field("framerate", gst::Fraction::new(50, 1))
        .build();
    let sink = gstreamer_app::AppSink::builder()
        .caps(&caps)
        .max_buffers(2)
        .drop(false)
        .sync(false)
        .wait_on_eos(false)
        .build();
    let mut chain = vec![queue.clone(), convert];
    if aspect == "crop" {
        chain.push(
            gst::ElementFactory::make("aspectratiocrop")
                .property("aspect-ratio", gst::Fraction::new(4, 3))
                .build()
                .map_err(|e| e.to_string())?,
        );
    }
    chain.extend([scale, rate, sink.clone().upcast()]);
    pipeline.add(&source).map_err(|e| e.to_string())?;
    pipeline.add_many(&chain).map_err(|e| e.to_string())?;
    gst::Element::link_many(&chain)
        .map_err(|e| format!("Cannot link GStreamer video pipeline: {e}"))?;
    let sink_pad = queue
        .static_pad("sink")
        .ok_or("GStreamer queue has no sink pad")?;
    source.connect_pad_added(move |_, pad| {
        let caps = pad.current_caps().unwrap_or_else(|| pad.query_caps(None));
        if caps
            .structure(0)
            .is_some_and(|s| s.name().starts_with("video/"))
            && !sink_pad.is_linked()
        {
            let _ = pad.link(&sink_pad);
        }
    });
    let run = RunningPipeline { pipeline, sink };
    run.pipeline
        .set_state(gst::State::Playing)
        .map_err(|e| format!("Cannot start GStreamer: {e:?}"))?;
    let (result, _, _) = run.pipeline.state(gst::ClockTime::from_seconds(8));
    result.map_err(|e| {
        run.error()
            .unwrap_or_else(|| format!("GStreamer failed to open video: {e:?}"))
    })?;
    Ok(run)
}

pub struct GstVideoSource {
    pub info: VideoInfo,
    path: PathBuf,
    run: RunningPipeline,
    aspect: String,
    cache: BTreeMap<u64, Vec<u8>>,
    cache_order: VecDeque<u64>,
    next_index: Option<u64>,
}
impl GstVideoSource {
    pub fn open(path: &Path) -> Result<Self, String> {
        let path = std::fs::canonicalize(path)
            .map_err(|e| format!("Cannot open {}: {e}", path.display()))?;
        initialize()?;
        let run = make_pipeline(&path, "fit")?;
        let duration = run
            .pipeline
            .query_duration::<gst::ClockTime>()
            .ok_or("GStreamer could not determine the clip duration")?
            .seconds_f64();
        if !duration.is_finite() || duration <= 0. {
            return Err("Video duration is invalid".into());
        }
        let info = VideoInfo {
            duration,
            n_frames: ((duration * 25. + 1e-6).floor() as u64).max(1),
            width: WIDTH as u32,
            height: HEIGHT as u32,
            fps: 50.,
            has_audio: false,
        };
        Ok(Self {
            info,
            path,
            run,
            aspect: "fit".into(),
            cache: BTreeMap::new(),
            cache_order: VecDeque::new(),
            next_index: Some(0),
        })
    }
    fn sample_frame(sample: &gst::Sample) -> Result<(u64, Vec<u8>), String> {
        let buffer = sample.buffer().ok_or("Decoded sample has no buffer")?;
        let pts = buffer.pts().ok_or("Decoded frame has no timestamp")?;
        let timestamp = sample
            .segment()
            .and_then(|s| s.downcast_ref::<gst::ClockTime>())
            .and_then(|s| s.to_stream_time(pts))
            .unwrap_or(pts)
            .nseconds();
        let index = timestamp.saturating_add(FIELD_NS / 2) / FIELD_NS;
        let caps = sample.caps().ok_or("Decoded sample has no video caps")?;
        let info = video::VideoInfo::from_caps(caps).map_err(|e| e.to_string())?;
        if info.width() != WIDTH as u32
            || info.height() != HEIGHT as u32
            || info.format() != video::VideoFormat::Rgb
        {
            return Err("GStreamer negotiated an unexpected video format".into());
        }
        let frame = video::VideoFrameRef::from_buffer_ref_readable(buffer, &info)
            .map_err(|e| e.to_string())?;
        let stride = frame.plane_stride()[0];
        if stride < (WIDTH * 3) as i32 {
            return Err("Decoded RGB plane stride is invalid".into());
        }
        let plane = frame.plane_data(0).map_err(|e| e.to_string())?;
        let mut rgb = vec![0; WIDTH * HEIGHT * 3];
        for y in 0..HEIGHT {
            let start = y * stride as usize;
            let end = start + WIDTH * 3;
            if end > plane.len() {
                return Err("Decoded RGB plane is truncated".into());
            }
            rgb[y * WIDTH * 3..(y + 1) * WIDTH * 3].copy_from_slice(&plane[start..end]);
        }
        Ok((index, rgb))
    }
    fn decoded(&mut self, index: u64) -> Result<Vec<u8>, String> {
        if let Some(rgb) = self.cache.get(&index) {
            return Ok(rgb.clone());
        }
        if !self
            .next_index
            .is_some_and(|next| index >= next && index - next <= 8)
        {
            // Decode from the preceding keyframe so videorate sees the same
            // neighbouring timestamps as sequential playback, including VFR.
            let before = index.saturating_sub(10) * FIELD_NS;
            self.run
                .pipeline
                .seek_simple(
                    gst::SeekFlags::FLUSH | gst::SeekFlags::KEY_UNIT | gst::SeekFlags::SNAP_BEFORE,
                    gst::ClockTime::from_nseconds(before),
                )
                .map_err(|e| format!("GStreamer seek failed: {e}"))?;
            self.next_index = None;
        }
        let start = Instant::now();
        loop {
            let sample = self.run.pull()?;
            let (actual, rgb) = Self::sample_frame(&sample)?;
            self.next_index = Some(actual + 1);
            if actual > index {
                return Err(format!(
                    "GStreamer skipped requested timestamp {index}; received {actual}"
                ));
            }
            if self.cache.insert(actual, rgb).is_none() {
                self.cache_order.push_back(actual);
            }
            while self.cache.len() > CACHE_FRAMES {
                if let Some(old) = self.cache_order.pop_front() {
                    self.cache.remove(&old);
                }
            }
            if actual == index {
                return Ok(self.cache[&index].clone());
            }
            if start.elapsed() > Duration::from_secs(10) {
                return Err("GStreamer seek timed out".into());
            }
        }
    }
    pub fn fields(&mut self, frame: u64, p: &Params) -> Result<(Vec<u8>, Vec<u8>), String> {
        if frame >= self.info.n_frames {
            return Err(format!("Frame {frame} is beyond the end of the video"));
        }
        let aspect = p.choice("aspect");
        if aspect != self.aspect {
            self.run = make_pipeline(&self.path, aspect)?;
            self.aspect = aspect.into();
            self.cache.clear();
            self.cache_order.clear();
            self.next_index = Some(0);
        }
        let mut first = self.decoded(frame * 2)?;
        let mut second = if p.choice("field_mode") == "temporal" {
            self.decoded(frame * 2 + 1)?
        } else {
            first.clone()
        };
        crate::media::vertical_filter(&mut first, p.number("vfilter"));
        crate::media::vertical_filter(&mut second, p.number("vfilter"));
        let row = WIDTH * 3;
        let mut a = Vec::with_capacity(row * FIELD_HEIGHT);
        let mut b = Vec::with_capacity(row * FIELD_HEIGHT);
        for y in 0..FIELD_HEIGHT {
            a.extend_from_slice(&first[2 * y * row..(2 * y + 1) * row]);
            b.extend_from_slice(&second[(2 * y + 1) * row..(2 * y + 2) * row]);
        }
        Ok((a, b))
    }
}

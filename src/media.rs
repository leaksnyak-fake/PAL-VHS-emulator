//! FFmpeg subprocess I/O. Video buffers and render queues have fixed bounds.
use crate::{
    model::Params,
    renderer::{render_frame, FieldMode},
    signal::{Engine, HEIGHT, WIDTH},
};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    fs::File,
    io::{Read, Seek, SeekFrom, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdout, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Arc, Mutex,
    },
    thread,
    time::Duration,
};

#[derive(Clone, Debug)]
pub struct VideoInfo {
    pub duration: f64,
    pub n_frames: u64,
    pub width: u32,
    pub height: u32,
    pub fps: f64,
    pub has_audio: bool,
}

fn command(program: &str) -> Command {
    let mut cmd = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000);
    }
    cmd
}

pub fn probe(path: &Path) -> Result<VideoInfo, String> {
    let output = command("ffprobe")
        .args([
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
        ])
        .arg(path)
        .output()
        .map_err(|e| {
            format!("Cannot start ffprobe (install FFmpeg and add its bin directory to PATH): {e}")
        })?;
    if !output.status.success() {
        return Err(format!(
            "Cannot open {}: {}",
            path.display(),
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    let data: Value = serde_json::from_slice(&output.stdout)
        .map_err(|e| format!("Invalid ffprobe response: {e}"))?;
    let streams = data["streams"].as_array().ok_or("No streams in video")?;
    let video = streams
        .iter()
        .find(|s| s["codec_type"] == "video")
        .ok_or("Input has no video stream")?;
    let duration = video["duration"]
        .as_str()
        .and_then(|s| s.parse::<f64>().ok())
        .or_else(|| {
            data["format"]["duration"]
                .as_str()
                .and_then(|s| s.parse().ok())
        })
        .filter(|d| d.is_finite() && *d > 0.)
        .ok_or("Cannot determine video duration")?;
    let fps = video["avg_frame_rate"]
        .as_str()
        .and_then(|s| {
            let (a, b) = s.split_once('/')?;
            Some(a.parse::<f64>().ok()? / b.parse::<f64>().ok()?)
        })
        .filter(|v| v.is_finite() && *v > 0.)
        .unwrap_or(25.);
    Ok(VideoInfo {
        duration,
        n_frames: ((duration * 25.).floor() as u64).max(1),
        width: video["width"].as_u64().unwrap_or(0) as u32,
        height: video["height"].as_u64().unwrap_or(0) as u32,
        fps,
        has_audio: streams.iter().any(|s| s["codec_type"] == "audio"),
    })
}

pub fn field_time(frame: u64, field: usize, temporal: bool) -> f64 {
    frame as f64 / 25. + if temporal { field as f64 / 50. } else { 0. }
}

pub fn fit_filter(p: &Params) -> String {
    let canvas:String=match p.choice("aspect"){
        "crop"=>"scale=768:576:force_original_aspect_ratio=increase,crop=768:576,scale=720:576,setsar=16/15".into(),
        "stretch"=>"scale=768:576,scale=720:576,setsar=16/15".into(),
        _=>"scale=768:576:force_original_aspect_ratio=decrease,pad=768:576:(ow-iw)/2:(oh-ih)/2:black,scale=720:576,setsar=16/15".into()
    };
    format!("scale=trunc(iw*sar+0.5):ih,setsar=1,{canvas}")
}

// The pipe handles stay on their I/O thread; a separate watcher can terminate
// FFmpeg even while read_exact/write_all is blocked. Never wait with the lock held.
struct ManagedChild {
    child: Arc<Mutex<Child>>,
    done: Arc<AtomicBool>,
    watcher: Option<thread::JoinHandle<()>>,
}
impl ManagedChild {
    fn new(child: Child, cancel: Arc<AtomicBool>) -> Self {
        let child = Arc::new(Mutex::new(child));
        let done = Arc::new(AtomicBool::new(false));
        let process = child.clone();
        let finished = done.clone();
        let watcher = thread::spawn(move || {
            while !finished.load(Ordering::Relaxed) {
                if cancel.load(Ordering::Relaxed) {
                    if let Ok(mut child) = process.lock() {
                        let _ = child.kill();
                    }
                    break;
                }
                thread::sleep(Duration::from_millis(50));
            }
        });
        Self {
            child,
            done,
            watcher: Some(watcher),
        }
    }
    fn wait(&mut self) -> Result<std::process::ExitStatus, String> {
        loop {
            if let Some(status) = self
                .child
                .lock()
                .map_err(|e| e.to_string())?
                .try_wait()
                .map_err(|e| e.to_string())?
            {
                return Ok(status);
            }
            thread::sleep(Duration::from_millis(20));
        }
    }
}
impl Drop for ManagedChild {
    fn drop(&mut self) {
        self.done.store(true, Ordering::Relaxed);
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
        }
        let _ = self.wait();
        if let Some(watcher) = self.watcher.take() {
            let _ = watcher.join();
        }
    }
}
struct Decoder {
    _child: ManagedChild,
    stdout: ChildStdout,
    log: tempfile::NamedTempFile,
    next: u64,
    key: String,
}
fn log_tail(file: &mut File) -> String {
    let _ = file.seek(SeekFrom::Start(0));
    let mut s = String::new();
    let _ = file.read_to_string(&mut s);
    s.chars()
        .rev()
        .take(2500)
        .collect::<String>()
        .chars()
        .rev()
        .collect()
}

pub struct VideoSource {
    pub info: VideoInfo,
    path: PathBuf,
    decoder: Option<Decoder>,
    cancel: Arc<AtomicBool>,
}
impl VideoSource {
    pub fn open(path: &Path) -> Result<Self, String> {
        Ok(Self {
            info: probe(path)?,
            path: path.to_owned(),
            decoder: None,
            cancel: Arc::new(AtomicBool::new(false)),
        })
    }
    pub fn set_cancel_token(&mut self, cancel: Arc<AtomicBool>) {
        self.decoder = None;
        self.cancel = cancel;
    }
    fn start(&mut self, frame: u64, p: &Params) -> Result<(), String> {
        self.decoder = None;
        let temporal = p.choice("field_mode") == "temporal";
        let rate = if temporal { 50 } else { 25 };
        let log = tempfile::NamedTempFile::new().map_err(|e| e.to_string())?;
        let filter = format!("fps={rate}:round=near,{}", fit_filter(p));
        let mut child = command("ffmpeg")
            .args([
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-threads",
                "1",
            ])
            .arg("-i")
            .arg(&self.path)
            .args([
                "-an",
                "-sn",
                "-vf",
                &filter,
                "-ss",
                &format!("{:.9}", frame as f64 / 25.),
                "-threads",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::from(log.reopen().map_err(|e| e.to_string())?))
            .spawn()
            .map_err(|e| format!("Cannot start FFmpeg: {e}"))?;
        let stdout = child.stdout.take().ok_or("FFmpeg stdout unavailable")?;
        self.decoder = Some(Decoder {
            _child: ManagedChild::new(child, self.cancel.clone()),
            stdout,
            log,
            next: frame,
            key: format!("{}:{}", p.choice("field_mode"), fit_filter(p)),
        });
        Ok(())
    }
    pub fn fields(&mut self, frame: u64, p: &Params) -> Result<(Vec<u8>, Vec<u8>), String> {
        if self.cancel.load(Ordering::Relaxed) {
            return Err("Export cancelled".into());
        }
        if frame >= self.info.n_frames {
            return Err(format!("Frame {frame} is beyond the end of the video"));
        }
        let key = format!("{}:{}", p.choice("field_mode"), fit_filter(p));
        if self
            .decoder
            .as_ref()
            .is_none_or(|d| d.next != frame || d.key != key)
        {
            self.start(frame, p)?;
        }
        let decoder = self.decoder.as_mut().unwrap();
        let mut first = vec![0u8; WIDTH * HEIGHT * 3];
        decoder.stdout.read_exact(&mut first).map_err(|e| {
            format!(
                "Decode failed at frame {frame}: {e}. {}",
                log_tail(decoder.log.as_file_mut())
            )
        })?;
        let mut second = if p.choice("field_mode") == "temporal" {
            let mut b = vec![0u8; first.len()];
            match decoder.stdout.read_exact(&mut b) {
                Ok(()) => b,
                Err(e)
                    if e.kind() == std::io::ErrorKind::UnexpectedEof
                        && frame + 1 == self.info.n_frames =>
                {
                    first.clone()
                }
                Err(e) => {
                    return Err(format!(
                        "Second-field decode failed at frame {frame}: {e}. {}",
                        log_tail(decoder.log.as_file_mut())
                    ))
                }
            }
        } else {
            first.clone()
        };
        vertical_filter(&mut first, p.number("vfilter"));
        vertical_filter(&mut second, p.number("vfilter"));
        let row = WIDTH * 3;
        let mut a = Vec::with_capacity(row * HEIGHT / 2);
        let mut b = Vec::with_capacity(row * HEIGHT / 2);
        for y in 0..HEIGHT / 2 {
            a.extend_from_slice(&first[2 * y * row..(2 * y + 1) * row]);
            b.extend_from_slice(&second[(2 * y + 1) * row..(2 * y + 2) * row]);
        }
        decoder.next = frame + 1;
        Ok((a, b))
    }
}

pub fn vertical_filter(rgb: &mut [u8], amount: f64) {
    if amount <= 0. {
        return;
    }
    let old = rgb.to_vec();
    let row = WIDTH * 3;
    let a = amount * 0.25;
    for y in 0..HEIGHT {
        for x in 0..row {
            let v = a * old[y.saturating_sub(1) * row + x] as f64
                + (1. - 2. * a) * old[y * row + x] as f64
                + a * old[(y + 1).min(HEIGHT - 1) * row + x] as f64;
            rgb[y * row + x] = v.round().clamp(0., 255.) as u8;
        }
    }
}

#[derive(Clone, Debug)]
pub struct ExportOptions {
    pub workers: usize,
    pub start_frame: u64,
    pub max_frames: Option<u64>,
    pub audio: bool,
    pub crf: u8,
    pub x264_preset: String,
}
impl Default for ExportOptions {
    fn default() -> Self {
        Self {
            workers: thread::available_parallelism()
                .map(|n| n.get())
                .unwrap_or(2)
                .min(4),
            start_frame: 0,
            max_frames: None,
            audio: true,
            crf: 14,
            x264_preset: "veryfast".into(),
        }
    }
}

pub fn validate_export(input: &Path, output: &Path, o: &ExportOptions) -> Result<(), String> {
    let resolved_in = std::fs::canonicalize(input)
        .unwrap_or_else(|_| std::path::absolute(input).unwrap_or_else(|_| input.to_owned()));
    let resolved_out = std::fs::canonicalize(output)
        .unwrap_or_else(|_| std::path::absolute(output).unwrap_or_else(|_| output.to_owned()));
    if resolved_in == resolved_out {
        return Err("Input and output must be different files".into());
    }
    if o.workers == 0 || o.workers > 64 {
        return Err("Worker count must be between 1 and 64".into());
    }
    if o.crf > 51 {
        return Err("CRF must be between 0 and 51".into());
    }
    if o.max_frames == Some(0) {
        return Err("Maximum frame count must be positive".into());
    }
    if ![
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
    ]
    .contains(&o.x264_preset.as_str())
    {
        return Err("Unknown x264 preset".into());
    }
    Ok(())
}

/// Interlace signalling for the encoder.
///
/// Interlaced (MBAFF) H.264 crashes or is rejected by many players, hardware
/// decoders and editors, so H.264 output is always written as progressive
/// frames (the woven fields are still in the picture). ProRes (.mov) is the
/// interlaced-aware format: it is flagged top-field-first.
pub fn output_flags(p: &Params, prores: bool) -> Vec<String> {
    if prores && p.choice("export_fields") == "interlaced" {
        vec!["-flags".into(), "+ildct".into(), "-top".into(), "1".into()]
    } else {
        vec![]
    }
}

pub fn is_prores_output(output: &Path) -> bool {
    output.extension().and_then(|s| s.to_str()) == Some("mov")
}

struct Encoder {
    child: ManagedChild,
    log: tempfile::NamedTempFile,
}

pub fn export_video(
    input: &Path,
    output: &Path,
    params: Params,
    options: ExportOptions,
    cancel: Arc<AtomicBool>,
    mut progress: impl FnMut(u64, u64),
) -> Result<(), String> {
    let output = if output.extension().is_none() {
        output.with_extension("mp4")
    } else {
        output.to_owned()
    };
    validate_export(input, &output, &options)?;
    if cancel.load(Ordering::Relaxed) {
        return Err("Export cancelled".into());
    }
    let mut source = VideoSource::open(input)?;
    source.set_cancel_token(cancel.clone());
    let total = source
        .info
        .n_frames
        .checked_sub(options.start_frame)
        .ok_or("Start frame is beyond end of video")?
        .min(options.max_frames.unwrap_or(u64::MAX));
    if total == 0 {
        return Err("Nothing to export".into());
    }
    let parent = output
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let suffix = format!(
        ".{}",
        output.extension().unwrap_or_default().to_string_lossy()
    );
    let temporary = tempfile::Builder::new()
        .prefix(".pal-vhs-")
        .suffix(&suffix)
        .tempfile_in(parent)
        .map_err(|e| format!("Cannot create temporary export: {e}"))?;
    let log = tempfile::NamedTempFile::new().map_err(|e| e.to_string())?;
    let prores = is_prores_output(&output);
    let mut cmd = command("ffmpeg");
    cmd.args([
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        "720x576",
        "-r",
        "25",
        "-i",
        "pipe:0",
    ]);
    if options.audio && source.info.has_audio {
        cmd.args([
            "-ss",
            &format!("{:.9}", options.start_frame as f64 / 25.),
            "-i",
        ])
        .arg(input)
        .args([
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:a",
            if prores { "pcm_s16le" } else { "copy" },
            "-t",
            &format!("{:.9}", total as f64 / 25.),
        ]);
    }
    if prores {
        // ProRes 422 HQ, 10-bit 4:2:2: the standard intermediate for editors.
        cmd.args(["-c:v", "prores_ks", "-profile:v", "3"])
            .args(output_flags(&params, true))
            .args(["-vf", "setsar=16/15", "-pix_fmt", "yuv422p10le"]);
    } else {
        cmd.args([
            "-c:v",
            "libx264",
            "-preset",
            &options.x264_preset,
            "-crf",
            &options.crf.to_string(),
            // Keep the stream inside its declared level (CRF alone can exceed
            // the level's bitrate limit, which decoders and editors reject).
            "-profile:v",
            "high",
            "-level:v",
            "4.0",
            "-maxrate",
            "20M",
            "-bufsize",
            "25M",
        ])
        .args(output_flags(&params, false))
        .args(["-vf", "setsar=16/15", "-pix_fmt", "yuv420p"]);
    }
    cmd.args([
        "-aspect",
        "4:3",
        "-color_range",
        "tv",
        "-colorspace",
        "bt470bg",
        "-color_primaries",
        "bt470bg",
        "-color_trc",
        "gamma28",
    ]);
    if matches!(
        output.extension().and_then(|s| s.to_str()),
        Some("mp4" | "mov" | "m4v")
    ) {
        cmd.args(["-movflags", "+faststart"]);
    }
    let mut child = cmd
        .arg(temporary.path())
        .stdin(Stdio::piped())
        .stderr(Stdio::from(log.reopen().map_err(|e| e.to_string())?))
        .stdout(Stdio::null())
        .spawn()
        .map_err(|e| format!("Cannot start FFmpeg encoder: {e}"))?;
    let mut stdin = child.stdin.take().ok_or("Encoder stdin unavailable")?;
    let mut encoder = Encoder {
        child: ManagedChild::new(child, cancel.clone()),
        log,
    };
    let workers = options.workers.min(total as usize).max(1);
    let mut senders = Vec::new();
    let mut handles = Vec::new();
    let (result_tx, result_rx) = mpsc::sync_channel(workers * 2);
    let mode = FieldMode::from_params(&params);
    for _ in 0..workers {
        let (tx, rx) = mpsc::sync_channel::<(u64, Vec<u8>, Vec<u8>)>(1);
        senders.push(tx);
        let result_tx = result_tx.clone();
        let p = params.clone();
        let stop = cancel.clone();
        handles.push(thread::spawn(move || {
            let mut engine = Engine::new(p);
            while let Ok((index, a, b)) = rx.recv() {
                if stop.load(Ordering::Relaxed) {
                    break;
                }
                let result =
                    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| match &mut engine {
                        Ok(e) => render_frame(e, &a, &b, index, mode, false).map(|f| f.rgb),
                        Err(e) => Err(e.clone()),
                    }))
                    .unwrap_or_else(|_| Err("Render worker panicked".into()));
                if result_tx.send((index, result)).is_err() {
                    break;
                }
            }
        }));
    }
    drop(result_tx);
    let result: Result<(), String> = (|| {
        let mut submitted = 0;
        let mut done = 0;
        let mut ready = BTreeMap::new();
        while done < total {
            if cancel.load(Ordering::Relaxed) {
                return Err("Export cancelled".into());
            }
            while submitted < total && submitted - done < (workers * 2) as u64 {
                let index = options.start_frame + submitted;
                let (a, b) = source.fields(index, &params)?;
                senders[submitted as usize % workers]
                    .send((index, a, b))
                    .map_err(|_| "Render worker stopped")?;
                submitted += 1;
            }
            let (index, frame) = loop {
                match result_rx.recv_timeout(Duration::from_millis(50)) {
                    Ok(value) => break value,
                    Err(mpsc::RecvTimeoutError::Timeout) => {
                        if cancel.load(Ordering::Relaxed) {
                            return Err("Export cancelled".into());
                        }
                    }
                    Err(mpsc::RecvTimeoutError::Disconnected) => {
                        return Err("All render workers stopped".into())
                    }
                }
            };
            ready.insert(index, frame?);
            while let Some(rgb) = ready.remove(&(options.start_frame + done)) {
                if cancel.load(Ordering::Relaxed) {
                    return Err("Export cancelled".into());
                }
                stdin
                    .write_all(&rgb)
                    .map_err(|e| format!("FFmpeg stopped receiving video: {e}"))?;
                done += 1;
                progress(done, total);
            }
        }
        Ok(())
    })();
    drop(senders);
    drop(result_rx);
    for h in handles {
        let _ = h.join();
    }
    drop(stdin);
    if cancel.load(Ordering::Relaxed) {
        return Err("Export cancelled".into());
    }
    if let Err(e) = result {
        return Err(format!("{e}\n{}", log_tail(encoder.log.as_file_mut())));
    }
    let status = encoder.child.wait()?;
    if cancel.load(Ordering::Relaxed) {
        return Err("Export cancelled".into());
    }
    if !status.success() {
        return Err(format!(
            "FFmpeg encoding failed: {}",
            log_tail(encoder.log.as_file_mut())
        ));
    }
    if cancel.load(Ordering::Relaxed) {
        return Err("Export cancelled".into());
    }
    temporary
        .persist(&output)
        .map_err(|e| format!("Could not replace output file: {}", e.error))?;
    Ok(())
}

#[cfg(test)]
mod process_tests {
    use super::*;
    #[test]
    fn cancellation_terminates_running_ffmpeg() {
        let cancel = Arc::new(AtomicBool::new(false));
        let child = command("ffmpeg")
            .args([
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-re",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000",
                "-f",
                "null",
                "-",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("FFmpeg must be on PATH");
        let mut child = ManagedChild::new(child, cancel.clone());
        let started = std::time::Instant::now();
        thread::sleep(Duration::from_millis(100));
        cancel.store(true, Ordering::Relaxed);
        assert!(!child.wait().unwrap().success());
        assert!(
            started.elapsed() < Duration::from_secs(3),
            "Cancellation did not terminate FFmpeg promptly"
        );
    }
}

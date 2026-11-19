#![cfg(feature = "desktop")]
use pal_vhs::{gst_media::GstVideoSource, model::Params, preview::AccuratePreview, renderer::FieldMode};
use std::{path::PathBuf, process::Command, time::Instant};
fn video() -> (tempfile::TempDir, PathBuf) {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("gst seek test.mkv");
    let output = Command::new("ffmpeg")
        .args([
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=768x576:rate=30000/1001",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-g",
            "30",
            "-pix_fmt",
            "yuv420p",
        ])
        .arg(&path)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    (temp, path)
}
#[test]
fn persistent_gstreamer_source_has_deterministic_seek_and_field_modes() {
    let (_temp, path) = video();
    let p = Params::default();
    let mut source = GstVideoSource::open(&path).unwrap();
    assert!(source.info.duration > 2.9);
    let mut first = Vec::new();
    for f in 0..36 {
        let pair = source.fields(f, &p).unwrap();
        assert_eq!(pair.0.len(), 720 * 288 * 3);
        first.push(pair);
    }
    for f in [34, 1, 28, 3, 0, 35, 4] {
        assert!(
            source.fields(f, &p).unwrap() == first[f as usize],
            "seek changed frame {f}"
        );
    }
    let mut frame = p.clone();
    frame.set("field_mode", serde_json::json!("frame")).unwrap();
    assert_eq!(source.fields(0, &frame).unwrap().0, first[0].0);
    assert!(source.fields(source.info.n_frames, &p).is_err());
}
#[test]
fn missing_video_returns_error() {
    assert!(GstVideoSource::open(&PathBuf::from("missing-video-52738.mp4")).is_err());
}
#[test]
#[ignore = "release end-to-end preview measurement"]
fn measure_gstreamer_exact_preview() {
    let (_temp, path) = video();
    let p = Params::default();
    let mut source = GstVideoSource::open(&path).unwrap();
    let mut engine = AccuratePreview::new(p.clone()).unwrap();
    let mut times = Vec::new();
    for f in 0..8 {
        let start = Instant::now();
        let (a, b) = source.fields(f, &p).unwrap();
        std::hint::black_box(engine.render(&a, &b, f, FieldMode::Interlaced, false).unwrap());
        times.push(start.elapsed().as_secs_f64() * 1000.);
    }
    times.sort_by(f64::total_cmp);
    eprintln!(
        "GStreamer decode + exact RF p50={:.2}ms p95={:.2}ms (25fps budget=40ms)",
        times[4], times[7]
    );
}

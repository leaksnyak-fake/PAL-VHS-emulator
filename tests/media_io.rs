use pal_vhs::{
    media::{export_video, ExportOptions, VideoSource},
    model::Params,
};
use std::{
    process::Command,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

fn make_video(path: &std::path::Path, pattern: &str, rate: &str, sar: &str) {
    let source = if pattern == "white" {
        format!("color=c=white:size=720x576:rate={rate}")
    } else {
        format!("{pattern}=size=720x576:rate={rate}")
    };
    let result = Command::new("ffmpeg")
        .args([
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            &source,
            "-t",
            "0.6",
            "-vf",
            &format!("setsar={sar}"),
            "-c:v",
            "ffv1",
        ])
        .arg(path)
        .output()
        .expect("FFmpeg must be on PATH for media integration tests");
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
}

#[test]
fn random_seeking_matches_sequential_fields_at_fractional_source_rate() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("fractional.mkv");
    make_video(&path, "testsrc", "30000/1001", "1");
    let p = Params::default();
    let mut sequential = VideoSource::open(&path).unwrap();
    let mut expected = Vec::new();
    for frame in 0..9 {
        expected.push(sequential.fields(frame, &p).unwrap());
    }
    let mut random = VideoSource::open(&path).unwrap();
    for frame in [8, 1, 6, 3, 0, 7, 2] {
        assert_eq!(
            random.fields(frame, &p).unwrap(),
            expected[frame as usize],
            "seeking changed field pictures at frame {frame}"
        );
    }
}

#[test]
fn anamorphic_four_three_input_fills_canvas_without_pillarboxing() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("anamorphic.mkv");
    make_video(&path, "white", "25", "16/15");
    let mut source = VideoSource::open(&path).unwrap();
    let (a, _) = source.fields(0, &Params::default()).unwrap();
    let edge = (100 * 720 + 1) * 3;
    assert!(
        a[edge..edge + 3].iter().all(|&v| v > 245),
        "4:3 source was pillarboxed"
    );
}

#[test]
fn cancellation_preserves_existing_destination() {
    let tmp = tempfile::tempdir().unwrap();
    let input = tmp.path().join("input.mkv");
    let output = tmp.path().join("output.mp4");
    make_video(&input, "testsrc", "25", "1");
    std::fs::write(&output, b"existing completed video").unwrap();
    let cancel = Arc::new(AtomicBool::new(false));
    let trigger = cancel.clone();
    let mut options = ExportOptions::default();
    options.workers = 1;
    options.max_frames = Some(4);
    options.audio = false;
    let mut params = Params::default();
    params.set("bypass_tape", serde_json::json!(true)).unwrap();
    let result = export_video(&input, &output, params, options, cancel, move |done, _| {
        if done == 1 {
            trigger.store(true, Ordering::Relaxed);
        }
    });
    assert!(result.unwrap_err().contains("cancelled"));
    assert_eq!(std::fs::read(output).unwrap(), b"existing completed video");
}

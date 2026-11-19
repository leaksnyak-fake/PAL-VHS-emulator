use pal_vhs::{model::Params, preview::AccuratePreview, renderer::{render_frame, FieldMode}, signal::Engine};
use serde_json::json;
const N: usize = 720 * 288 * 3;
fn image(shift: usize) -> Vec<u8> {
    (0..N).map(|i| ((i / 3 * 17 + i % 3 * 71 + shift) % 256) as u8).collect()
}
fn bypass() -> Params {
    let mut p = Params::default();
    p.set("bypass_tape", json!(true)).unwrap();
    p
}
#[test]
fn validates_both_fields_even_for_cached_frames() {
    let p = bypass();
    let mut preview = AccuratePreview::new(p).unwrap();
    let a = image(0);
    preview.render(&a, &a, 0, FieldMode::Interlaced, false).unwrap();
    assert!(preview.render(&[], &a, 0, FieldMode::Interlaced, false).is_err());
    assert!(preview.render(&a, &a[..N - 1], 0, FieldMode::Interlaced, false).is_err());
}
#[test]
fn exact_preview_matches_export_all_modes_and_scopes() {
    let a = image(0);
    let b = image(29);
    let p = bypass();
    let mut preview = AccuratePreview::new(p.clone()).unwrap();
    let mut export = Engine::new(p).unwrap();
    for (frame, mode, taps) in [
        (3, FieldMode::Interlaced, true),
        (4, FieldMode::First, false),
        (5, FieldMode::Second, false),
        (3, FieldMode::Interlaced, false),
    ] {
        let actual = preview.render(&a, &b, frame, mode, taps).unwrap();
        let expected = render_frame(&mut export, &a, &b, frame, mode, taps).unwrap();
        assert_eq!(actual.rgb, expected.rgb, "mismatch at frame {frame}, mode {mode:?}");
        assert_eq!(actual.taps, expected.taps, "waveform tap mismatch");
    }
}
#[test]
fn tape_damage_matches_export_and_is_seek_deterministic() {
    let a = image(4);
    let b = image(34);
    let p = Params::default();
    let mut preview = AccuratePreview::new(p.clone()).unwrap();
    let mut export = Engine::new(p).unwrap();
    let expected = render_frame(&mut export, &a, &b, 32, FieldMode::Interlaced, false).unwrap();
    let actual = preview.render(&a, &b, 32, FieldMode::Interlaced, false).unwrap();
    assert_eq!(actual.rgb, expected.rgb);
    let _ = preview.render(&a, &b, 4, FieldMode::Second, false).unwrap();
    let repeated = preview.render(&a, &b, 32, FieldMode::Interlaced, false).unwrap();
    assert_eq!(repeated.rgb, expected.rgb);
}
#[test]
#[ignore = "release throughput measurement; requires a representative host"]
fn measure_exact_preview() {
    let a = image(0);
    let b = image(15);
    let mut preview = AccuratePreview::new(Params::default()).unwrap();
    let mut times = Vec::new();
    for f in 0..12 {
        let start = std::time::Instant::now();
        std::hint::black_box(preview.render(&a, &b, f, FieldMode::Interlaced, false).unwrap());
        times.push(start.elapsed().as_secs_f64() * 1000.0);
    }
    times.sort_by(f64::total_cmp);
    eprintln!("full-RF preview p50={:.2}ms p95={:.2}ms; 25fps budget=40ms", times[6], times[11]);
}

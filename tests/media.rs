use pal_vhs::{
    media::{field_time, fit_filter, output_flags, validate_export, ExportOptions},
    model::Params,
};
use std::path::Path;

#[test]
fn temporal_fields_are_twenty_ms_apart() {
    assert!((field_time(10, 0, true) - 0.4).abs() < 1e-12);
    assert!((field_time(10, 1, true) - 0.42).abs() < 1e-12);
    assert_eq!(field_time(10, 1, false), field_time(10, 0, false));
}

#[test]
fn pal_filter_uses_square_pixel_canvas_before_storage_scaling() {
    let mut p = Params::default();
    let filter = fit_filter(&p);
    assert!(filter.contains("768:576"));
    assert!(filter.contains("720:576"));
    p.set("aspect", serde_json::json!("crop")).unwrap();
    assert!(fit_filter(&p).contains("crop=768:576"));
}

#[test]
fn only_prores_gets_interlaced_flags() {
    let mut p = Params::default();
    assert!(output_flags(&p, true).iter().any(|s| s == "+ildct"));
    // H.264 is always written progressive: interlaced MBAFF crashes many players.
    assert!(output_flags(&p, false).is_empty());
    p.set("export_fields", serde_json::json!("field 2 only"))
        .unwrap();
    assert!(output_flags(&p, true).is_empty());
}

#[test]
fn reject_input_output_alias_and_invalid_export_settings() {
    let p = Path::new("movie.mp4");
    assert!(validate_export(p, p, &ExportOptions::default()).is_err());
    let mut options = ExportOptions::default();
    options.workers = 0;
    assert!(validate_export(p, Path::new("out.mp4"), &options).is_err());
    options.workers = 1;
    options.x264_preset = "invalid".into();
    assert!(validate_export(p, Path::new("out.mp4"), &options).is_err());
}

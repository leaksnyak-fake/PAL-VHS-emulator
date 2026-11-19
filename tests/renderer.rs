use pal_vhs::model::Params;
use pal_vhs::renderer::{double_field, weave_fields, FieldMode, Generation};

#[test]
fn weave_preserves_field_parity_and_every_scanline() {
    let row = 720 * 3;
    let a: Vec<u8> = (0..288).flat_map(|y| vec![(y % 251) as u8; row]).collect();
    let b: Vec<u8> = (0..288)
        .flat_map(|y| vec![255 - (y % 251) as u8; row])
        .collect();
    let out = weave_fields(&a, &b).unwrap();
    assert_eq!(out.len(), row * 576);
    for y in 0..288 {
        assert_eq!(
            &out[2 * y * row..(2 * y + 1) * row],
            &a[y * row..(y + 1) * row]
        );
        assert_eq!(
            &out[(2 * y + 1) * row..(2 * y + 2) * row],
            &b[y * row..(y + 1) * row]
        );
    }
}

#[test]
fn single_field_duplicates_rows_without_blending() {
    let row = 720 * 3;
    let src: Vec<u8> = (0..288).flat_map(|y| vec![(y % 251) as u8; row]).collect();
    let out = double_field(&src).unwrap();
    for y in 0..288 {
        assert_eq!(
            &out[2 * y * row..(2 * y + 1) * row],
            &src[y * row..(y + 1) * row]
        );
        assert_eq!(
            &out[(2 * y + 1) * row..(2 * y + 2) * row],
            &src[y * row..(y + 1) * row]
        );
    }
    assert!(double_field(&src[..src.len() - 1]).is_err());
    assert!(weave_fields(&src, &[]).is_err());
}

#[test]
fn outdated_previews_cannot_replace_latest_request() {
    let mut generation = Generation::default();
    let first = generation.advance();
    assert!(generation.accepts(first));
    let latest = generation.advance();
    assert!(!generation.accepts(first));
    assert!(generation.accepts(latest));
}

#[test]
fn output_mode_matches_progressive_and_interlaced_setting() {
    let mut p = Params::default();
    assert!(FieldMode::from_params(&p).is_interlaced());
    p.set("export_fields", "field 2 only".into()).unwrap();
    assert_eq!(FieldMode::from_params(&p), FieldMode::Second);
    assert!(!FieldMode::from_params(&p).is_interlaced());
}

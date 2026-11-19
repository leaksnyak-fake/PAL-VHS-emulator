use pal_vhs::model::{decks, presets, specs, Params};
use serde_json::json;
#[test]
fn complete_defaults_and_clamping() {
    let mut p = Params::default();
    assert!(specs().len() == 137);
    for s in specs() {
        assert_eq!(p.to_value()[&s.key], s.default);
    }
    p.set("tape_noise", json!(99)).unwrap();
    assert_eq!(p.number("tape_noise"), 0.3);
    assert!(p.set("tape_speed", json!("invalid")).is_err());
}
#[test]
fn legacy_and_unknown_roundtrip() {
    let mut p = Params::default();
    p.set("hs_residual_motion", json!("Forward/back steps"))
        .unwrap();
    assert_eq!(p.choice("hs_residual_motion"), "Drift + jitter");
    p.set("future_parameter", json!({"x":1})).unwrap();
    let q = Params::from_value(p.to_value()).unwrap();
    assert_eq!(q.to_value()["future_parameter"], json!({"x":1}));
}
#[test]
fn preset_reset_deck_partial_and_macros() {
    let mut p = Params::default();
    p.set("wrinkle", json!(0.8)).unwrap();
    p.apply_deck(decks().keys().next().unwrap()).unwrap();
    assert_eq!(p.number("wrinkle"), 0.8);
    p.apply_preset("VHS SP - good tape").unwrap();
    assert_eq!(p.number("wrinkle"), 0.0);
    for name in ["wear", "colour", "unstable", "smear", "crease"] {
        p.set_macro(name, 100.0).unwrap();
        assert_eq!(p.macro_position(name), 100.0);
    }
    for name in presets().keys() {
        p.apply_preset(name).unwrap();
    }
}
#[test]
fn paired_ranges() {
    let mut p = Params::default();
    p.set("wr_hmin", json!(50)).unwrap();
    assert!(p.number("wr_hmax") >= p.number("wr_hmin"));
    p.set("wr_hmax", json!(2)).unwrap();
    assert!(p.number("wr_hmax") >= p.number("wr_hmin"));
}

#[test]
fn json_file_roundtrip_and_atomic_invalid_update() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("settings.json");
    let mut p = Params::default();
    p.set("future", json!([1, 2, 3])).unwrap();
    p.save(&path).unwrap();
    let q = Params::load(&path).unwrap();
    assert_eq!(p.to_value(), q.to_value());
    let before = p.to_value();
    assert!(p
        .update(&json!({"tape_noise":0.2,"tv_decoder":"unknown"}))
        .is_err());
    assert_eq!(p.to_value(), before);
    assert!(Params::from_value(json!([])).is_err());
}

#[test]
fn controls_are_hidden_unless_their_parent_setting_is_active() {
    let mut p = Params::default();
    // Default: RF switch, snow strength 0.
    assert!(p.is_active("hs_advance") && p.is_active("hs_phase_deg"));
    assert!(!p.is_active("hs_lines") && !p.is_active("hs_snow_us"));
    assert!(!p.is_active("hs_residual_width_px") && !p.is_active("hs_residual_follow"));
    p.set("hs_residual", json!(0.5)).unwrap();
    assert!(p.is_active("hs_residual_bottom_px") && p.is_active("hs_residual_follow"));
    assert!(p.is_active("hs_residual_speed_px") && p.is_active("hs_residual_jitter_px"));
    p.set("hs_residual_follow", json!(true)).unwrap();
    assert!(!p.is_active("hs_residual_bottom_px"));
    p.set("hs_residual_motion", json!("Stationary")).unwrap();
    assert!(!p.is_active("hs_residual_speed_px") && !p.is_active("hs_residual_jitter_px"));
    // Legacy overlay hides every RF-only control and shows the legacy ones.
    p.set("hs_model", json!("legacy overlay")).unwrap();
    for k in ["hs_advance", "hs_servo_lines", "hs_phase_deg", "hs_gap_us", "hs_residual", "hs_residual_follow"] {
        assert!(!p.is_active(k), "{k}");
    }
    assert!(p.is_active("hs_lines") && p.is_active("hs_snow") && p.is_active("hs_noise"));
    assert!(!p.is_active("hs_snow_us"));
    p.set("hs_snow", json!(0.4)).unwrap();
    assert!(p.is_active("hs_snow_us") && p.is_active("hs_snow_sweep"));
    // Off hides everything except the model selector itself.
    p.set("hs_model", json!("off")).unwrap();
    assert!(p.is_active("hs_model"));
    for s in specs().iter().filter(|s| s.group == "6b Head switching" && s.key != "hs_model") {
        assert!(!p.is_active(&s.key), "{}", s.key);
    }
    // VHS bypass hides every tape group but keeps encoder, output and TV.
    p.set("bypass_tape", json!(true)).unwrap();
    assert!(!p.is_active("tape_noise") && !p.is_active("dropout_rate") && !p.is_active("wr_travel"));
    assert!(p.is_active("bypass_tape") && p.is_active("out_gain") && p.is_active("tv_hue"));
    p.set("bypass_tape", json!(false)).unwrap();
    // Travelling band and wrinkle dependants.
    assert!(!p.is_active("wr_period") && !p.is_active("wrinkle_height"));
    p.set("wr_travel", json!(true)).unwrap();
    assert!(p.is_active("wr_period") && p.is_active("wr_white") && !p.is_active("wr_grey") && !p.is_active("wr_gap"));
    p.set("wr_style", json!("grey fade")).unwrap();
    assert!(p.is_active("wr_grey") && !p.is_active("wr_white"));
    p.set("wrinkle", json!(0.5)).unwrap();
    assert!(p.is_active("wrinkle_height") && !p.is_active("wrinkle_gap"));
}

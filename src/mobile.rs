//! Platform-independent frame plumbing for the mobile (Android) build.
//!
//! The desktop build gets 720x576 RGB frames from an FFmpeg subprocess. On
//! Android the platform codecs deliver I420 frames at the source resolution,
//! so this module does the equivalent of `fit_filter` and the field split in
//! plain Rust, and converts the engine's RGB output back to I420.
use crate::{
    media::vertical_filter,
    model::{self, Params},
    renderer::{double_field, weave_fields, FieldMode},
    signal::{Engine, HEIGHT, WIDTH},
};
use std::borrow::Cow;

const CANVAS_W: f64 = 768.0; // 4:3 canvas before the 720-sample storage squeeze
const CANVAS_H: f64 = 576.0;

fn clamp8(v: f32) -> u8 {
    v.round().clamp(0.0, 255.0) as u8
}

/// Convert a packed I420 frame (`w*h` Y, then `w/2*h/2` U, then V) to RGB,
/// rotate by `rotation` degrees clockwise (0/90/180/270) and fit it into the
/// 720x576 PAL canvas using the same `fit` / `crop` / `stretch` modes as the
/// desktop build. `bt709` selects the matrix (use it for HD sources).
pub fn i420_to_canvas(
    i420: &[u8],
    w: usize,
    h: usize,
    rotation: u32,
    aspect: &str,
    bt709: bool,
    out: &mut [u8],
) -> Result<(), String> {
    if w < 2 || h < 2 || w % 2 != 0 || h % 2 != 0 {
        return Err(format!("Unsupported frame size {w}x{h}"));
    }
    if i420.len() != w * h * 3 / 2 {
        return Err(format!("Expected {} I420 bytes, got {}", w * h * 3 / 2, i420.len()));
    }
    if out.len() != WIDTH * HEIGHT * 3 {
        return Err("Canvas buffer has the wrong size".into());
    }
    if !matches!(rotation, 0 | 90 | 180 | 270) {
        return Err("Rotation must be 0, 90, 180 or 270".into());
    }
    let (kr, kb) = if bt709 { (0.2126f32, 0.0722f32) } else { (0.299, 0.114) };
    let kg = 1.0 - kr - kb;
    let (y_plane, rest) = i420.split_at(w * h);
    let (u_plane, v_plane) = rest.split_at(w * h / 4);
    // Fetch a source pixel as RGB (floats 0..255), coordinates already clamped.
    let rgb_at = |x: usize, y: usize| -> [f32; 3] {
        let yy = (y_plane[y * w + x] as f32 - 16.0) * (255.0 / 219.0);
        let ci = (y / 2) * (w / 2) + x / 2;
        let cb = (u_plane[ci] as f32 - 128.0) * (255.0 / 224.0);
        let cr = (v_plane[ci] as f32 - 128.0) * (255.0 / 224.0);
        let r = yy + 2.0 * (1.0 - kr) * cr;
        let b = yy + 2.0 * (1.0 - kb) * cb;
        let g = (yy - kr * r - kb * b) / kg;
        [r, g, b]
    };
    // Size of the picture after rotation, and a map from rotated to source coords.
    let (rw, rh) = if rotation % 180 == 90 { (h, w) } else { (w, h) };
    let (rwf, rhf) = (rw as f64, rh as f64);
    let (dw, dh) = match aspect {
        "stretch" => (CANVAS_W, CANVAS_H),
        "crop" => {
            let s = (CANVAS_W / rwf).max(CANVAS_H / rhf);
            (rwf * s, rhf * s)
        }
        _ => {
            let s = (CANVAS_W / rwf).min(CANVAS_H / rhf);
            (rwf * s, rhf * s)
        }
    };
    let (ox, oy) = ((CANVAS_W - dw) / 2.0, (CANVAS_H - dh) / 2.0);
    let sample = |fx: f64, fy: f64| -> [f32; 3] {
        // fx, fy: continuous coordinates in the rotated picture (pixel centres at +0.5).
        let fx = (fx - 0.5).clamp(0.0, rwf - 1.0);
        let fy = (fy - 0.5).clamp(0.0, rhf - 1.0);
        let (x0, y0) = (fx.floor() as usize, fy.floor() as usize);
        let (x1, y1) = ((x0 + 1).min(rw - 1), (y0 + 1).min(rh - 1));
        let (tx, ty) = ((fx - x0 as f64) as f32, (fy - y0 as f64) as f32);
        let src = |rx: usize, ry: usize| match rotation {
            0 => rgb_at(rx, ry),
            90 => rgb_at(ry, h - 1 - rx),
            180 => rgb_at(w - 1 - rx, h - 1 - ry),
            _ => rgb_at(w - 1 - ry, rx),
        };
        let (a, b, c, d) = (src(x0, y0), src(x1, y0), src(x0, y1), src(x1, y1));
        let mut o = [0.0; 3];
        for i in 0..3 {
            let top = a[i] + (b[i] - a[i]) * tx;
            let bot = c[i] + (d[i] - c[i]) * tx;
            o[i] = top + (bot - top) * ty;
        }
        o
    };
    for py in 0..HEIGHT {
        for px in 0..WIDTH {
            // Canvas position in the 768x576 space (storage is 720 wide).
            let cx = (px as f64 + 0.5) * CANVAS_W / WIDTH as f64;
            let cy = py as f64 + 0.5;
            let o = (py * WIDTH + px) * 3;
            if cx < ox || cx >= ox + dw || cy < oy || cy >= oy + dh {
                out[o..o + 3].fill(0);
                continue;
            }
            let c = sample((cx - ox) * rwf / dw, (cy - oy) * rhf / dh);
            out[o] = clamp8(c[0]);
            out[o + 1] = clamp8(c[1]);
            out[o + 2] = clamp8(c[2]);
        }
    }
    Ok(())
}

/// 720x576 RGB -> packed I420, BT.601 limited range (the PAL standard).
pub fn canvas_to_i420(rgb: &[u8]) -> Result<Vec<u8>, String> {
    if rgb.len() != WIDTH * HEIGHT * 3 {
        return Err("Canvas buffer has the wrong size".into());
    }
    let mut out = vec![0u8; WIDTH * HEIGHT * 3 / 2];
    let (yp, rest) = out.split_at_mut(WIDTH * HEIGHT);
    let (up, vp) = rest.split_at_mut(WIDTH * HEIGHT / 4);
    for y in 0..HEIGHT {
        for x in 0..WIDTH {
            let i = (y * WIDTH + x) * 3;
            let (r, g, b) = (rgb[i] as f32, rgb[i + 1] as f32, rgb[i + 2] as f32);
            yp[y * WIDTH + x] = clamp8(16.0 + 0.2568 * r + 0.5041 * g + 0.0979 * b);
        }
    }
    for y in 0..HEIGHT / 2 {
        for x in 0..WIDTH / 2 {
            let (mut r, mut g, mut b) = (0.0, 0.0, 0.0);
            for (dy, dx) in [(0, 0), (0, 1), (1, 0), (1, 1)] {
                let i = ((2 * y + dy) * WIDTH + 2 * x + dx) * 3;
                r += rgb[i] as f32;
                g += rgb[i + 1] as f32;
                b += rgb[i + 2] as f32;
            }
            let (r, g, b) = (r / 4.0, g / 4.0, b / 4.0);
            up[y * (WIDTH / 2) + x] = clamp8(128.0 - 0.1482 * r - 0.2910 * g + 0.4392 * b);
            vp[y * (WIDTH / 2) + x] = clamp8(128.0 + 0.4392 * r - 0.3678 * g - 0.0714 * b);
        }
    }
    Ok(out)
}

/// Resolve UI settings without initializing the signal engine.
pub fn settings(preset: &str, overrides: &str) -> Result<Params, String> {
    let mut params = Params::default();
    if !preset.is_empty() {
        params.apply_preset(preset)?;
    }
    if !overrides.trim().is_empty() {
        let mut values: serde_json::Value =
            serde_json::from_str(overrides).map_err(|e| e.to_string())?;
        let macros = values.as_object_mut().and_then(|values| values.remove("macros"));
        if let Some(macros) = macros.as_ref().and_then(|m| m.as_object()) {
            for (name, amount) in macros {
                params.set_macro(name, amount.as_f64().ok_or("Macro amount must be a number")?)?;
            }
        }
        params.update(&values)?;
    }
    Ok(params)
}

pub fn control_state(preset: &str, overrides: &str) -> Result<serde_json::Value, String> {
    let params = settings(preset, overrides)?;
    let visible: Vec<_> = model::specs().iter()
        .filter(|s| params.is_active(&s.key))
        .map(|s| &s.key)
        .collect();
    let macros: serde_json::Map<_, _> = model::macros().iter().map(|(name, spec)| {
        let keys: Vec<_> = spec[2].as_object().unwrap().keys().collect();
        (name.clone(), serde_json::json!({
            "position": params.macro_position(name),
            "keys": keys,
        }))
    }).collect();
    Ok(serde_json::json!({ "values": params.to_value(), "visible": visible, "macros": macros }))
}

/// Immutable settings and engine shared across the export workers.
pub struct Session {
    engine: Engine,
    params: Params,
    mode: FieldMode,
}

impl Session {
    pub fn new(preset: &str, overrides: &str) -> Result<Self, String> {
        let params = settings(preset, overrides)?;
        let mode = FieldMode::from_params(&params);
        Ok(Self { engine: Engine::new(params.clone())?, params, mode })
    }

    pub fn aspect(&self) -> String {
        self.params.choice("aspect").to_owned()
    }

    /// Render one canvas at the given output frame index.
    pub fn render(&self, canvas: &[u8], frame_idx: u64) -> Result<Vec<u8>, String> {
        self.render_pair(canvas, None, frame_idx, false)
    }

    /// The second canvas, when supplied, is sampled 20 ms after the first.
    pub fn render_pair(
        &self,
        first: &[u8],
        second: Option<&[u8]>,
        frame_idx: u64,
        parallel: bool,
    ) -> Result<Vec<u8>, String> {
        let canvas_size = WIDTH * HEIGHT * 3;
        if first.len() != canvas_size || second.is_some_and(|s| s.len() != canvas_size) {
            return Err("Canvas buffer has the wrong size".into());
        }
        let amount = self.params.number("vfilter");
        let first = filtered_canvas(first, amount);
        let second = second.map(|canvas| filtered_canvas(canvas, amount));
        let row = WIDTH * 3;
        let field = |fi, canvas: &[u8]| {
            let mut rgb = Vec::with_capacity(canvas_size / 2);
            for lines in canvas.chunks_exact(2 * row) {
                rgb.extend_from_slice(&lines[fi * row..(fi + 1) * row]);
            }
            rgb
        };
        let second_canvas = second.as_deref().unwrap_or(&first);
        if self.mode != FieldMode::Interlaced {
            let fi = usize::from(self.mode == FieldMode::Second);
            let canvas = if fi == 0 { first.as_ref() } else { second_canvas };
            return double_field(&self.engine.render_field(&field(fi, canvas), fi, frame_idx, false)?.rgb);
        }
        let a = field(0, &first);
        let b = field(1, second_canvas);
        if parallel {
            std::thread::scope(|scope| {
                let first = scope.spawn(|| self.engine.render_field(&a, 0, frame_idx, false));
                let second = self.engine.render_field(&b, 1, frame_idx, false);
                let first = first.join().map_err(|_| "Preview field renderer panicked")??;
                weave_fields(&first.rgb, &second?.rgb)
            })
        } else {
            let first = self.engine.render_field(&a, 0, frame_idx, false)?;
            let second = self.engine.render_field(&b, 1, frame_idx, false)?;
            weave_fields(&first.rgb, &second.rgb)
        }
    }
}

fn filtered_canvas(canvas: &[u8], amount: f64) -> Cow<'_, [u8]> {
    if amount <= 0.0 {
        return Cow::Borrowed(canvas);
    }
    let mut frame = canvas.to_vec();
    vertical_filter(&mut frame, amount);
    Cow::Owned(frame)
}

pub fn preset_names() -> Vec<String> {
    crate::model::presets().keys().cloned().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn grey_survives_i420_roundtrip() {
        let (w, h) = (64, 48);
        let mut i420 = vec![128u8; w * h * 3 / 2];
        i420[..w * h].fill(126); // mid grey luma, neutral chroma
        let mut canvas = vec![0u8; WIDTH * HEIGHT * 3];
        i420_to_canvas(&i420, w, h, 0, "stretch", false, &mut canvas).unwrap();
        let mid = (HEIGHT / 2 * WIDTH + WIDTH / 2) * 3;
        for c in 0..3 {
            assert!((canvas[mid + c] as i32 - 128).abs() <= 2, "{:?}", &canvas[mid..mid + 3]);
        }
        let back = canvas_to_i420(&canvas).unwrap();
        assert!((back[HEIGHT / 2 * WIDTH + WIDTH / 2] as i32 - 126).abs() <= 2);
        assert!((back[WIDTH * HEIGHT] as i32 - 128).abs() <= 2);
    }

    #[test]
    fn fit_letterboxes_wide_video_and_rotation_swaps_axes() {
        let (w, h) = (160, 90); // 16:9 -> black bars top and bottom
        let i420 = {
            let mut v = vec![128u8; w * h * 3 / 2];
            v[..w * h].fill(235);
            v
        };
        let mut c = vec![9u8; WIDTH * HEIGHT * 3];
        i420_to_canvas(&i420, w, h, 0, "fit", false, &mut c).unwrap();
        assert_eq!(c[(2 * WIDTH + 10) * 3], 0); // top bar
        assert!(c[(HEIGHT / 2 * WIDTH + 10) * 3] > 240); // picture
        // A 90 degree rotated 16:9 frame is portrait: bars left and right.
        i420_to_canvas(&i420, w, h, 90, "fit", false, &mut c).unwrap();
        assert_eq!(c[(HEIGHT / 2 * WIDTH + 5) * 3], 0);
        assert!(c[(HEIGHT / 2 * WIDTH + WIDTH / 2) * 3] > 240);
    }

    #[test]
    fn preview_and_export_use_the_same_temporal_fields() {
        let s = Session::new("", r#"{"bypass_tape":true,"vfilter":0}"#).unwrap();
        let first = vec![70; WIDTH * HEIGHT * 3];
        let second = vec![170; WIDTH * HEIGHT * 3];
        let export = s.render_pair(&first, Some(&second), 9, false).unwrap();
        let preview = s.render_pair(&first, Some(&second), 9, true).unwrap();
        let same_canvas = s.render(&first, 9).unwrap();
        let row = WIDTH * 3;
        assert_eq!(preview, export);
        assert_eq!(&export[..row], &same_canvas[..row]);
        assert_ne!(&export[row..2 * row], &same_canvas[row..2 * row]);
    }

    #[test]
    fn advanced_values_can_override_a_macro() {
        let p = settings("", r#"{"macros":{"smear":50},"track_smear":0.8}"#).unwrap();
        assert_eq!(p.number("track_band"), 0.4);
        assert_eq!(p.number("track_smear"), 0.8);
    }

    #[test]
    fn mobile_controls_follow_the_desktop_head_switch_rules() {
        let visible = |overrides: &str| {
            control_state("", overrides).unwrap()["visible"].as_array().unwrap().clone()
        };
        let rf = visible(r#"{"hs_model":"RF switch","hs_residual":0.5,"hs_residual_follow":true}"#);
        assert!(rf.contains(&serde_json::json!("hs_residual_follow")));
        assert!(!rf.contains(&serde_json::json!("hs_residual_bottom_px")));
        let legacy = visible(r#"{"hs_model":"legacy overlay"}"#);
        assert!(legacy.contains(&serde_json::json!("hs_lines")));
        assert!(!legacy.contains(&serde_json::json!("hs_advance")));
        let off = visible(r#"{"hs_model":"off"}"#);
        assert!(off.contains(&serde_json::json!("hs_model")));
        assert!(!off.contains(&serde_json::json!("hs_lines")));
    }

    #[test]
    fn session_renders_a_frame() {
        let s = Session::new("PAL VHS / SP - home recording", "").unwrap();
        let canvas = vec![100u8; WIDTH * HEIGHT * 3];
        let out = s.render(&canvas, 0).unwrap();
        assert_eq!(out.len(), WIDTH * HEIGHT * 3);
        assert!(preset_names().len() > 10);
        Session::new("", r#"{"macros":{"wear":50,"crease":20}}"#).unwrap();
        assert!(Session::new("", r#"{"macros":{"nope":1}}"#).is_err());
    }
}

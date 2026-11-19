//! Bundled parameter registry, presets and backwards-compatible JSON settings.
use serde::Deserialize;
use serde_json::{json, Value};
use std::{collections::BTreeMap, path::Path, sync::OnceLock};
#[derive(Clone, Debug, Deserialize, serde::Serialize)]
pub struct Spec {
    pub key: String,
    pub label: String,
    pub group: String,
    pub kind: String,
    pub default: Value,
    pub lo: Option<Value>,
    pub hi: Option<Value>,
    pub step: Option<f64>,
    pub tip: String,
}
pub fn specs() -> &'static [Spec] {
    static S: OnceLock<Vec<Spec>> = OnceLock::new();
    S.get_or_init(|| {
        serde_json::from_str(include_str!("../assets/schema.json")).expect("bundled schema")
    })
}
pub fn presets() -> &'static BTreeMap<String, Value> {
    static S: OnceLock<BTreeMap<String, Value>> = OnceLock::new();
    S.get_or_init(|| {
        serde_json::from_str(include_str!("../assets/presets.json")).expect("bundled presets")
    })
}
pub fn decks() -> &'static BTreeMap<String, Value> {
    static S: OnceLock<BTreeMap<String, Value>> = OnceLock::new();
    S.get_or_init(|| {
        serde_json::from_str(include_str!("../assets/decks.json")).expect("bundled decks")
    })
}
pub fn macros() -> &'static BTreeMap<String, Value> {
    static S: OnceLock<BTreeMap<String, Value>> = OnceLock::new();
    S.get_or_init(|| {
        serde_json::from_str(include_str!("../assets/macros.json")).expect("bundled macros")
    })
}
#[derive(Clone, Debug)]
pub struct Params {
    values: BTreeMap<String, Value>,
}
impl Default for Params {
    fn default() -> Self {
        Self {
            values: specs()
                .iter()
                .map(|s| (s.key.clone(), s.default.clone()))
                .collect(),
        }
    }
}
impl Params {
    pub fn number(&self, key: &str) -> f64 {
        self.values.get(key).and_then(Value::as_f64).unwrap_or(0.0)
    }
    pub fn boolean(&self, key: &str) -> bool {
        self.values
            .get(key)
            .and_then(Value::as_bool)
            .unwrap_or(false)
    }
    pub fn choice(&self, key: &str) -> &str {
        self.values.get(key).and_then(Value::as_str).unwrap_or("")
    }
    pub fn set(&mut self, key: &str, mut value: Value) -> Result<(), String> {
        if [
            "hs_residual_forward_frames",
            "hs_residual_backward_frames",
            "hs_residual_forward_px",
            "hs_residual_backward_px",
        ]
        .contains(&key)
        {
            return Ok(());
        }
        if key == "hs_residual_motion" && value == "Forward/back steps" {
            value = json!("Drift + jitter");
        }
        if let Some(s) = specs().iter().find(|s| s.key == key) {
            value = match s.kind.as_str() {
                "float" | "int" => {
                    let n = value
                        .as_f64()
                        .or_else(|| value.as_str().and_then(|v| v.parse().ok()))
                        .ok_or_else(|| format!("{key}: expected number"))?;
                    if !n.is_finite() {
                        return Err(format!("{key}: value must be finite"));
                    }
                    let n = if s.kind == "int" { n.trunc() } else { n };
                    let n = n.clamp(
                        s.lo.as_ref().and_then(Value::as_f64).unwrap(),
                        s.hi.as_ref().and_then(Value::as_f64).unwrap(),
                    );
                    if s.kind == "int" {
                        json!(n as i64)
                    } else {
                        json!(n)
                    }
                }
                "bool" => json!(match &value {
                    Value::Null => false,
                    Value::Bool(b) => *b,
                    Value::Number(n) => n.as_f64().unwrap_or(0.0) != 0.0,
                    Value::String(s) => !s.is_empty(),
                    Value::Array(a) => !a.is_empty(),
                    Value::Object(o) => !o.is_empty(),
                }),
                "choice" => {
                    if !s
                        .lo
                        .as_ref()
                        .and_then(Value::as_array)
                        .map(|a| a.contains(&value))
                        .unwrap_or(false)
                    {
                        return Err(format!("{key}: invalid choice {value}"));
                    }
                    value
                }
                _ => value,
            };
        }
        self.values.insert(key.to_owned(), value);
        // Keep travelling-band bounds ordered, including direct Advanced edits.
        if key == "wr_hmin" && self.number("wr_hmin") > self.number("wr_hmax") {
            self.values
                .insert("wr_hmax".into(), json!(self.number("wr_hmin")));
        }
        if key == "wr_hmax" && self.number("wr_hmin") > self.number("wr_hmax") {
            self.values
                .insert("wr_hmin".into(), json!(self.number("wr_hmax")));
        }
        Ok(())
    }
    pub fn to_value(&self) -> Value {
        serde_json::to_value(&self.values).expect("JSON values")
    }
    pub fn from_value(value: Value) -> Result<Self, String> {
        let mut p = Self::default();
        p.update(&value)?;
        Ok(p)
    }
    pub fn update(&mut self, value: &Value) -> Result<(), String> {
        let map = value
            .as_object()
            .ok_or("Parameter file must contain a JSON object")?;
        let mut next = self.clone();
        for (k, v) in map {
            next.set(k, v.clone())?;
        }
        *self = next;
        Ok(())
    }
    pub fn load(path: impl AsRef<Path>) -> Result<Self, String> {
        let bytes = std::fs::read(path).map_err(|e| e.to_string())?;
        Self::from_value(serde_json::from_slice(&bytes).map_err(|e| e.to_string())?)
    }
    pub fn save(&self, path: impl AsRef<Path>) -> Result<(), String> {
        std::fs::write(
            path,
            serde_json::to_vec_pretty(&self.to_value()).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())
    }
    pub fn apply_preset(&mut self, name: &str) -> Result<(), String> {
        let data = presets()
            .get(name)
            .ok_or_else(|| format!("Unknown preset: {name}"))?;
        let mut p = Self::default();
        p.update(data)?;
        *self = p;
        Ok(())
    }
    pub fn apply_deck(&mut self, name: &str) -> Result<(), String> {
        self.update(
            decks()
                .get(name)
                .ok_or_else(|| format!("Unknown deck: {name}"))?,
        )
    }
    pub fn set_macro(&mut self, name: &str, amount: f64) -> Result<(), String> {
        if !amount.is_finite() {
            return Err("Macro amount must be finite".into());
        }
        let m = macros()
            .get(name)
            .ok_or_else(|| format!("Unknown macro: {name}"))?;
        let t = amount.clamp(0.0, 100.0) / 100.0;
        for (k, v) in m[2].as_object().unwrap() {
            let a = v[0].as_f64().unwrap();
            let b = v[1].as_f64().unwrap();
            self.set(k, json!(a + (b - a) * t))?;
        }
        Ok(())
    }
    /// Whether `key` currently has any effect, given the other settings.
    /// Used by the desktop UI to hide controls whose parent switch, model,
    /// style or strength is off. Unknown keys are always active.
    pub fn is_active(&self, key: &str) -> bool {
        let n = |k: &str| self.number(k);
        let on = |k: &str| n(k) > 0.0;
        let group = specs()
            .iter()
            .find(|s| s.key == key)
            .map(|s| s.group.as_str())
            .unwrap_or("");
        let tape_group = matches!(
            group.split_whitespace().next(),
            Some("3" | "4" | "5" | "6" | "6b" | "7" | "7b" | "8")
        );
        if tape_group && self.boolean("bypass_tape") {
            return false;
        }
        let model = self.choice("hs_model");
        let rf = model == "RF switch";
        let legacy = model == "legacy overlay";
        let hs = rf || legacy;
        let shift = hs && n("hs_shift_us") != 0.0;
        let snow = rf && on("hs_residual");
        let motion = self.choice("hs_residual_motion");
        let tracking_noise = n("tracking") != 0.0 || on("track_band");
        let travel = self.boolean("wr_travel");
        match key {
            // Head switching: RF model only.
            "hs_advance" | "hs_servo_lines" | "hs_phase_deg" | "hs_residual" => rf,
            "hs_gap_us" | "hs_recovery_us" => rf && on("hs_noise"),
            "hs_residual_follow"
            | "hs_residual_width_px"
            | "hs_residual_height"
            | "hs_residual_x"
            | "hs_residual_motion"
            | "hs_residual_sweep_px" => snow,
            "hs_residual_bottom_px" => snow && !self.boolean("hs_residual_follow"),
            "hs_residual_speed_px" => snow && matches!(motion, "Drift" | "Drift + jitter"),
            "hs_residual_jitter_px" => snow && matches!(motion, "Random jumps" | "Drift + jitter"),
            // Head switching: legacy overlay only.
            "hs_lines" | "hs_snow" => legacy,
            "hs_snow_lines" | "hs_snow_us" | "hs_snow_speed" | "hs_snow_pos"
            | "hs_snow_jitter" | "hs_snow_sweep" => legacy && on("hs_snow"),
            // Head switching: shared by both models, none when off.
            "hs_noise" | "hs_shift_us" | "hs_jitter_us" | "hs_mask_lines" => hs,
            "hs_shift_var" | "hs_random" => shift,
            "hs_shift_rate" => shift && on("hs_shift_var"),
            // Timebase.
            "tb_wobble_hz" => on("tb_wobble_ns"),
            "skew_random" => n("tb_skew_us") != 0.0,
            // Dropouts and tracking.
            "dropout_len_us" | "dropout_depth" => on("dropout_rate"),
            "track_speed" | "track_accel" | "track_wobble" | "track_smear" => on("track_band"),
            "snow_streaks" | "snow_grain" => tracking_noise,
            "snow_streak_us" => tracking_noise || on("snow_sparse"),
            // Travelling white band.
            "wr_gap" | "wr_hold" => travel && n("wr_count") > 1.0,
            "wr_grey" => travel && self.choice("wr_style") == "grey fade",
            "wr_white" => travel && self.choice("wr_style") == "white",
            k if k.starts_with("wr_") && k != "wr_travel" => travel,
            // Wrinkle and colour glitches.
            "wrinkle_gap" => on("wrinkle") && n("wrinkle_count") > 1.0,
            k if k.starts_with("wrinkle_") => on("wrinkle"),
            "cu_glitch_period" | "cu_glitch_len" => on("cu_glitch"),
            // Output.
            "ghost_ns" => on("ghost"),
            _ => true,
        }
    }
    pub fn macro_position(&self, name: &str) -> f64 {
        let Some(m) = macros().get(name) else {
            return 0.0;
        };
        let key = match name {
            "wear" => "tape_wear",
            "colour" => "chroma_delay_ns",
            "unstable" => "tb_jitter_ns",
            "smear" => "track_band",
            "crease" => "wrinkle",
            _ => return 0.0,
        };
        let v = &m[2][key];
        let a = v[0].as_f64().unwrap();
        let b = v[1].as_f64().unwrap();
        (((self.number(key) - a) / (b - a)).clamp(0.0, 1.0) * 100.0).round()
    }
}

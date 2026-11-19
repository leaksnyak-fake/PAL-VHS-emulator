//! Field assembly shared by preview and offline export.
use crate::{
    model::Params,
    signal::{Engine, FIELD_HEIGHT, WIDTH},
};
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FieldMode {
    Interlaced,
    First,
    Second,
}
impl FieldMode {
    pub fn from_params(p: &Params) -> Self {
        match p.choice("export_fields") {
            "field 1 only" => Self::First,
            "field 2 only" => Self::Second,
            _ => Self::Interlaced,
        }
    }
    pub fn is_interlaced(self) -> bool {
        self == Self::Interlaced
    }
}

/// A monotonic token invalidates results when the source or controls change.
#[derive(Default)]
pub struct Generation(u64);
impl Generation {
    pub fn advance(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(1);
        self.0
    }
    pub fn accepts(&self, id: u64) -> bool {
        self.0 == id
    }
}

pub struct FrameOutput {
    pub rgb: Vec<u8>,
    pub taps: BTreeMap<String, Vec<f64>>,
}

fn check_field(field: &[u8]) -> Result<(), String> {
    if field.len() != WIDTH * FIELD_HEIGHT * 3 {
        Err(format!(
            "Expected {} RGB field bytes, received {}",
            WIDTH * FIELD_HEIGHT * 3,
            field.len()
        ))
    } else {
        Ok(())
    }
}
pub fn weave_fields(first: &[u8], second: &[u8]) -> Result<Vec<u8>, String> {
    check_field(first)?;
    check_field(second)?;
    let row = WIDTH * 3;
    let mut out = vec![0; row * FIELD_HEIGHT * 2];
    for y in 0..FIELD_HEIGHT {
        out[2 * y * row..(2 * y + 1) * row].copy_from_slice(&first[y * row..(y + 1) * row]);
        out[(2 * y + 1) * row..(2 * y + 2) * row].copy_from_slice(&second[y * row..(y + 1) * row]);
    }
    Ok(out)
}
pub fn double_field(field: &[u8]) -> Result<Vec<u8>, String> {
    weave_fields(field, field)
}

pub fn render_frame(
    engine: &mut Engine,
    first: &[u8],
    second: &[u8],
    frame_idx: u64,
    mode: FieldMode,
    want_taps: bool,
) -> Result<FrameOutput, String> {
    match mode {
        FieldMode::Interlaced => {
            let a = engine.render_field(first, 0, frame_idx, want_taps)?;
            let b = engine.render_field(second, 1, frame_idx, false)?;
            Ok(FrameOutput {
                rgb: weave_fields(&a.rgb, &b.rgb)?,
                taps: a.taps,
            })
        }
        FieldMode::First | FieldMode::Second => {
            let fi = usize::from(mode == FieldMode::Second);
            let a = engine.render_field(
                if fi == 0 { first } else { second },
                fi,
                frame_idx,
                want_taps,
            )?;
            Ok(FrameOutput {
                rgb: double_field(&a.rgb)?,
                taps: a.taps,
            })
        }
    }
}

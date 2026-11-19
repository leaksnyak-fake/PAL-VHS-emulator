//! Pixel-accurate preview using the very same PAL/VHS signal engine as export.
//!
//! The two PAL fields can be processed on separate CPU cores: the signal model
//! is deterministic per (frame, field, seed), and neither field consumes state
//! from the other. This changes scheduling, not the DSP algorithms or settings.
//! A small RGB LRU avoids repeating expensive work when scrubbing backwards.
use crate::{
    model::Params,
    renderer::{self, FieldMode, FrameOutput},
    signal::{Engine, FIELD_HEIGHT, WIDTH},
};
use std::{collections::{BTreeMap, VecDeque}, thread};

const RGB_CACHE_CAPACITY: usize = 8;

pub struct AccuratePreview {
    engine: Engine,
    cache: VecDeque<(u64, FieldMode, Vec<u8>)>,
}

impl AccuratePreview {
    pub fn new(params: Params) -> Result<Self, String> {
        Ok(Self {
            engine: Engine::new(params)?,
            cache: VecDeque::with_capacity(RGB_CACHE_CAPACITY),
        })
    }

    /// The inputs are already 720x288 fields, vertically filtered and split
    /// by the GStreamer source. Do not apply that filter again here.
    /// Signal scopes always come from the real engine; cached RGB alone cannot
    /// satisfy a request for taps.
    pub fn render(
        &mut self,
        first: &[u8],
        second: &[u8],
        frame: u64,
        mode: FieldMode,
        want_taps: bool,
    ) -> Result<FrameOutput, String> {
        let expected = WIDTH * FIELD_HEIGHT * 3;
        if first.len() != expected || second.len() != expected {
            return Err(format!(
                "Expected two 720x288 RGB fields ({} bytes each), got {} and {}",
                expected, first.len(), second.len()
            ));
        }
        if !want_taps {
            if let Some(position) = self.cache.iter().position(|(i, m, _)| *i == frame && *m == mode) {
                let item = self.cache.remove(position).unwrap();
                let rgb = item.2.clone();
                self.cache.push_back(item);
                return Ok(FrameOutput { rgb, taps: BTreeMap::new() });
            }
        }

        let output = match mode {
            FieldMode::Interlaced => {
                // Engine is read-only during rendering. Reuse the same deck
                // calibration and PAL tables on both cores, without contention.
                let engine = &self.engine;
                let (top, bottom) = thread::scope(|scope| {
                    let top_thread = scope.spawn(|| engine.render_field(first, 0, frame, want_taps));
                    let bottom = engine.render_field(second, 1, frame, false);
                    let top = top_thread.join()
                        .map_err(|_| "Top-field signal renderer panicked".to_string())?;
                    Ok::<_, String>((top?, bottom?))
                })?;
                FrameOutput {
                    rgb: renderer::weave_fields(&top.rgb, &bottom.rgb)?,
                    taps: top.taps,
                }
            }
            FieldMode::First => {
                let top = self.engine.render_field(first, 0, frame, want_taps)?;
                FrameOutput { rgb: renderer::double_field(&top.rgb)?, taps: top.taps }
            }
            FieldMode::Second => {
                let bottom = self.engine.render_field(second, 1, frame, want_taps)?;
                FrameOutput { rgb: renderer::double_field(&bottom.rgb)?, taps: bottom.taps }
            }
        };
        // Do not cache large f64 waveform taps; they may occupy tens of MB.
        if let Some(position) = self.cache.iter().position(|(i, m, _)| *i == frame && *m == mode) {
            self.cache.remove(position);
        }
        self.cache.push_back((frame, mode, output.rgb.clone()));
        if self.cache.len() > RGB_CACHE_CAPACITY {
            self.cache.pop_front();
        }
        Ok(output)
    }
}

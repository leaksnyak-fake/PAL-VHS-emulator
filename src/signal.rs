//! Native PAL composite / VHS waveform engine. Random model: native-v1.
//! Timing preserves the reference's whole-line approximation of PAL fields.
mod damage;
mod pal;
mod tape;
use crate::{dsp::*, model::Params};
use std::{collections::BTreeMap, sync::{Arc, OnceLock}};
pub const WIDTH: usize = 720;
pub const HEIGHT: usize = 576;
pub const FIELD_HEIGHT: usize = 288;
pub const SPL: usize = 1135;
pub const FS: f64 = 17_734_375.0;
pub const FSC: f64 = 4_433_618.75;
pub const FCU: f64 = 626_953.125;
pub const US: f64 = FS / 1e6;
const ACTIVE_FIRST: usize = 23;
const ACTIVE_START: usize = 186;
const ACTIVE_LEN: usize = 922;
const BURST_START: usize = 99;
const BURST_LEN: usize = 40;
const SYNC_W: usize = 83;
const CPL: f64 = 283.7516;
const TAU: f64 = std::f64::consts::TAU;
const PI: f64 = std::f64::consts::PI;
pub struct FieldOutput {
    pub rgb: Vec<u8>,
    pub taps: BTreeMap<String, Vec<f64>>,
}
pub struct Engine {
    p: Params,
    deck: tape::Deck,
    decoder: pal::Decoder,
    bases: [Arc<pal::Basis>; 8],
}
impl Engine {
    pub fn new(p: Params) -> Result<Self, String> {
        // These 8 PAL carrier tables depend only on phase/cadence, never on
        // controls or clip content. Reuse them across fields and threads.
        static BASES: OnceLock<[Arc<pal::Basis>; 8]> = OnceLock::new();
        let bases = BASES.get_or_init(|| std::array::from_fn(|i| {
            Arc::new(pal::Basis::new((i / 2) as u64, i % 2))
        })).clone();
        let decoder = pal::Decoder::new(&p, bases[1].as_ref());
        let deck = tape::Deck::new(&p);
        Ok(Self {
            p,
            deck,
            decoder,
            bases,
        })
    }
    pub fn render_field(
        &self,
        rgb: &[u8],
        fi: usize,
        frame_idx: u64,
        want_taps: bool,
    ) -> Result<FieldOutput, String> {
        if fi > 1 {
            return Err("Field index must be 0 or 1".into());
        }
        if rgb.len() != WIDTH * FIELD_HEIGHT * 3 {
            return Err(format!(
                "Expected {} packed RGB bytes, got {}",
                WIDTH * FIELD_HEIGHT * 3,
                rgb.len()
            ));
        }
        let basis = self.bases[(frame_idx as usize % 4) * 2 + fi].as_ref();
        let comp = pal::encode(Some(rgb), fi, &self.p, basis);
        let mut taps = BTreeMap::new();
        if want_taps {
            taps.insert("comp_in".into(), comp.clone());
        }
        let stream = if self.p.boolean("bypass_tape") {
            comp
        } else {
            self.deck.process(
                &comp,
                fi,
                frame_idx,
                &self.p,
                basis,
                if want_taps { Some(&mut taps) } else { None },
            )
        };
        let mut out = lowpass(self.p.number("out_bw") * 1e6, 2, FS).run(&stream);
        for x in &mut out {
            *x *= self.p.number("out_gain");
        }
        if self.p.number("ghost") > 0.0 {
            let d = (self.p.number("ghost_ns") * FS / 1e9).round() as usize;
            let old = out.clone();
            for (i, x) in out.iter_mut().enumerate() {
                *x += self.p.number("ghost") * old[i.saturating_sub(d)];
            }
        }
        let mut rng = Rng::new(&[self.p.number("seed") as u64, frame_idx, fi as u64, 9]);
        for x in &mut out {
            if self.p.number("out_noise") > 0.0 {
                *x += rng.normal() * self.p.number("out_noise");
            }
            *x = x.clamp(-0.6, 1.6);
        }
        let rgb = self.decoder.decode(&out, fi, &self.p, basis);
        if want_taps {
            taps.insert("comp_out".into(), out);
        }
        Ok(FieldOutput { rgb, taps })
    }
}
fn field_lines(fi: usize) -> usize {
    if fi == 0 {
        313
    } else {
        312
    }
}
fn rotation(line: usize, fi: usize, p: &Params) -> f64 {
    if p.choice("cu_phase_model") == "legacy 90deg" {
        (line % 4) as f64 * PI / 2.0
    } else if fi == 1 {
        -(line as f64 % 4.0) * PI / 2.0
    } else {
        0.0
    }
}
pub fn switch_line(p: &Params, lines: usize, fi: usize, frame: u64) -> f64 {
    if p.choice("hs_model") == "legacy overlay" {
        lines as f64 - p.number("hs_lines")
    } else {
        lines as f64 + 2.0 - p.number("hs_advance")
            + p.number("hs_servo_lines")
                * (TAU * 0.73 * (frame as f64 / 25.0 + fi as f64 * 0.02)).sin()
    }
}

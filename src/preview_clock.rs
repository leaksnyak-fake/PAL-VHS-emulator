//! Presentation clock: slow processing skips presentation frames, never time.
use std::time::Instant;

pub struct PlaybackClock {
    frame: u64,
    anchor: Option<Instant>,
}
impl Default for PlaybackClock {
    fn default() -> Self {
        Self::new()
    }
}
impl PlaybackClock {
    pub fn new() -> Self {
        Self {
            frame: 0,
            anchor: None,
        }
    }
    pub fn start(&mut self, frame: u64, now: Instant) {
        self.frame = frame;
        self.anchor = Some(now);
    }
    pub fn pause(&mut self) {
        self.anchor = None;
    }
    pub fn seek(&mut self, frame: u64, now: Instant) {
        self.frame = frame;
        if self.anchor.is_some() {
            self.anchor = Some(now);
        }
    }
    pub fn target(&self, now: Instant, n_frames: u64) -> u64 {
        let elapsed = self
            .anchor
            .map(|anchor| now.saturating_duration_since(anchor).as_nanos() / 40_000_000)
            .unwrap_or(0);
        self.frame
            .saturating_add(elapsed.min(u64::MAX as u128) as u64)
            .min(n_frames.saturating_sub(1))
    }
}

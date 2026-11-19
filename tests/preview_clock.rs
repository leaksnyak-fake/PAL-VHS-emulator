use pal_vhs::preview_clock::PlaybackClock;
use std::time::{Duration, Instant};
#[test]
fn late_frames_follow_elapsed_time_instead_of_slowing_the_clip() {
    let mut clock = PlaybackClock::new();
    let now = Instant::now();
    clock.start(10, now);
    assert_eq!(clock.target(now + Duration::from_millis(200), 100), 15);
    assert_eq!(clock.target(now + Duration::from_millis(400), 100), 20);
}
#[test]
fn seek_and_pause_reset_the_anchor_and_end_is_clamped() {
    let mut clock = PlaybackClock::new();
    let now = Instant::now();
    clock.start(0, now);
    clock.seek(50, now + Duration::from_secs(1));
    assert_eq!(clock.target(now + Duration::from_millis(1080), 100), 52);
    clock.pause();
    assert_eq!(clock.target(now + Duration::from_secs(8), 100), 50);
    clock.start(98, now);
    assert_eq!(clock.target(now + Duration::from_secs(1), 100), 99);
    assert_eq!(clock.target(now, 0), 0);
}

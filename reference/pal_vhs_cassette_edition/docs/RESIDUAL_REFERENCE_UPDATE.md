# Head-switch snow: original waveform restored

The previous revision used a rectangular RGB noise patch after TV decoding.
That change was rejected: it lost the soft, flowing streak of the original.
This revision restores the original snow algorithm's smoothed attack,
exponential decay, correlated grain, random length breathing and per-line fade.
The original Legacy overlay branch is unchanged.

RF mode now adds this one-dimensional snow waveform to played-back luma before
output filters and PAL TV decoding. Fractional horizontal positions are retained
on the signal grid. Filters soften the bright head and fading tail; there is no
post-decode RGB snow rectangle. Luma-demod and composite-output scope taps include
the streak. This is an artistic waveform model combined with the separate RF
switch model, not a calibrated physical demodulator simulation.

Use `Deck / Professional / narrow residual (user reference)` or Easy mode's
Apply deck selector. Applying a deck preserves tape wear and recording settings.

| Control | Professional reference |
|---|---|
| Head-switch snow strength | 0.6 |
| Snow width at 720 pixels | 9 nominal pixels |
| Snow height | 1 line per field; 2 available |
| Gap below band | 5 woven-frame rows |
| Base horizontal position | 0.12 |
| Motion | Forward/back steps |
| Forward/backward run | 3 frames / 1 frame |
| Forward/backward step | 12 / 12 pixels per frame |
| Position scatter | 10 pixels rms in random modes only |
| Sweep per additional line | 3 pixels |

Width sets the waveform's nominal duration. The original random length factor
(0.7 to 1.3), line taper and output filtering change its visible extent each
field. The tail may extend beyond that nominal width. It is deliberately not an
exact pixel bounding box. The user's 8-10-pixel professional and 10-15-pixel
cheaper-playback targets are appearance guides, not universal deck measurements.
Budget defaults to 15 pixels and two field lines; aligned domestic 2-head to
12 and two; domestic 4-head to 10 and one; high-end/professional to 9 and one.

Five rows below the band is an explicit woven-frame interpretation of the
reference; change the gap if the source counts field lines instead. One line
per field occupies two interleaved rows in a woven frame. Height never means
whole fields. Filters can spread light into nearby rows.

Stationary stops travel and jumps, while grain and length still change as fields
advance. Drift, Random jumps and Drift + jitter remain available. Motion reflects
at the edges; negative drift moves left. Frame index and seed determine both
position and texture, so seeking, preview and export agree. A paused frame stays
fixed. Image-line jitter remains zero in every preset and is independent of
snow movement. Strength zero, tape bypass and head-switch Off disable this snow;
the SWP black mask takes precedence.

Advanced / Head switching shows the working RF snow controls. Legacy controls
appear only in Legacy overlay mode. Easy mode retains strength and Moving.

`validation/liquid_snow_detail.png` shows full-pipeline synthetic bottom crops.
`validation/snow_motion.gif` contains 20 separately rendered complete DSP frames,
cropped and enlarged afterward. These are diagnostic renders, not real captures.

## Direction cadence controls

Forward/back steps advances right for the configured forward-frame count, then
left for the backward-frame count, repeatedly. Frame zero is the anchor; the
default subsequent displacements are +12, +12, +12, -12 pixels. Counts range
from 1 to 60 frames per run; each direction has its own 0-150-pixel step.
Both fields share a frame position; grain and length still breathe independently.
This mode excludes random scatter, so random jumps cannot hide the backward step.
Drift and scatter controls still affect their named modes. The edge reflection
can reverse apparent direction near a boundary. Absolute frame indexing keeps
seeking/export deterministic. Existing JSON does not silently change modes.

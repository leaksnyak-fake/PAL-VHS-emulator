"""PAL (625/50) timing constants and the sample grid used by the whole simulation.

The composite signal is simulated as a real sampled waveform at FS = 1135 * 15625 Hz
(~17.734 MHz, about 4 x fsc) so every line is exactly 1135 samples long.
Voltage convention (volts at a 75 ohm load, 1 V p-p composite):
    sync tip = -0.3, blanking = 0.0, peak white = +0.7
"""

FH = 15625.0                       # line frequency, Hz
LINE_US = 64.0                     # line period, microseconds
SPL = 1135                         # samples per line
FS = SPL * FH                      # sample rate, Hz  (17,734,375)
US = FS / 1e6                      # samples per microsecond (17.734)

CPL = 283.75 + 25.0 / FH           # subcarrier cycles per line (283.7516)
FSC = CPL * FH                     # 4,433,618.75 Hz

# vertical structure (625 lines / frame, two fields, TFF = top field first)
LINES_FRAME = 625
FIELD_LINES = (313, 312)           # field 1 (top, first) / field 2 (bottom)
ACTIVE_FIRST = 23                  # first active line index inside each field
ACTIVE_LINES = 288                 # active lines per field  -> 576 per frame
FRAME_H = 576
FRAME_W = 720

# horizontal structure (samples from the leading edge of sync at index 0)
SYNC_W = int(round(4.7 * US))      # 83
EQ_W = int(round(2.35 * US))       # equalising pulse width
BROAD_W = int(round(27.3 * US))    # broad (vsync) pulse width
BURST_START = int(round(5.6 * US))     # 99
BURST_LEN = int(round(10 / FSC * FS))  # ten subcarrier cycles = 40 samples
ACTIVE_START = int(round(10.5 * US))   # 186
ACTIVE_LEN = int(round(52.0 * US))     # 922
BACKPORCH_A = int(round(8.5 * US))     # clean back porch window for clamping
BACKPORCH_B = int(round(10.2 * US))

SYNC_LEVEL = -0.3
WHITE_LEVEL = 0.7
BURST_AMP = 0.15                   # amplitude (0.3 V peak to peak)

# VHS (PAL) recording
FM_SYNC_HZ = 3.8e6                 # FM carrier at sync tip
FM_DEV_HZ_PER_V = 1.0e6            # sync tip -> peak white = 1.0 V = 1.0 MHz (3.8 -> 4.8 MHz)
FCU = 40.125 * FH                  # colour-under carrier, 626,953.125 Hz

"""Regenerate reference fixtures with the preserved Python source and NumPy/SciPy/OpenCV.

Run with reference/pal_vhs_cassette_edition on PYTHONPATH. Runtime Rust tests
consume the generated data and do not require Python.
"""
from pathlib import Path
import json
import numpy as np
import scipy
import cv2
from pal_vhs import pal
from pal_vhs.params import Params
from pal_vhs.vhs import Deck

root = Path(__file__).parent
colors = np.array([[255,255,255],[255,255,0],[0,255,255],[0,255,0],
                   [255,0,255],[255,0,0],[0,0,255],[0,0,0]], dtype=np.uint8)
rgb = np.tile(np.repeat(colors, 90, axis=0)[None], (288,1,1))
metadata = {"numpy": np.__version__, "scipy": scipy.__version__, "opencv": cv2.__version__, "cases": {}}
for rate in ("1x", "2x"):
    p = Params()
    for key in ("tape_noise", "chroma_noise", "tb_jitter_ns", "tb_wobble_ns",
                "tb_skew_us", "hs_phase_deg", "hs_shift_us", "hs_noise", "dropout_rate", "out_noise"):
        setattr(p, key, 0)
    p.hs_model = "off"
    p.rf_rate = rate
    deck = Deck(p)
    for fi in (0, 1):
        comp = pal.encode_field(rgb.astype(np.float64)/255, fi, 0, p)
        taps = {}
        stream = deck.process_field(comp, fi, 0, taps)
        out = deck.output_stage(stream, fi, 0)
        decoded = (pal.decode_field(out, fi, 0, p)*255+0.5).astype(np.uint8)
        name = f"bars_{rate}_field{fi}"
        (root / f"{name}.rgb").write_bytes(decoded.tobytes())
        taps["comp_out"] = out
        metadata["cases"][name] = {
            "calibration": deck.calibration[fi],
            "taps": {k: {"stride": 97, "length": len(v.reshape(-1)),
                         "values": v.reshape(-1)[::97].tolist()} for k,v in taps.items()}
        }
        print(name, decoded.shape, flush=True)
(root / "signal_reference.json").write_text(json.dumps(metadata, separators=(",", ":")))

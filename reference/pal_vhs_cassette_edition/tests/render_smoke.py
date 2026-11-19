"""Optional real DSP smoke test. Requires the project's runtime dependencies.

python tests/render_smoke.py  (from project root)
Produces a synthetic test-pattern comparison, not a real-capture calibration.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from pal_vhs.params import Params, PRESETS
from pal_vhs.experience import CURATED
from pal_vhs.pipeline import render_frame


def main():
    # Vertical edges, colour bars, grayscale, and alternating fine lines exercise
    # chroma alignment, bandwidth loss, timing errors, and field weaving.
    frame = np.zeros((576, 720, 3), np.uint8)
    colours = [(220,220,220),(220,220,20),(20,220,220),(20,220,20),
               (220,20,220),(220,20,20),(20,20,220),(20,20,20)]
    for i, col in enumerate(colours):
        frame[:240,i*90:(i+1)*90] = col
    frame[240:400] = np.arange(720, dtype=float)[None,:,None]*255/719
    frame[400:, ::8] = 240
    frame[450:520, 100:620] = 140
    frame[470:500, 140:580] = 220
    images = []
    for name in CURATED:
        p = Params(**PRESETS[name]).to_dict()
        a, taps = render_frame(frame[::2], frame[1::2], 42, p)
        assert a.shape == (576,720,3) and a.dtype == np.uint8
        assert np.isfinite(a).all() and a.std() > 10
        assert taps is None
        images.append((name,a))
        print('PASS render:', name, flush=True)
    # Fixed seed/frame is identical despite a different render order/deck cache.
    name, reference = images[0]
    a, _ = render_frame(frame[::2], frame[1::2], 42, Params(**PRESETS[name]).to_dict())
    assert np.array_equal(a, reference)
    assert not np.array_equal(images[0][1], images[4][1])
    print('PASS deterministic re-render; tracking preset differs from fresh SP', flush=True)
    try:
        from PIL import Image, ImageDraw
        sheet = Image.new('RGB',(960,((len(images)+1)//2)*395),(13,20,24))
        draw = ImageDraw.Draw(sheet)
        for i,(name,a) in enumerate(images):
            x,y = (i%2)*480,(i//2)*395
            draw.text((x+8,y+8),name,fill=(220,235,230))
            sheet.paste(Image.fromarray(a).resize((480,360)),(x,y+30))
        Path('validation').mkdir(exist_ok=True)
        sheet.save('validation/preset_comparison.png')
    except ImportError:
        pass


if __name__ == '__main__':
    main()

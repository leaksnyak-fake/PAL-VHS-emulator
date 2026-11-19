"""Generate head-switch comparison charts and offscreen application previews."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image,ImageDraw
from pal_vhs.params import Params,PRESETS
from pal_vhs.experience import CURATED,REFERENCE
from pal_vhs.headswitch import DECK_PROFILES,apply_deck_profile
from pal_vhs.pipeline import render_frame


def source():
    # Self-created pattern: no downloaded reference media is redistributed.
    x=np.zeros((576,720,3),np.uint8)
    x[:]=[40,60,75]
    for c in range(40,720,60):x[:,c:c+3]=[220,210,170]
    for r in range(35,576,45):x[r:r+3]=[190,160,130]
    x[100:380,160:560]=[120,180,150]
    x[140:340,200:520]=[35,80,95]
    # High contrast reference close to the lower switching zone.
    x[520:555,70:650]=[210,210,190]
    return x


def main():
    out=Path('validation');out.mkdir(exist_ok=True)
    x=source();pairs=[]
    for name in DECK_PROFILES:
        p=apply_deck_profile(Params().update(REFERENCE),name)
        y,_=render_frame(x[::2],x[1::2],25 if 'Fault' in name else 42,p.to_dict())
        pairs.append((name,y))
    # Use full-width bottom crops so fractional-line effects remain visible.
    sheet=Image.new('RGB',(900,len(pairs)*155),(14,23,28));d=ImageDraw.Draw(sheet)
    for i,(name,y) in enumerate(pairs):
        d.text((8,i*155+6),name,fill='white')
        sheet.paste(Image.fromarray(y[-80:]).resize((900,100)),(0,i*155+28))
        d.text((8,i*155+132),'Last 80 picture rows; expanded vertically for inspection',fill='#96b6bc')
    sheet.save(out/'headswitch_comparison.png')
    from PySide6 import QtWidgets as W
    from pal_vhs.gui import MainWindow
    app=W.QApplication.instance() or W.QApplication([])
    w=MainWindow(params=Params().update(REFERENCE));w.resize(1500,900);w.show();app.processEvents()
    w.video.set_image(pairs[1][1]);app.processEvents()
    w.grab().save(str(out/'easy_mode.png'))
    w.panel.mode_selector.setCurrentIndex(1)
    w.panel.search.setText('head')
    from pal_vhs.params import GROUPS
    w.panel.toolbox.setCurrentIndex(GROUPS.index('6b Head switching'))
    app.processEvents();w.grab().save(str(out/'advanced_mode.png'))
    w.close();app.processEvents()
    print('Saved bottom-raster and actual Qt application previews')


if __name__ == '__main__':main()

"""Regenerate help catalogue and complete preset JSON from the live registry."""
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pal_vhs.params import SPECS,GROUPS,Params,PRESETS
from pal_vhs.experience import CURATED,MACROS,help_for

lines=['# Control reference','',f'{len(SPECS)} controls. Generated from the actual GUI schema and hover text.','',
       'See VHS_EFFECTS_REFERENCE.md for researched head-switching behaviour and accuracy limits.','',
       '## Easy macro mappings','','| Easy control | Advanced key | 0% | 100% |','|---|---|---:|---:|']
for _,(label,_,mapping) in MACROS.items():
    for key,(a,b) in mapping.items():lines.append(f'| {label} | `{key}` | {a:g} | {b:g} |')
lines+=['','Apply deck changes playback only. Full presets reset every parameter. Damage buttons affect the whole clip, not timestamped events.','']
for group in GROUPS:
    lines += [f'## {group.split(" ",1)[1]}','','| Control / key | Help |','|---|---|']
    for s in SPECS:
        if s['group']==group:
            text=help_for(s).replace('\n',' ').replace('|','/')
            lines.append(f'| {s["label"]} / `{s["key"]}` | {text} |')
    lines.append('')
(ROOT/'docs/CONTROLS.md').write_text('\n'.join(lines),encoding='utf-8')
(ROOT/'presets').mkdir(exist_ok=True)
for name in CURATED:
    filename=re.sub(r'[^a-z0-9]+','_',name.lower()).strip('_')+'.json'
    Params(**PRESETS[name]).save(ROOT/'presets'/filename)
print(f'Generated {len(SPECS)} help entries and {len(CURATED)} complete presets')

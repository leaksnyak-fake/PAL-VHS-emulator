import pathlib,sys,types,json
base=pathlib.Path('reference/pal_vhs_cassette_edition/pal_vhs')
pkg=types.ModuleType('refmodel');pkg.__path__=[str(base.resolve())];sys.modules['refmodel']=pkg
import refmodel.params as p
h=types.ModuleType('refmodel.headswitch');h.__package__='refmodel';sys.modules[h.__name__]=h
source=(base/'headswitch.py').read_text();source='\n'.join(l for l in source.splitlines() if not l.startswith(('import numpy','from scipy','from . import')))
exec(compile(source,str(base/'headswitch.py'),'exec'),h.__dict__)
import refmodel.experience as e
out=pathlib.Path('assets')
for name,data in [('schema',p.SPECS),('presets',p.PRESETS),('decks',{k:dict(h.DECK_BASE,**v[1]) for k,v in h.DECK_PROFILES.items()}),('macros',e.MACROS)]:
 (out/(name+'.json')).write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
print(len(p.SPECS),len(p.PRESETS),len(h.DECK_PROFILES))

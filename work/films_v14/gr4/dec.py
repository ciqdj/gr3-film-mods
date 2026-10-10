import sys
sys.path.insert(0, '.'); import codec_path  # noqa: F401  (run from the repo root)
from gr4_editor.codec.container import inspect_container
from gr4_editor.codec.frames import decode_payload, section_rows
for name,path in [('gr3','../fwdc239b.bin'),('gr4','../fwdc248b.bin')]:
    d=open(path,'rb').read(); i=inspect_container(d)
    print(name, {k:v for k,v in i.items() if not isinstance(v,(bytes,list,dict))})
    dec,_=decode_payload(d[128:i['payload_end']], i['decoded_size'])
    open(f'{name}_dec.bin','wb').write(dec)
    for r in section_rows(dec): print('  ',{k:(hex(v) if isinstance(v,int) else v) for k,v in r.items()})

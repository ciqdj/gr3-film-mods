import struct, re, os
import numpy as np
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
W=__import__('os').environ.get('GR_RTOS_DIR', 'scratch/w/')  # gr3_rtos.bin / gr4_rtos.bin (dec.py)
CFG={'gr3':(0x5407b540,0x55000000,0x3a080),'gr4':(0x5437b640,0x55000000,0x57480)}
BASE=0x53000000
class FW:
    def __init__(s,name):
        s.name=name; s.R=open(W+name+'_rtos.bin','rb').read()
        s.SRC,s.DST,s.LEN=CFG[name]
        s._W=np.frombuffer(s.R[:len(s.R)//4*4],dtype='<u4')
        s.md=Cs(CS_ARCH_ARM,CS_MODE_ARM)
    def off(s,a):
        if s.DST<=a<s.DST+s.LEN: return s.SRC-BASE+a-s.DST
        return a-BASE
    def addr(s,o):
        if s.SRC-BASE<=o<s.SRC-BASE+s.LEN: return s.DST+o-(s.SRC-BASE)
        return BASE+o
    def rd(s,a,n): o=s.off(a); return s.R[o:o+n]
    def w(s,a): return struct.unpack('<I',s.rd(a,4))[0]
    def h(s,a,n): return struct.unpack(f'<{n}h',s.rd(a,2*n))
    def H(s,a,n): return struct.unpack(f'<{n}H',s.rd(a,2*n))
    def cstr(s,a):
        o=s.off(a); e=s.R.index(b'\0',o); return s.R[o:e].decode('latin1')
    def find(s,b): return [s.addr(m.start()) for m in re.finditer(re.escape(b),s.R)]
    def refs(s,a):
        p=struct.pack('<I',a); return [s.addr(m.start()) for m in re.finditer(re.escape(p),s.R) if m.start()%4==0]
    def movw_xrefs(s,target):
        lo=target&0xFFFF; hi=target>>16; W=s._W
        movw=(W&0x0FF00000)==0x03000000; movt=(W&0x0FF00000)==0x03400000
        val=((W>>4)&0xF000)|(W&0xFFF)
        out=[]
        for i in np.nonzero(movw&(val==lo))[0]:
            rd=(W[i]>>12)&15
            for j in range(i+1,min(i+24,len(W))):
                if movt[j] and ((W[j]>>12)&15)==rd:
                    if val[j]==hi: out.append(BASE+4*int(i))
                    break
        return out
    def bl_callers(s,target):
        W=s._W; idx=np.arange(len(W))
        isbl=(W&0x0E000000)==0x0A000000
        imm=(W&0x00FFFFFF).astype(np.int64); imm=np.where(imm&0x800000,imm-0x1000000,imm)
        dest=BASE+idx*4+8+imm*4
        return [BASE+4*int(i) for i in np.flatnonzero(isbl&(dest==target)&((W>>24)&0xF==0xB) )]
    def b_refs(s,target):
        W=s._W; idx=np.arange(len(W))
        isb=(W&0x0E000000)==0x0A000000
        imm=(W&0x00FFFFFF).astype(np.int64); imm=np.where(imm&0x800000,imm-0x1000000,imm)
        dest=BASE+idx*4+8+imm*4
        return [BASE+4*int(i) for i in np.flatnonzero(isb&(dest==target))]
    def dis(s,a,n=40):
        o=s.off(a)
        return '\n'.join(f'{i.address:#x}: {i.mnemonic} {i.op_str}' for i in s.md.disasm(s.R[o:o+4*n],a))
    def func_start(s,a):
        while a>BASE:
            if s.w(a)==0xE1A0C00D: return a
            a-=4
def vtables(fw,name):
    res=[]
    for a in fw.find(b'\0'+name.encode()+b'\0'):
        a+=1
        for r in fw.refs(a):
            ti=r-4
            for v in fw.refs(ti):
                res.append((ti,v+4))
    # also mangled names e.g. "16MultiAxialTuning"
    for a in fw.find(name.encode()+b'\0'):
        s=a
        while fw.rd(s-1,1).isdigit(): s-=1
        if s==a: continue
        for r in fw.refs(s):
            ti=r-4
            for v in fw.refs(ti): res.append((ti,v+4))
    return res
FW.vtables=vtables
def refs_in_range(fw,lo,hi):
    W=fw._W
    lits=[(fw.addr(4*int(i)),int(W[i])) for i in np.flatnonzero((W>=lo)&(W<hi))]
    movw=(W&0x0FF00000)==0x03000000; movt=(W&0x0FF00000)==0x03400000
    val=((W>>4)&0xF000)|(W&0xFFF)
    out=[]
    hi16s=set(range(lo>>16,(hi-1>>16)+1))
    for j in np.flatnonzero(movt):
        if int(val[j]) not in hi16s: continue
        rd=(W[j]>>12)&15
        for i in range(j-1,max(j-24,0),-1):
            if movw[i] and ((W[i]>>12)&15)==rd:
                v=(int(val[j])<<16)|int(val[i])
                if lo<=v<hi: out.append((BASE+4*i,v))
                break
    return lits,out
FW.refs_in_range=refs_in_range
def disj(fw,a,n=60):
    """disassemble with jump-table decoding (ldrls pc,[pc,rX,lsl#2] after cmp rX,#N)"""
    out=[];x=a;end=a+4*n;lastcmp=None
    md=fw.md
    while x<end:
        ins=list(md.disasm(fw.rd(x,4),x))
        if not ins:
            out.append(f'{x:#x}: .word {fw.w(x):#010x}'); x+=4; continue
        i=ins[0]; out.append(f'{x:#x}: {i.mnemonic} {i.op_str}')
        if i.mnemonic.startswith('cmp') and '#' in i.op_str:
            try: lastcmp=int(i.op_str.split('#')[1],0)
            except: pass
        if i.mnemonic.startswith('ldr') and i.op_str.startswith('pc, [pc,') and lastcmp is not None:
            # table at x+8, lastcmp+1 entries; default insn at x+4
            dflt=list(md.disasm(fw.rd(x+4,4),x+4))[0]
            out.append(f'{x+4:#x}: {dflt.mnemonic} {dflt.op_str}   ; default')
            for k in range(lastcmp+1):
                out.append(f'      case {k}: -> {fw.w(x+8+4*k):#x}')
            x=x+8+4*(lastcmp+1); continue
        x+=4
    return '\n'.join(out)
FW.disj=disj

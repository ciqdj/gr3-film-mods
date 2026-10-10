import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fwx import FW
from emux import Tuning
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
import numpy as np
g=FW('gr4')
def curves(tone,stage,ct=None):
    t=Tuning(g,stage=stage)
    cap={}
    def h(u,addr,size,_):
        if addr==0x5391e340: cap['buf']=u.reg_read(A.UC_ARM_REG_R0); cap['ctx']=u.reg_read(A.UC_ARM_REG_R1)
        if addr==0x5391e3a8: cap['mix']=(u.reg_read(A.UC_ARM_REG_R0),u.reg_read(A.UC_ARM_REG_R1))
    t.e.u.hook_add(UC_HOOK_CODE,h,begin=0x5391e340,end=0x5391e3ac)
    ex=(lambda e,st: e.w8(st+0x7a6,ct)) if ct is not None else None
    t.make(tone,extra=ex)
    b=cap['buf']; rd=lambda o: np.frombuffer(t.e.rd(b+o,512),'<u2').astype(int)
    return dict(base=rd(0),curves=[rd(0x200),rd(0x400),rd(0x600)],comp=[rd(0x3008),rd(0x3208),rd(0x3408)],mix=cap.get('mix'),ct60=t.e.rd(cap['ctx']+0x60,2))
if __name__=='__main__':
    for tone in (11,18,19):
        for st in (1,0):
            for ct in (None,0,1,2):
                c=curves(tone,st,ct)
                print(tone,st,ct,c['mix'],c['ct60'].hex(),c['comp'][0][::32],c['comp'][2][::32])

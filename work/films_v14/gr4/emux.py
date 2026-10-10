import struct
from fwx import FW, BASE
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_INTR, UcError
from unicorn import arm_const as A
HEAP, STACK, STOP = 0x60000000, 0x5F000000, 0x5E000000
CFG = {
 'gr3': dict(malloc=(0x536af2a8,0x536af31c), free=(0x536af2e4,0x536af358), assert_=0x536b93d0, ret0={0x536b82d4,0x5313fbb8},
             init1=0x536da1fc, init2=0x536da62c, vt=0x53dbd8a0, make=0x536dd8f0, si_off=0x71248, tone=0x77c, d=0,
             subs=(0x536decb4,0x536e4634,0x536e4de4,0x536e5070,0x536e7348,0x536eaf80,0x536ec3e0,0x536eb0b0,0x536e9d1c)),
 'gr4': dict(malloc=(0x538e09b0,0x538e0a24), free=(0x538e09ec,0x538e0a60), assert_=0x538ed930, ret0={0x538ec838,0x53155f78},
             init1=0x5390fdf4, init2=0x53910224, vt=0x54043fd8, make=0x53913854, si_off=0x71280, tone=0x79c, d=0x20,
             subs=(0x53914c18,0x5391a564,0x5391ad14,0x5391afa0,0x5391d278,0x53920c30,0x539220f0,0x53920d60,0x5391f9cc)),
}
class Emu:
    def __init__(self, fw, rtos=None, stub_subs=True):
        self.fw=fw; c=self.c=CFG[fw.name]; R=rtos if rtos is not None else fw.R
        u=self.u=Uc(UC_ARCH_ARM, UC_MODE_ARM)
        u.mem_map(BASE,(len(R)+0xFFFF)&~0xFFFF); u.mem_write(BASE,bytes(R))
        u.mem_map(0x55000000,0x01000000); u.mem_write(fw.DST,bytes(R[fw.SRC-BASE:fw.SRC-BASE+fw.LEN]))
        u.mem_map(HEAP,0x04000000); u.mem_map(STACK-0x100000,0x100000); u.mem_map(STOP,0x1000)
        u.reg_write(A.UC_ARM_REG_C1_C0_2,0xF00000); u.reg_write(A.UC_ARM_REG_FPEXC,0x40000000)
        self.brk=HEAP; self.asserts=[]; self.stubs={}
        if stub_subs:
            for s in c['subs']: self.stubs[s]=0
        u.hook_add(UC_HOOK_CODE,self._code); u.hook_add(UC_HOOK_INTR,lambda u,i,_: u.reg_write(A.UC_ARM_REG_R0,0))
    def alloc(self,n):
        a=self.brk; self.brk=(self.brk+n+0x3F)&~0x3F; self.u.mem_write(a,bytes(n)); return a
    def _ret(self,v=None):
        if v is not None: self.u.reg_write(A.UC_ARM_REG_R0,v)
        self.u.reg_write(A.UC_ARM_REG_PC,self.u.reg_read(A.UC_ARM_REG_LR))
    def _code(self,u,at,size,_):
        c=self.c
        if at in c['malloc']: self._ret(self.alloc(u.reg_read(A.UC_ARM_REG_R0)))
        elif at in c['free']: self._ret(0)
        elif at==c['assert_']:
            if not u.reg_read(A.UC_ARM_REG_R0): self.asserts.append((hex(u.reg_read(A.UC_ARM_REG_LR)),u.reg_read(A.UC_ARM_REG_R3)))
            self._ret(0)
        elif at in c['ret0']: self._ret(0)
        elif at in self.stubs:
            v=self.stubs[at]; self._ret(v(self) if callable(v) else v)
    def call(self,at,*args,limit=20_000_000):
        u=self.u
        for i in range(13): u.reg_write(getattr(A,f'UC_ARM_REG_R{i}'),0)
        for i,v in enumerate(args): u.reg_write(getattr(A,f'UC_ARM_REG_R{i}'),v)
        u.reg_write(A.UC_ARM_REG_SP,STACK-0x100); u.reg_write(A.UC_ARM_REG_LR,STOP); u.reg_write(A.UC_ARM_REG_CPSR,0x13)
        try: u.emu_start(at,STOP,count=limit)
        except UcError as e:
            raise RuntimeError(f'{e} at pc={u.reg_read(A.UC_ARM_REG_PC):#x} lr={u.reg_read(A.UC_ARM_REG_LR):#x}')
        if u.reg_read(A.UC_ARM_REG_PC)!=STOP: raise RuntimeError(f'did not return pc={u.reg_read(A.UC_ARM_REG_PC):#x}')
        return u.reg_read(A.UC_ARM_REG_R0)
    def r32(self,a): return struct.unpack('<I',self.u.mem_read(a,4))[0]
    def w32(self,a,v): self.u.mem_write(a,struct.pack('<I',v))
    def w8(self,a,v): self.u.mem_write(a,bytes([v&0xff]))
    def rd(self,a,n): return bytes(self.u.mem_read(a,n))

GR3_DEFAULTS={**{o:4 for o in (0x77d,0x77e,0x77f,0x780,0x781,0x782,0x784,0x787,0x792,0x793,0x794)},0x783:1,0x786:1,0x798:1}
class Tuning:
    def __init__(self,fw,rtos=None,stage=1,stub_subs=True):
        e=self.e=Emu(fw,rtos,stub_subs); c=e.c
        obj=e.alloc(0x400); cfg=e.alloc(0x1000)
        e.w32(obj,c['vt']); e.call(c['init1'],obj,cfg); e.call(c['init2'],obj,cfg); e.w32(obj,c['vt'])
        info=e.alloc(0x9000); si=e.alloc(0x80000)
        e.w8(info+0x82ac,stage); e.w32(info+0x82d0,si)
        self.obj,self.info,self.si,self.stage=obj,info,si,stage
    def make(self,tone,params=None,extra=None):
        e=self.e; c=e.c
        st=self.si+(c['si_off'] if self.stage else 0)
        for o,v in GR3_DEFAULTS.items(): e.w8(st+o+c['d'],v)
        if params:
            for o,v in params.items(): e.w8(st+o,v)
        e.w8(st+c['tone'],tone)
        if extra: extra(e,st)
        e.call(c['make'],self.obj,self.info)
        return e.rd(self.info,0x9000)

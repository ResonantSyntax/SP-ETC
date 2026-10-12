"""Compiled capture contracts: all pads, released selection and melodic delegation."""
import hashlib,json,struct,sys
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB
from unicorn import arm_const as ar
from kits.sparse_module import reconstruct_module
out=Path(sys.argv[1]);m=json.loads((out/'manifest.json').read_text());image=(out/'SP404MKII_APP1.bin').read_bytes()
assert hashlib.sha256(image).hexdigest()==m['sha256']
module=reconstruct_module(image,m);S=m['arp_symbols'];base=m['arp_code_base']
u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
for address,size in [(0,8192),(0x80249000,4096),(0x8353a000,12288),(0x83f80000,458752),(0x20200000,16384),(0x800de000,4096)]:u.mem_map(address,size)
u.mem_write(base,module);u.mem_write(0x1000,b'\x00\xbf')
for address in [0x800ded08,0x800decf8]:u.mem_write(address,b'\x70\x47')
u.reg_write(ar.UC_ARM_REG_C1_C0_2,0xf<<20);u.reg_write(ar.UC_ARM_REG_FPEXC,0x40000000)
def call(name,*args):
 u.reg_write(ar.UC_ARM_REG_SP,0x20203f00);u.reg_write(ar.UC_ARM_REG_LR,0x1001)
 for i,v in enumerate(args):u.reg_write(getattr(ar,'UC_ARM_REG_R'+str(i)),v)
 u.emu_start(S[name]|1,0x1000,count=2000000)
 assert u.reg_read(ar.UC_ARM_REG_PC)==0x1000
 return u.reg_read(ar.UC_ARM_REG_R0)
cases=0
for kit in range(1,12):
 u.mem_write(S['kit_mode'],bytes([kit]))
 for pad in range(16):
  # Selection persists after release even if the UI selects a different pad.
  velocity=32+(pad*5)%96;call('kit_note_seen',pad,velocity);call('kit_note_seen',pad,0)
  u.mem_write(S['kit_edit_pad'],bytes([(pad+1)%16]))
  u.mem_write(0x80249810,struct.pack('<I',7))
  assert call('kit_capture_selected')==1
  assert struct.unpack('<I',u.mem_read(0x8353c1ac,4))[0]==pad
  assert struct.unpack('<I',u.mem_read(0x8353c198,4))[0]==velocity*100
  assert struct.unpack('<I',u.mem_read(0x8353c010,4))[0]==0
  assert struct.unpack('<I',u.mem_read(0x8353c700,4))[0]==1
  assert u.mem_read(0x8353c004,1)==b'\0'
  assert u.mem_read(S['kit_pads_down'],2)==b'\0\0'
  cases+=1
u.mem_write(S['kit_mode'],b'\0');assert call('kit_capture_selected')==0
report=dict(passed=True,released_pad_cases=cases,velocity_snapshot=True,ui_selection_does_not_replace_last_strike=True,melodic_capture_delegated=True,app1_sha256=m['sha256'])
(out/'capture_check.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

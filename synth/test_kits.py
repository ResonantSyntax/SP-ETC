"""Run the kit engine from the built arp+kit module in Unicorn.

The module (boot-copied at 0x83FA2000) is loaded from the built APP1 at its
SP address. For every kit and pad, kit_output on a fake voice
state must equal the host build of kit_engine.c sample-for-sample (3,000
samples). Also checks that the generated menu answers items 11..20, and the
hold-pad VALUE turn: the pad note hook, kit_turn (stock setting get/step
replaced by stubs) and kit_turn_gate's handled exit back into 0x8015cb2e.
"""
from __future__ import annotations
import ctypes as ct, hashlib, json, struct, sys
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL, UC_PROT_READ
from unicorn import arm_const as ar

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from kits.sparse_module import reconstruct_module
V0, RET, STACK, BUF = 0x80249800, 0x1000, 0x20200000, 0x201FE000

def main():
    out = Path(sys.argv[1]).resolve()
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8")); img = (out / "SP404MKII_APP1.bin").read_bytes()
    if hashlib.sha256(img).hexdigest() != man["sha256"]: raise ValueError("APP1/manifest hash mismatch")
    base = man["arp_code_base"]
    module = reconstruct_module(img, man)
    S = man["arp_symbols"]
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    if base + len(module) > 0x83FF0000:
        raise ValueError("module exceeds reserved runtime window")
    for b, n in ((0, 0x2000), (0x80249000, 0x1000), (0x8353A000, 0x3000), (0x83F80000, 0x70000), (STACK - 0x4000, 0x4000),
                 (0x800BF000, 0x1000), (0x800D9000, 0x1000), (0x8015C000, 0x1000)):
        uc.mem_map(b, n, UC_PROT_ALL)
    uc.mem_write(base, module); uc.mem_write(RET, b"\x00\xbf")
    pcm_data = None
    if "kit_pcm" in man:
        bank = man["kit_pcm"]
        start, length, address = bank["file_offset"], bank["bytes"], bank["flash_address"]
        pcm_data = img[start:start+length]
        if len(pcm_data) != length or hashlib.sha256(pcm_data).hexdigest() != bank["sha256"]:
            raise ValueError("PCM bank/manifest mismatch")
        if address & 4095: raise ValueError("PCM mapping must start at a page boundary")
        mapped_size = (length+4095) & ~4095
        uc.mem_map(address, mapped_size, UC_PROT_ALL)
        uc.mem_write(address, pcm_data)
        uc.mem_protect(address, mapped_size, UC_PROT_READ)
    uc.reg_write(ar.UC_ARM_REG_C1_C0_2, uc.reg_read(ar.UC_ARM_REG_C1_C0_2) | (0xf << 20)); uc.reg_write(ar.UC_ARM_REG_FPEXC, 0x40000000)
    def call(fn, *args):
        uc.reg_write(ar.UC_ARM_REG_SP, STACK - 0x100); uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        for k, a in enumerate(args): uc.reg_write(getattr(ar, f"UC_ARM_REG_R{k}"), a)
        uc.emu_start(S[fn] | 1, RET, count=2000000)
        if uc.reg_read(ar.UC_ARM_REG_PC) != RET:
            raise RuntimeError(("instruction limit or early exit", fn, hex(uc.reg_read(ar.UC_ARM_REG_PC))))
        return uc.reg_read(ar.UC_ARM_REG_R0), struct.unpack("<f", struct.pack("<I", uc.reg_read(ar.UC_ARM_REG_S0)))[0]
    library = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "build" / ("kit_engine_host.dll" if sys.platform == "win32" else "kit_engine_host.so")
    host = ct.CDLL(str(library.resolve())); N = 3000; buf = (ct.c_float * N)()
    if pcm_data is not None:
        host_bank = (ct.c_uint8 * len(pcm_data)).from_buffer_copy(pcm_data)
        host.kit_pcm_bind.argtypes = [ct.POINTER(ct.c_uint8), ct.c_uint32]
        host.kit_pcm_bind.restype = ct.c_int
        if host.kit_pcm_bind(host_bank, len(pcm_data)) != 1:
            raise AssertionError("host PCM bind failed")
    host.kit_host_render.argtypes = [ct.c_uint, ct.c_uint, ct.c_int, ct.POINTER(ct.c_float)]
    checked = 0
    kits = len(man["arp_menu"]["KIT"]) - 1
    for kit in range(1, kits + 1):
        uc.mem_write(S["kit_mode"], bytes([kit]))
        for pad in range(16):
            # A one-shot host preview has an explicitly cold physical circuit.
            # Match that policy here; persistent repeated hits are tested by
            # the separate lifecycle check, not by carrying between presets.
            if "kit_finish_begin_block" in S:
                uc.mem_write(base, module)
                uc.mem_write(S["kit_mode"], bytes([kit]))
            if "kit_clock_next" in S:
                uc.mem_write(S["kit_clock_next"], bytes(4)); uc.mem_write(S["kit_live_cursor"], bytes(16))
            host.kit_host_render(kit, pad, N, buf)
            st = bytearray(0x1B0); st[0] = 1; struct.pack_into("<I", st, 0x1AC, pad); struct.pack_into("<i", st, 0x19C, 8 + pad)
            uc.mem_write(V0, bytes(st))
            for n in range(N):
                if "kit_begin_block" in S and n % 64 == 0:
                    call("kit_begin_block", min(64, N-n))
                    if "kit_finish_begin_block" in S:
                        call("kit_finish_begin_block", min(64, N-n))
                _, y = call("kit_output", V0)
                if n == 0: uc.mem_write(V0 + 0x18C, struct.pack("<I", 0x3F800000))
                if struct.pack("<f", y) != struct.pack("<f", buf[n]): raise AssertionError(("kit/pad differs", kit, pad, n, y, buf[n]))
            checked += 1
    # Compare the new control bytes on ARM, not only neutral factory recipes.
    hp=(ct.c_ubyte*(kits*16*8)).in_dll(host,'kit_pads')
    factory=bytes(hp);control_checks=0
    fields=[(1,-12,12),(2,0,100),(3,0,100),(5,0,100),(6,0,100),(7,0,100)]
    for sound in (0,8,9,18,23,35,109,121,141):
        for offset,lo,hi in fields:
            for value in (lo,hi):
                recipe=bytearray(factory)
                recipe[:8]=bytes([sound,0,50,50,110,50,50,50])
                recipe[offset]=value&255
                hp[:]=recipe
                host.kit_host_render(1,0,384,buf)
                uc.mem_write(base,module);uc.mem_write(S['kit_mode'],b'\x01')
                uc.mem_write(S['kit_pads_ready'],b'\x01');uc.mem_write(S['kit_pads'],bytes(recipe))
                st=bytearray(0x1B0);st[0]=1;struct.pack_into('<i',st,0x19C,8)
                uc.mem_write(V0,bytes(st))
                for n in range(384):
                    if n%64==0:call('kit_begin_block',64);call('kit_finish_begin_block',64)
                    _,y=call('kit_output',V0)
                    if n==0:uc.mem_write(V0+0x18C,struct.pack('<I',0x3F800000))
                    assert struct.pack('<f',y)==struct.pack('<f',buf[n]),('control ARM mismatch',sound,offset,value,n,y,buf[n])
                control_checks+=1
    hp[:]=factory
    uc.mem_write(base,module);uc.mem_write(S['kit_pads_ready'],b'\x01');uc.mem_write(S['kit_pads'],factory)
    uc.mem_write(S['kit_mode'],bytes([kits]))
    inventories=[set(range(8,24)),set(range(72,78)),set(range(78,86)),set(range(90,98)),set(range(0,8)),set(range(24,31))|set(range(86,90)),set(range(31,38)),set(range(38,44)),set(range(98,113)),set(range(44,58)),set(range(58,72)),set(range(113,128)),set(range(128,143))]
    for kit,allowed in enumerate(inventories,1):
        uc.mem_write(S['kit_mode'],bytes([kit]))
        for pad in range(16):
            uc.mem_write(S['kit_edit_pad'],bytes([pad]))
            address=S['kit_pads']+((kit-1)*16+pad)*8
            initial=uc.mem_read(address,1)[0]
            for _ in range(len(allowed)+1):
                call('arp_item_step',13,1)
                sound=uc.mem_read(address,1)[0]
                assert sound==255 if initial==255 else sound in allowed,(kit,pad,initial,sound)
    uc.mem_write(base,module);uc.mem_write(S['kit_pads_ready'],b'\x01');uc.mem_write(S['kit_pads'],factory);uc.mem_write(S['kit_mode'],bytes([kits]))
    for mode,step,want in [(1,-1,1),(1,-100,1),(13,1,13),(13,100,13),(6,-1,5),(6,1,7),(0,-1,0),(0,1,0),(0,100,0)]:
        uc.mem_write(S['kit_mode'],bytes([mode]));call('kit_item_step',11,step&0xffffffff)
        assert uc.mem_read(S['kit_mode'],1)[0]==want,('selector',mode,step,want)
    uc.mem_write(S['kit_mode'],bytes([kits]))
    names = {}
    for item in range(11, 21):
        uc.mem_write(BUF, bytes(16)); call("arp_item_name", item, BUF); n = bytes(uc.mem_read(BUF, 8)).split(b"\0")[0].decode()
        uc.mem_write(BUF, bytes(16)); call("arp_item_text", item, BUF); t = bytes(uc.mem_read(BUF, 8)).split(b"\0")[0].decode()
        names[n] = t
    if list(names) != ["KIT", "PAD", "SOUND", "TUNE", "DECAY", "TONE", "LEVEL", "SWEEP", "NOISE", "ATTCK"]: raise AssertionError(names)
    turn = check_turn(uc, call, S, len(man["arp_menu"]["SOUND"]))
    hats = check_hat_audio(uc, call, S, base, module)
    res = dict(control_endpoint_arm_matches=control_checks, machine_inventory_restrictions=True,selector_boundary_cases=9,kits=kits, pads_sample_exact=checked, samples_per_pad=N, menu=names, hold_pad_turn=turn, hat_audio=hats, build_sha256=man["sha256"],
               pcm_bank_sha256=man.get("kit_pcm", {}).get("sha256"), pcm_flash_readonly=pcm_data is not None,
               module_runtime_bytes=len(module), module_stored_bytes=man.get("arp_code_stored_bytes", len(module)),
               module_reconstructed_sha256=hashlib.sha256(module).hexdigest())
    (out / "unicorn_check.json").write_text(json.dumps(dict(schema="kit-unicorn-check-v2", passed=True, **res), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(res))

CURSOR = BUF + 0x100      # stand-in for setting 0x83 (the VALUE cursor)

def check_turn(uc, call, S, sounds):
    from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
    ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB)
    lo, hi = CURSOR & 0xFFFF, CURSOR >> 16
    # setting get (r0 obj, r1 id, r2 0) and setting step (r0 obj, r1 id, r2 delta, r3, [sp]) stubs
    get = f"movw r3, #{lo}; movt r3, #{hi}; ldr r0, [r3]; bx lr"
    step = f"movw r3, #{lo}; movt r3, #{hi}; ldr r0, [r3]; add r0, r2; str r0, [r3]; bx lr"
    uc.mem_write(0x800D94D8, bytes(ks.asm(get, 0x800D94D8)[0])); uc.mem_write(0x800BF8C8, bytes(ks.asm(step, 0x800BF8C8)[0]))
    rd = lambda a, n=1: int.from_bytes(bytes(uc.mem_read(a, n)), "little")
    pads = S["kit_pads"]
    def sound(kit, pad): return rd(pads + 128 * (kit - 1) + 8 * pad)
    uc.mem_write(S["kit_mode"], bytes([5])); uc.mem_write(CURSOR, struct.pack("<i", 6))
    call("kit_note_seen", 3, 100)
    if rd(S["kit_edit_pad"]) != 3 or rd(S["kit_pads_down"], 2) != 1 << 3: raise AssertionError("pad press not seen")
    before = sound(5, 3); neighbor_before = sound(5, 2)
    r, _ = call("kit_turn", 1)
    if r != 1 or sound(5, 3) != ((before + 1) if before < 7 else 0) or rd(CURSOR, 4) != 13: raise AssertionError(("turn +", r, sound(5, 3)))
    r, _ = call("kit_turn", 0xFFFFFFFF)
    if r != 1 or sound(5, 3) != before or rd(CURSOR, 4) != 13: raise AssertionError("turn -")
    if sound(5, 2) != neighbor_before: raise AssertionError("other pad touched")
    call("kit_note_seen", 3, 0)
    r, _ = call("kit_turn", 1)
    if r != 1 or sound(5, 3) != before: raise AssertionError("turn without a held pad")
    call("kit_note_seen", 7, 90); uc.mem_write(S["kit_mode"], bytes([0]))
    r, _ = call("kit_turn", 1)
    if r != 1 or rd(CURSOR,4)>10: raise AssertionError("melodic menu turn")
    call("kit_note_seen",7,0)
    for mode,expected in [(0,list(range(11))), (5,[6,7,8,9,10,11,12,13,17])]:
        uc.mem_write(S["kit_mode"],bytes([mode]));uc.mem_write(CURSOR,struct.pack("<i",expected[0]))
        for value in expected[1:]:
            call("kit_turn",1)
            if rd(CURSOR,4)!=value:raise AssertionError(("menu +",mode,value,rd(CURSOR,4)))
        call("kit_turn",1)
        if rd(CURSOR,4)!=expected[-1]:raise AssertionError("menu upper bound")
        for value in reversed(expected[:-1]):
            call("kit_turn",0xffffffff)
            if rd(CURSOR,4)!=value:raise AssertionError(("menu -",mode,value,rd(CURSOR,4)))
        call("kit_turn",0xffffffff)
        if rd(CURSOR,4)!=expected[0]:raise AssertionError("menu lower bound")
    uc.mem_write(S["kit_mode"],bytes([0]));call("kit_note_seen",7,90)
    # kit_turn_gate: stops at the stock code it returns to; r0..r2 must be the stock cursor-step arguments.
    stops = []
    def hook(uc_, addr, size, _):
        stops.append((addr, uc_.reg_read(ar.UC_ARM_REG_R0), uc_.reg_read(ar.UC_ARM_REG_R1), uc_.reg_read(ar.UC_ARM_REG_R2),
                      uc_.reg_read(ar.UC_ARM_REG_SP))); uc_.emu_stop()
    h = uc.hook_add(1 << 2, hook, None, 0x8015CB24, 0x8015CB2E)     # UC_HOOK_CODE
    def gate(dir_):
        sp = STACK - 0x100; uc.reg_write(ar.UC_ARM_REG_SP, sp); uc.reg_write(ar.UC_ARM_REG_R2, dir_)
        stops.clear(); uc.emu_start(S["kit_turn_gate"] | 1, RET, count=200000)
        a, r0, r1, r2, sp2 = stops[0]
        if sp2 != sp: raise AssertionError("gate stack")
        return a, r0, r1, r2
    if gate(1)[0] != 0x8015CB2E: raise AssertionError("gate, melodic")
    if gate(0xFFFFFFFF)[0] != 0x8015CB2E: raise AssertionError("gate -1, melodic")
    uc.mem_write(S["kit_mode"], bytes([5]))
    a, *_ = gate(1)
    if a != 0x8015CB2E or rd(S["kit_edit_pad"]) != 7: raise AssertionError(("gate, pad held", hex(a)))
    uc.hook_del(h)
    call("kit_note_seen", 7, 0); uc.mem_write(S["kit_mode"], bytes([0]))
    return dict(press_selects_pad=True, turn_steps_sound=True, cursor_to_sound=True, kit_menu_without_pad=True, melodic_menu_bounded=True,
                gate_exits=["0x8015cb24 stock cursor step", "0x8015cb2e handled"])

def check_hat_audio(uc, call, S, base, module):
    """Exercise simultaneous stock voice states through the built ARM hook."""
    results = []
    def state(addr, pad):
        st = bytearray(0x1B0); st[0] = 1
        struct.pack_into("<I", st, 0x1AC, pad)
        uc.mem_write(addr, bytes(st))
    def sample(addr):
        _, y = call("kit_output", addr)
        uc.mem_write(addr+0x18C, struct.pack("<f", 1.0))
        return y
    for kit, oh, ch in ((1, 3, 2), (2, 3, 2), (3, 3, 2), (4, 3, 2), (5, 3, 2), (7, 3, 2), (12, 3, 2)):
        energies = []
        for choke in (False, True):
            uc.mem_write(base, module); uc.mem_write(S["kit_mode"], bytes([kit]))
            state(V0, oh); state(0x8353A310, ch)
            for _ in range(1200): sample(V0)
            if choke: sample(0x8353A310)
            energy = 0.0
            for n in range(1200):
                y = sample(V0)
                if n >= 480: energy += y*y
            energies.append(energy)
        if not energies[0] > 0 or energies[1] >= energies[0]*1e-5:
            raise AssertionError(("ARM hat choke failed", kit, energies))
        results.append(dict(kit=kit, tail_energy_ratio=energies[1]/energies[0]))
    return results

if __name__ == "__main__":
    main()

"""Build synthesized kits from the exact v9.6-fixes parent, without overwrites."""
import argparse,subprocess,sys
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('v96',type=Path);p.add_argument('--zig',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();here=Path(__file__).resolve().parent
    subprocess.run([sys.executable,str(here/'kits/build_arp_kit.py'),str(here),str(a.v96.resolve()),str(a.out.resolve()),str(a.zig.resolve())],check=True)
if __name__=='__main__':main()

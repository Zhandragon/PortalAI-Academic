"""Public instance endpoint diagnostics; no account data is read."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from instance_runtime import status,save_settings
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['status','configure'],default='status',nargs='?')
    parser.add_argument('--root',default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--name');parser.add_argument('--ports',help='JSON service-to-port map; 0 chooses automatically on next launch')
    args=parser.parse_args()
    if args.action=='configure':
        current=status(args.root)['configured']
        save_settings(args.root,{'name':args.name or current['name'],'ports':json.loads(args.ports) if args.ports else current['ports']})
    print(json.dumps(status(args.root),indent=2))
if __name__=='__main__':main()

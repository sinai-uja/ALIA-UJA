import sys, os, yaml
sys.path.append(f"{os.path.dirname(os.path.realpath(__file__))}/")
from datetime import datetime
import argparse, subprocess
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import ALIADataUtils as autils
from documentation.spreadsheet_retriever import SpreadsheetRetriever

def main(args):
    
    print(f"Arguments: {args}")
    
    if args.all:
        root = yaml.safe_load(
            open(f"{os.path.dirname(os.path.realpath(__file__))}/config.yaml", "r")
        )['root-interim']
        if args.domain:
            ids = autils.get_domain_dataset_ids(f"{root}/{args.domain}")
        else:
            ids = []
            domains = os.listdir(f"{root}")
            for domain in domains: 
                ids.extend(autils.get_domain_dataset_ids(f"{root}/{domain}"))
    else:
        ids = [args.id]
    
    sr = SpreadsheetRetriever()
    
    for id in ids:
        
        _id = id.replace("/", "_")
        
        # form
        try:
            sr.retrieve_spreadsheet(id)
        except Exception as e:
            print(f"Error retrieving the form for '{id}': {e}")
            continue
        
        print(f"Processing dataset '{id}'")
        _time = datetime.now().strftime('%m-%d_%H-%M')
        _dir = yaml.safe_load(
            open(f"{os.path.dirname(os.path.realpath(__file__))}/config.yaml", "r")
        )['log-dir']
        _output = os.path.realpath(f"{_dir}/{_time}_{_id}.out")
        _error = os.path.realpath(f"{_dir}/{_time}_{_id}.err")
        batch = yaml.safe_load(
            open(f"{os.path.dirname(os.path.realpath(__file__))}/config.yaml", "r")
        )['launcher-path']
        
        order = [
            "sbatch",
            f'--output={_output}',
            f'--error={_error}',
            f'--nodelist={args.node}',
            batch, 
            args.env,
            id
        ]
        
        subprocess.run(order)

class VandelviraDataArgumentParser(argparse.ArgumentParser):
    
    def error(self, message):
        self.print_help()
        print("\nERROR:", message, file=sys.stderr)
        print("\nAdditional details:")
        print("- Use --env <virtual-environment>.")
        print("- Use --node <node-name>. Available nodes: 'nodo01', 'nodo02', 'nodo03', 'nodo04', 'nodo05', 'nodo06', 'nodo07'. Default (and recommended) is 'nodo05'.")
        print("- Use --id <identifier> to process a specific dataset.")
        print("- Or use --all to process every dataset, optionally with --domain <name>.")
        self.exit(2)

if __name__ == "__main__":
    
    parser = VandelviraDataArgumentParser(description="Process some arguments.")
    parser.add_argument('--env', type=str, required=True, help="Name of the virtual environment.") # required
    parser.add_argument('--node', type=str, help="Name of the virtual environment.", default="nodo05") # optional
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--id', type=str, help="Identifier of the dataset to process.")
    group.add_argument('--all', action='store_true', help="Process all datasets.")
    parser.add_argument('--domain', type=str, help="Restrict processing to a specific domain (only valid with --all).")
    
    args = parser.parse_args()
    main(args)
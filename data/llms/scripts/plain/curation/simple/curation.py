import sys, os, yaml
sys.path.append(f"{os.path.dirname(os.path.abspath(__file__))}/")
sys.path.append(f"{os.path.dirname(os.path.abspath(__file__))}/../")
sys.path.append(os.path.abspath("./"))
from utils.utils_alia import ALIADataUtils as autils
from dataset_curator import DatasetCurator
from documentation.documentation_generator import DocumentationGenerator

import argparse

def main(args):
    
    dg = DocumentationGenerator()
    
    print(f"Processing [curation] dataset '{args.id}'")

    curated = dg.check_curation(args.id)
    
    config = yaml.safe_load(
        open(os.path.abspath("data/llms/scripts/plain/config.yaml"), "r")
    )

    if not curated or args.FORCE:
        
        if curated and args.FORCE:
            dataset_path = autils.search_dataset_dir(config['root'], args.id)
            os.rename(dataset_path, f"{dataset_path}_backup")
        
        # Process the dataset text
        curator = DatasetCurator()
        try:
            curator.process_dataset(args.id)
        except Exception as e:
            print(f"\t- Error processing dataset '{args.id}': {e}")
    else:
        print(f"\t- Dataset '{args.id}' has already been processed.")

    # Update resources list
    dg.generate_yaml_resources()

class VandelviraArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_help()
        print("\nERROR:", message, file=sys.stderr)
        print("\nAdditional details:")
        print("- Use only --id <identifier> to process a specific dataset.")
        print("- Use --FORCE to force the documentation of the dataset.")

        self.exit(2)

if __name__ == "__main__":
    parser = VandelviraArgumentParser(description="Process some arguments.")
    parser.add_argument('--id', type=str, required=True, help="Identifier of the dataset to process.")
    parser.add_argument('--FORCE', action='store_true', help="Force documentation of the dataset.")

    args = parser.parse_args()

    main(args)

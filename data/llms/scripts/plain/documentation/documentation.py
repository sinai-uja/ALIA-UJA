import sys, os
sys.path.append(f"{os.path.dirname(os.path.realpath(__file__))}/")

from documentation_generator import DocumentationGenerator
from metadata_generator import MetadataGenerator

import argparse
import traceback

def main(args):
    
    dg = DocumentationGenerator()

    print(f"Processing [documentation] dataset '{args.id}'")
    metadata_yaml, metadata_json, datasheet_report = dg.check_documentation(args.id)
    
    if not (metadata_yaml and metadata_json and datasheet_report) or args.FORCE:
                
        # metadata
        if not (metadata_yaml and metadata_json) or args.FORCE:
            md = MetadataGenerator()
            try:
                md.generate_metadata(args.id) # metadata.yaml and metadata.json
                print(f"\tMetadata files for dataset '{args.id}' have been generated successfully.")
            except Exception as e:
                print(f"\t- Error generating metadata file for '{args.id}': {e}")
                traceback.print_exc()

        # report
        if not datasheet_report or args.FORCE:
            print(f"\tGenerating datasheet and token report for dataset '{args.id}'...")
            try:
                dg.generate_report(args.id)         # generate report
                print(f"\tDataset '{args.id}' reports have been documented successfully.")
            except Exception as e:
                print(f"\t- Error generating the metadata report for '{args.id}': {e}")
                traceback.print_exc()
    
        try:
            dg.update_resources_yaml(args.id)           # update resources list in yaml file
            dg.update_resources_csv(args.id)            # update resources list in csv file
            dg.generate_resources_per_domain_csv(args.id)      # update resources per domain csv file
            dg.generate_dossier(args.id)                 # update dossier
            print(f"Dataset '{args.id}' has been processed successfully.")
        except Exception as e:
            print(f"\t- Error generating resource files '{args.id}': {e}")
            traceback.print_exc()

    else:
        dg.generate_resources_per_domain_csv(args.id)
        dg.generate_dossier(args.id)
        print(f"\t- Dataset '{args.id}' is already documented. Skipping...")


class VandelviraArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_help()
        print("\nERROR:", message, file=sys.stderr)
        print("\nAdditional details:")
        print("- Use --id <identifier> to process a specific dataset.")
        print("- Use --FORCE to force the documentation of the dataset.")
        self.exit(2)

if __name__ == "__main__":
    
    parser = VandelviraArgumentParser(description="Process some arguments.")
    parser.add_argument('--id', type=str, required=True, help="Identifier of the dataset to process.")
    parser.add_argument('--FORCE', action='store_true', help="Force documentation of the dataset.")

    args = parser.parse_args()
    main(args)
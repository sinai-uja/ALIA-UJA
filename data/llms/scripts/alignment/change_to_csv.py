from pathlib import Path

import pandas as pd


def main() -> None:
    output_dir = Path(__file__).resolve().parent / "dpo_data"

    for jsonl_file in output_dir.glob("*.jsonl"):
        csv_file = jsonl_file.with_suffix(".csv")
        df = pd.read_json(jsonl_file, lines=True)
        df.to_csv(csv_file, index=False)


if __name__ == "__main__":
    main()

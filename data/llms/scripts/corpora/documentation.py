# ------------------------------------------------------------------------------------------------------------------------
# Generar documentación de corpus @sduenas
# ------------------------------------------------------------------------------------------------------------------------

import os, sys, json, yaml
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import load_config

# params
config = load_config(os.path.join(os.path.realpath(__file__), "config.yaml"))
data_path_dir = config['root-data'].format(domain=config['domain'])
output_path_dir = os.path.join(
    config['root-corpora'], 
    config['path-corpus-dir'].format(
        domain=config['domain'], 
        name=config['name']
    )
)

# ------------------------------------------------------------------------------------------------------------------------

intro = config['documentation']['templates']['intro']

temp_text_datasets = config['documentation']['templates']['datasets']

info = json.load(
    open(
        os.path.join(
            config['root-corpora'],
            config['domain'],
            config['info_path'].format(name=config['name'])
        ), 
        "r"
    )
)

for d in info['datasets']:
    try:
        metadata = yaml.safe_load(open(os.path.join(data_path_dir, d, "metadata.yaml"), "r"))
        temp_text_datasets += f"- **{d}**: {metadata['alia:dataset']['dc:title']}\n"
        temp_text_datasets += f"\t{metadata['alia:dataset']['dc:description'].replace("\n", "")}\n"
        temp_text_datasets += f"\t- Metadata file: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/{config['domain']}/{d}/metadata.yaml)\n" # !!!
    except Exception as e:
        print(f"WARNING: El dataset {d} no está en {data_path_dir}")

temp_text_table = config['documentation']['templates']['statistics']
table = info['info']
for d in info['datasets']:
    try:
        tokens_formatted = f"{table[d]['tokens']:,}".replace(",", ".")
        instances_formatted = f"{table[d]['instances']:,}".replace(",", ".")
        tokens_pct = f"{table[d]['tokens%']*100:.2f}".replace(".", ",")
        instances_pct = f"{table[d]['instances%']*100:.2f}".replace(".", ",")
        temp_text_table += f"| {d} | {tokens_formatted} | {instances_formatted} | {tokens_pct}% | {instances_pct}% |\n"
    except Exception as e:
        print(f"WARNING: El dataset {d} no está en {data_path_dir}")

total_tokens_formatted = f"{info['total-tokens']:,}".replace(",", ".")
total_instances_formatted = f"{info['total-instances']:,}".replace(",", ".")
temp_text_table += f"| **TOTAL** | **{total_tokens_formatted}** | **{total_instances_formatted}** |  |  |\n"

with open(
    os.path.join(
        output_path_dir, 
        f"ALIA-{config['name']}-template.md"
    ), 
    "w"
) as f:
    f.write(intro + temp_text_datasets + temp_text_table)

# ------------------------------------------------------------------------------------------------------------------------

# placeholders
placeholders = config['documentation']['templates']['placeholders']

with open(
    os.path.join(
        config['root-corpora'], 
        config['documentation']['template_path']
    ), 
    "r"
) as file:
    template = file.read()

# initial placeholders
_template = template
# 1
_template = _template.replace("<corpus-name>", f"ALIA-{config['name']}")
# 2
for tag, text in placeholders.items():
    _template = _template.replace(tag, text)

# statistics
temp_text_table = ""
table = info['info']
entries = []
for d in info['datasets']:
    try:
        tokens_formatted = f"{table[d]['tokens']:,}".replace(".", ",")
        instances_formatted = f"{table[d]['instances']:,}".replace(".", ",")
        tokens_pct = f"{table[d]['tokens%']*100:.2f}".replace(",", ".")
        entries.append(f"| {d} | {tokens_formatted} | {instances_formatted} | {tokens_pct}% |")
    except Exception as e:
        print(f"WARNING: El dataset {d} no está en {data_path_dir}")

_template = _template.replace("<TABLE-DATA>", "\n".join(entries))

total_tokens_formatted = f"{info['total-tokens']:,}".replace(".", ",")
total_instances_formatted = f"{info['total-instances']:,}".replace(".", ",")

_template = _template.replace("<tokens-total>", total_tokens_formatted)
_template = _template.replace("<tokens-instances>", total_instances_formatted)

with open(
    os.path.join(
        output_path_dir, 
        config['documentation']['output_path'].format(name=config['name'])), 
    "w"
) as file:
    file.write(_template)
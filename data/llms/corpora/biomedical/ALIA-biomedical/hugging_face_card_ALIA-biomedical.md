---
license: cc-by-sa-4.0
task_categories:
- text-generation
- fill-mask
- question-answering
- text-classification
language:
- es
tags:
- biomedical
- spanish
- medical
- corpus
- nlp
- healthcare 
size_categories:
- 1M<n<10M
---

# Dataset Card for ALIA biomedical Corpus

The **ALIA biomedical Corpus** constitutes a strategic data infrastructure designed to support research in life sciences, healthcare, and clinical computational linguistics. By ensuring systematic access to multiple official medical repositories in a single consolidated dataset, it provides a robust foundation for Spanish-language BioNLP. With over 10 million instances and more than 5 billion tokens, it represents the most comprehensive corpus of biomedical and clinical-related texts in Spanish, combining source heterogeneity with advanced technical curation via datatrove.

## Table of Contents
- [Dataset Card for ALIA biomedical Corpus](#dataset-card-for-alia-biomedical-corpus)
  - [Table of Contents](#table-of-contents)
  - [Dataset Details](#dataset-details)
    - [Dataset Description](#dataset-description)
    - [Dataset Sources](#dataset-sources)
    - [Uses](#uses)
  - [Dataset Structure](#dataset-structure)
    - [Data Instances](#data-instances)
    - [Data Fields](#data-fields)
    - [Data Splits](#data-splits)
    - [Example Usage](#example-usage)
  - [Dataset Creation](#dataset-creation)
    - [Curation Rationale](#curation-rationale)
    - [Source Data](#source-data)
      - [Clinical Guidelines and Protocols](#clinical-guidelines-and-protocols)
      - [Pharmaceutical and Toxicological Data](#pharmaceutical-and-toxicological-data)
      - [Scientific Literature and Academic Resources](#scientific-literature-and-academic-resources)
      - [Clinical Records and Specialized Corpus](#clinical-records-and-specialized-corpus)
      - [Reference and NLP Resources](#reference-and-nlp-resources)
    - [Data Collection and Processing](#data-collection-and-processing)
      - [Preprocessing system](#preprocessing-system)
    - [Annotations](#annotations)
    - [Personal and Sensitive Information](#personal-and-sensitive-information)
    - [Citation](#citation)
  - [Considerations for Using the Data](#considerations-for-using-the-data)
    - [Social Impact of Dataset](#social-impact-of-dataset)
    - [Discussion of Biases](#discussion-of-biases)
    - [Other Known Limitations](#other-known-limitations)

## Dataset Details

### Dataset Description

The ALIA Biomedical Corpus is an open-access strategic data infrastructure that compiles and organizes an extensive collection of official documents and scientific texts from the Spanish biomedical and clinical domain. Its purpose is to provide a homogeneous, structured, and accessible documentary base for researchers, healthcare professionals, and computational linguists interested in the analysis and exploitation of medical, pharmacological, and clinical texts in Spanish.

This corpus has been designed with an integrative approach that encompasses clinical guidelines, medical registries, scientific publications, and official health bulletins. It covers key areas such as pharmacology, epidemiology, public health, and specialized medical research. This diversity allows for comprehensive coverage of the documentary ecosystem that regulates and records medical and scientific activity in the Spanish-speaking world.

The scope of the corpus, with approximately **10 million instances** and over **5.5 billion tokens**, makes it an unprecedented source for the development of Large Language Models (LLMs) specialized in medicine, Natural Language Processing (NLP) tools applied to clinical language, and research in medical informatics. Its processed nature facilitates advanced utilization in text mining, semantic modeling, information retrieval, and the construction of artificial intelligence systems specialized in healthcare and life sciences.


- **Curated by:** SINAI Research Group (Intelligent Systems for Information Access) - Universidad de Jaén, through the Center for Advanced Studies in Information and Communication Technologies (CEATIC).
- **Funded by:** This work is funded by the Ministerio para la Transformación Digital y de la Función Pública - Funded by EU – NextGenerationEU within the framework of the project Desarrollo de Modelos ALIA.
- **Language(s) (NLP):** es (Spanish)
- **License:** [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)

### Dataset Sources

- **Paper:** [N/A]

### Uses

The primary purpose of this corpus is to serve as a foundation for training and evaluating language models specialized in the Spanish biomedical domain, with applications in:

- Training large language models (LLMs) specialized in Spanish biomedical text
- Biomedical information retrieval systems
- Question-answering systems about Spanish biomedical
- Research in natural language processing applied to the biomedical domain

## Dataset Structure

### Data Instances

Each instance in the corpus has the following structure:

```
{
    'id': '7072382',
    'text': 'El número de lesiones del ligamento cruzado aumentó considerablemente entre 1970 y 1979 en las estadísticas de la Schweizerische Unfallversicherungsanstalt . Se llama la atención para nuevos y más diferenciados métodos de diagnóstico y terapia. La tendencia de la tasa de nulidad debido a la mejora de los diagnósticos y de la terapia solo puede observarse tendencia. Las medidas preventivas deben ser demandadas sobre todo en el deporte ya que encontramos el origen de más y más lesiones del ligamento cruzado',
    'source_id': 'Translated_Pubmed'
}
```

### Data Fields

- **id** (string): Unique document identifier
- **text** (string): Clean and processed textual content of the document
- **source_id** (string): Source of origin of the document

### Data Splits

The complete dataset contains the following main sources with their statistics:
| Source Dataset | Num Tokens | Num Instances | Tokens Percentage | Link |
| :--- | :---: | :---: | :---: | :--- |
| SECOMCYC | 428,621 | 60 | 0.0077% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/SECOMCYC) |
| SER | 441,098 | 12 | 0.0079% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/SER) |
| SANGVA | 504,259 | 7 | 0.0090% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/SANGVA) |
| Ministerio_Sanidad_Medic_Trans | 519,871 | 36 | 0.0093% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/Ministerio_Sanidad_Medic_Trans) |
| CARMEN_I | 742,437 | 1,310 | 0.0133% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/CARMEN_I) |
| Tox_Habits | 1,061,706 | 1,040 | 0.0191% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/Tox_Habits) |
| SPA_Junta_De_Andalucia | 1,206,355 | 27 | 0.0217% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/SPA_Junta_De_Andalucia) |
| AEPCP | 1,507,891 | 40 | 0.0271% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/AEPCP) |
| RECCMI | 1,827,907 | 30 | 0.0328% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/RECCMI) |
| AEPED | 1,946,814 | 788 | 0.0350% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/AEPED) |
| Guia_Salud | 2,015,004 | 21 | 0.0362% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/Guia_Salud) |
| BARR_2 | 2,108,752 | 2,858 | 0.0378% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/BARR_2) |
| Ministerio_Sanidad_Estrategias | 6,038,859 | 172 | 0.1084% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/Ministerio_Sanidad_Estrategias) |
| Prod_Cient_AETSA | 11,169,765 | 303 | 0.2005% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/Prod_Cient_AETSA) |
| MedlinePlus | 11,259,425 | 5,531 | 0.2021% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/MedlinePlus) |
| Multi_Clin_Sum | 38,208,297 | 53,691 | 0.6858% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/Multi_Clin_Sum) |
| MESINESP_2 | 60,639,295 | 135,286 | 1.0884% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/MESINESP_2) |
| Wikipedia_Biomedical | 64,881,930 | 39,601 | 1.1646% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/Wikipedia_Biomedical) |
| CIMA_AEMPS | 123,472,173 | 16,392 | 2.2162% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/CIMA_AEMPS) |
| Miscelanea_Roberta | 1,554,077,398 | 11,776 | 27.8939% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/Miscelanea_Roberta) |
| Translated_Pubmed | 3,687,325,552 | 10,033,666 | 66.1833% | [GitHub](https://github.com/sinai-uja/ALIA-UJA/tree/dev/data/llms/datasets/biomedical/Translated_Pubmed) |
| **TOTAL** | **5,571,383,409** | **10,302,647** | **100.00%** | - |


### Example Usage

To load the dataset:

```
from datasets import load_dataset

# Load the complete dataset
data = load_dataset("SINAI/ALIA-biomedical", trust_remote_code=True)

# Load with streaming (recommended for large corpora)
data = load_dataset("SINAI/ALIA-biomedical", trust_remote_code=True, streaming=True)
```

Example of data access:

```
# Access an example
example = data['train']
print(f"ID: {example['id']}")
print(f"Source: {example['source_id']}")
print(f"Text: {example['text'][:200]}...")
```

## Dataset Creation

### Curation Rationale

This corpus was created to address the need for specialized linguistic resources in Spanish biomedical language, fundamental for the development of the ALIA foundational model within the Spanish Government's Artificial Intelligence Strategy 2024. Its design responds to the demand from researchers, legal professionals, and data scientists who require systematic access to Spanish official documentation for AI model training and specialized linguistic analysis.

### Source Data

The corpus integrates documentation from multiple Spanish clinical and biomedical repositories:

#### Clinical Guidelines and Protocols
- **National Health System (GuíaSalud)**: Active Clinical Practice Guidelines based on scientific evidence.
- **Regional Health Services**: Includes guidelines and care protocols from the Andalusian Health Service (SAS) and the Valencian Community Health System (SANGVA).
- **Medical Societies**: Clinical protocols and guidelines from specialized societies such as Oncology (SEOM), Rheumatology (SER), and Oral and Maxillofacial Surgery (SECOMCYC).

#### Pharmaceutical and Toxicological Data
- **CIMA (AEMPS)**: Official information on authorized medicines, technical data sheets, and evaluation reports.
- **Pediamécum (AEPED)**: Specialized dataset on pediatric medications and active ingredients.
- **ToxHabits-NER**: Gold-standard annotated data for detecting toxic habits (tobacco, alcohol, and drugs) in clinical texts.

#### Scientific Literature and Academic Resources
- **MESINESP2**: Large-scale dataset for medical semantic indexing, including clinical trials, scientific articles (LILACS/IBECS), and medical patents.
- **Translated PubMed**: Spanish translations of PubMed titles and abstracts with MeSH and DeCS indexing.
- **Scientific Production (AETSA & AEPCP)**: Health technology assessment reports and scientific publications on clinical psychology.

#### Clinical Records and Specialized Corpus
- **CARMEN-I**: Anonymized electronic health records from Hospital Clínic de Barcelona.
- **RECCMI**: Real-world clinical cases in internal medicine (2018-2025).
- **MultiClinSum**: Multilingual corpus for the automatic summarization of clinical case reports.

#### Reference and NLP Resources
- **Biomedical Abbreviations (BARR2)**: Specialized resource for the recognition and resolution of clinical abbreviations.
- **Wikipedia Biomedical**: Comprehensive collection of biomedical terms and definitions from the Spanish Wikipedia.
- **Ministerio de Sanidad**: Strategic health plans, transfusion medicine reports, and national health policies.


All data come from official and publicly accessible sources.

### Data Collection and Processing

#### Preprocessing system

The corpus is based on a previous version of nearly 20 billion tokens that was processed with an advanced cleaning methodology based on [datatrove](https://github.com/huggingface/datatrove). This system automates the cleaning and preparation of large volumes of text in Spanish, eliminating duplicate and low-quality content.

**Step 1: Configuration and paths loading**
- Loading YAML configuration files with parameters (language threshold, filters, etc.)
- Definition of work paths and processing environment preparation

**Step 2: Language filtering**
- Automatic language analysis of each document
- Selection of Spanish texts according to confidence threshold

**Step 3: MinHash deduplication**
- Advanced detection of repeated or highly similar content
- Use of scalable comparison algorithms for large volumes

**Step 4: Quality filters and final cleaning**
- Application of multiple specialized filters
- Correction of encoding errors
- Removal of sensitive or identifiable information

Token counting was performed using [tiktoken](https://github.com/openai/tiktoken).

The final result is a corpus of **5571383409 tokens** distributed across **10302647**, optimized for language model training.

### Annotations

The dataset does not contain additional annotations beyond the structural metadata extracted during processing (dates, document types, source).

### Personal and Sensitive Information

The corpus has been subjected to cleaning processes to remove sensitive or identifiable information according to data protection regulations. Documents come from public official sources, although some may contain references to names in official contexts (legislators, public officials in the exercise of their duties). Users are advised to apply additional controls depending on the specific use of the corpus.

### Citation
[N/A]

## Considerations for Using the Data

### Social Impact of Dataset

This corpus represents a significant advance in democratizing access to biomedical information in Spanish, facilitating the development of AI tools that can improve access to justice and understanding of regulations by citizens and professionals. It contributes to the national strategic objective of developing foundational AI models in Spanish with ethical and transparency standards.

### Discussion of Biases

The corpus reflects the biomedical language used in Spanish, which may present biases inherent to:

- Formal Scientific Language: The corpus primarily consists of formal, clinical, and academic language. It may not be representative of colloquial Spanish or informal patient-doctor interactions (e.g., social media health discussions or medical forums).

- Geographic Representation: There may be an overrepresentation of certain Spanish autonomous communities or regions, depending on the availability and digitization level of their specific health and clinical repositories.

- Technical Anglicisms: In segments like the EuroPat (medical patents) or Translated_Pubmed, some technical anglicisms or translation artifacts may be present, reflecting the globalized nature of medical terminology and patent documentation.

- Regional Regulatory Focus: The data reflects regulatory frameworks and institutional perspectives specific to the Spanish healthcare system, which might differ from those in other Spanish-speaking regions in Latin America.

### Other Known Limitations

- The quality of original texts depends on official digitization and publication, and may contain OCR errors in historical documents
- Temporal coverage varies by source, being more complete in recent years
- The vocabulary is limited to the biomedical domain and may not be representative of other Spanish domains
- Some technical documents may include tables, formulas, or structured elements that are lost in the textual version
- Token and instance statistics by dataset correspond to data prior to final cleaning with datatrove

---

**Contact:** [ALIA Project](https://www.alia.gob.es/) - [SINAI Research Group](https://sinai.ujaen.es) - [Universidad de Jaén](https://www.ujaen.es/)

**More information:** [SINAI Research Group](https://sinai.ujaen.es) | [ALIA-UJA Project](https://github.com/sinai-uja/ALIA-UJA)

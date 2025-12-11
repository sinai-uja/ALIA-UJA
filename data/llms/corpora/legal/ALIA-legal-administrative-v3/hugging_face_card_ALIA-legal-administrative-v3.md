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
- legal
- administrative
- spanish
- BOE
- legislation

size_categories:
- 1M<n<10M
---

# Dataset Card for ALIA legal-administrative Corpus

The **ALIA Legal and Administrative Corpus** constitutes a strategic data infrastructure to support research in social sciences, legal studies, and computational linguistics, ensuring systematic access to multiple official repositories in a single consolidated dataset. With over **7 million instances** and more than **5 billion tokens**, it represents the most comprehensive corpus of legal and administrative texts in Spanish, combining source heterogeneity and advanced technical curation with datatrove.


## Table of Contents
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
  - [Data Collection and Processing](#data-collection-and-processing)
  - [Annotations](#annotations)
  - [Personal and Sensitive Information](#personal-and-sensitive-information)
  - [Citation](#citation)
- [Considerations for Using the Data](#considerations-for-using-the-data)
  - [Social Impact of Dataset](#social-impact-of-dataset)
  - [Discussion of Biases](#discussion-of-biases)
  - [Other Known Limitations](#other-known-limitations)

## Dataset Details

### Dataset Description

The **ALIA Legal and Administrative Corpus** is an open-access data resource that compiles and organizes an extensive collection of official documents from the Spanish legal and administrative domain. Its purpose is to provide a homogeneous, structured, and accessible documentary base for researchers, academics, legal professionals, and public administration practitioners interested in the analysis and exploitation of normative, legislative, and administrative texts in Spanish.

This corpus has been designed with an integrative approach that encompasses state, regional, and provincial official bulletins (BOE, BOJA, BOCYL, BORM, among others), specialized registries (BORME, Legal Library, Building Technical Code), ministerial documents in key areas such as energy, environment, climate change, defense, and national security, public tenders and contracts, as well as parliamentary proceedings from the Andalusian Parliament. This diversity allows for comprehensive coverage of the documentary ecosystem that regulates institutional, economic, and social activity in Spain.

The scope of the corpus, with over **7 million instances** and more than **5 billion tokens**, makes it an unprecedented source for academic study of Spanish regulations, comparative legislative analysis, development of natural language processing (NLP) tools applied to legal-administrative language, and research in institutional open data. Its open and processed nature facilitates both manual exploration by legal professionals and documentation specialists, as well as advanced utilization in text mining projects, semantic modeling, information retrieval, and construction of artificial intelligence systems specialized in law and public administration.

- **Curated by:** SINAI Research Group (Intelligent Systems for Information Access) - Universidad de Jaén, through the Center for Advanced Studies in Information and Communication Technologies (CEATIC).
- **Funded by:** This work is funded by the Ministerio para la Transformación Digital y de la Función Pública - Funded by EU – NextGenerationEU within the framework of the project Desarrollo de Modelos ALIA.
- **Language(s) (NLP):** es (Spanish)
- **License:** [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)

### Dataset Sources

- **Repository:** [ALIA Project - SINAI](https://github.com/sinai-uja/ALIA-UJA)
- **Paper:** [More Information Needed]

### Uses

The primary purpose of this corpus is to serve as a foundation for training and evaluating language models specialized in the Spanish legal-administrative domain, with applications in:

- Training large language models (LLMs) specialized in Spanish legal-administrative text
- Legal-administrative information retrieval systems
- Question-answering systems about Spanish legal-administrative
- Research in natural language processing applied to the legal-administrative domain

## Dataset Structure

### Data Instances

Each instance in the corpus has the following structure:

```
{
    'id': 'BOE_2024_123456',
    'text': 'DISPONICIONES GENERALES. Artículo 1. Objeto y ámbito de aplicación. 1. La presente Ley tiene por objeto establecer las bases del régimen jurídico del sector público y de la actividad administrativa, así como regular los principios que deben inspirar la actuación de las...',
    'source_id': 'Boletin_Oficial_Estado'
}
```

### Data Fields

- **id** (string): Unique document identifier
- **text** (string): Clean and processed textual content of the document
- **source_id** (string): Source of origin of the document

### Data Splits

The complete dataset contains the following main sources with their statistics:

| Source Dataset | Num Tokens | Num Instances | Tokens Percentage |
|--------|------------|---------------|----------|
| Agen_Urb_Esp | 335,451 | 11 | 0.0065% |
| Biblioteca_Juridica | 2,527,731 | 22 | 0.0487% |
| Boletin_Oficial_Canarias | 141,562,339 | 47,982 | 2.7258% |
| Boletin_Oficial_Cantabria | 349,985,165 | 156,256 | 6.7389% |
| Boletin_Oficial_Castilla_Y_Leon | 616,134,537 | 209,921 | 11.8636% |
| Boletin_Oficial_Ceuta | 37,172,910 | 868 | 0.7158% |
| Boletin_Oficial_Estado | 1,275,960,977 | 264,436 | 24.5685% |
| Boletin_Oficial_Junta_Andalucia | 870,941,236 | 212,086 | 16.7699% |
| Boletin_Oficial_Provincial_Cordoba | 248,902,474 | 9,112 | 4.7926% |
| Boletin_Oficial_Provincial_Granada | 22,909,841 | 282 | 0.4411% |
| Boletin_Oficial_Provincial_Jaen | 106,913,362 | 63,652 | 2.0586% |
| Boletin_Oficial_Provincial_Sevilla | 5,082,865 | 49 | 0.0979% |
| Boletin_Oficial_Region_Murcia | 530,661,205 | 217,865 | 10.2178% |
| Boletines_Oficiales_Defensa | 1,550,715 | 38 | 0.0299% |
| Codigo_Tecnico_Edificacion | 1,319,740 | 56 | 0.0254% |
| Departamento_Seguridad_Nacional | 1,469,757 | 62 | 0.0283% |
| EuroPat | 673,770,502 | 5,804,732 | 12.9734% |
| Licitaciones | 65,801,579 | 630 | 1.2670% |
| Ministerio_Transicion_Ecologica_Calidad_Evaluacion_Ambiental | 14,069,838 | 2,272 | 0.2709% |
| Ministerio_Transicion_Ecologica_Cambio_Climatico | 4,636,644 | 453 | 0.0893% |
| Ministerio_Transicion_Ecologica_Energia | 5,479,445 | 327 | 0.1055% |
| Ministerio_Transicion_Ecologica_Ministerio | 7,937,682 | 602 | 0.1528% |
| Ministerio_Transicion_Ecologica_Organismo_Autonomo_Parques_Nacionales | 13,425,207 | 605 | 0.2585% |
| Ministerio_Transicion_Ecologica_Reto_Demografico | 416,145 | 30 | 0.0080% |
| Ministerio_Transicion_Ecologica_Sala_Prensa | 90,664 | 2 | 0.0017% |
| Ministerio_Vivienda_Agenda_Urbana | 266,487 | 9 | 0.0051% |
| NORMA | 25,811,082 | 6,853 | 0.4970% |
| ParlaMint-ES-AN | 68,164,267 | 658 | 1.3125% |
| Registro_Mercantil_Borme | 100,173,907 | 31,880 | 1.9288% |
| **TOTAL** | **5,193,473,754** | **7,031,751** |  |  |

### Example Usage

To load the dataset:

```
from datasets import load_dataset

# Load the complete dataset
data = load_dataset("sinai-uja/ALIA-legal-administrative", trust_remote_code=True)

# Load with streaming (recommended for large corpora)
data = load_dataset("sinai-uja/ALIA-legal-administrative", trust_remote_code=True, streaming=True)
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

This corpus was created to address the need for specialized linguistic resources in Spanish legal and administrative language, fundamental for the development of the ALIA foundational model within the Spanish Government's Artificial Intelligence Strategy 2024. Its design responds to the demand from researchers, legal professionals, and data scientists who require systematic access to Spanish official documentation for AI model training and specialized linguistic analysis.

### Source Data

The corpus integrates documentation from multiple Spanish official repositories:

#### Official Bulletins
- **Boletín Oficial del Estado** (Spanish State Official Bulletin): Spanish state legislation
- **Regional Bulletins**: Boletín Oficial de la Junta de Andalucía (Andalusia), Boletín Oficial de Castilla y León (Castile and León), Boletín Oficial de la Región de Murcia (Murcia), Boletín Oficial de Cantabria (Cantabria), Boletín Oficial de Canarias (Canary Islands), Boletín Oficial de Ceuta (Ceuta)
- **Provincial Bulletins**: Boletín Oficial Provincial de Granada, Boletín Oficial Provincial de Jaén, Boletín Oficial Provincial de Sevilla, Boletín Oficial Provincial de Cordoba

#### Specialized Registries
- **Registro Mercantil Borme**: Commercial Registry
- **Biblioteca Jurídica**: Legal codes and compilations
- **EuroPat**: Parallel corpus of European patents
- **Código Técnico de la Edificación**: Building Technical Code

#### Ministerial Documentation
- **Ministerio para la Transición Ecológica y el Reto Demográfico**: Includes subsections on Climate Change, Energy, Environmental Quality and Assessment, Demographic Challenge, and National Parks
- **Ministerio de Defensa**: Defense-related regulations and documents
- **Ministerio de Vivienda y Agenda Urbana**: Housing and Urban Planning
- **Departamento de Seguridad Nacional**: National Security

#### Other Documents
- **Licitaciones**: Public contracts and tenders
- **ParlaMint-ES-AN**: Parliamentary proceedings from the Parliament of Andalusia (1982-2025)
- **NORMA**: Economic and financial regulations
    

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

The final result is a corpus of **5,193,473,754 tokens** distributed across **7,031,751 instances **, optimized for language model training.

### Annotations

The dataset does not contain additional annotations beyond the structural metadata extracted during processing (dates, document types, source).

### Personal and Sensitive Information

The corpus has been subjected to cleaning processes to remove sensitive or identifiable information according to data protection regulations. Documents come from public official sources, although some may contain references to names in official contexts (legislators, public officials in the exercise of their duties). Users are advised to apply additional controls depending on the specific use of the corpus.

### Citation

```
```

## Considerations for Using the Data

### Social Impact of Dataset

This corpus represents a significant advance in democratizing access to legal and administrative information in Spanish, facilitating the development of AI tools that can improve access to justice and understanding of regulations by citizens and professionals. It contributes to the national strategic objective of developing foundational AI models in Spanish with ethical and transparency standards.

### Discussion of Biases

The corpus reflects the legal-administrative language used in Spanish, which may present biases inherent to:

- Formal institutional language, not representative of colloquial Spanish
- Possible overrepresentation of certain autonomous communities depending on the availability of digitized data
- The EuroPat corpus may contain technical anglicisms due to patent translations
- Reflection of regulatory frameworks and institutional perspectives specific to the Spanish context

### Other Known Limitations

- The quality of original texts depends on official digitization and publication, and may contain OCR errors in historical documents
- Temporal coverage varies by source, being more complete in recent years
- The vocabulary is limited to the legal-administrative domain and may not be representative of other Spanish domains
- Some technical documents may include tables, formulas, or structured elements that are lost in the textual version
- Token and instance statistics by dataset correspond to data prior to final cleaning with datatrove

---

**Contact:** [ALIA Project](https://www.alia.gob.es/) - [SINAI Research Group](https://sinai.ujaen.es) - [Universidad de Jaén](https://www.ujaen.es/)

**More information:** [SINAI Research Group](https://sinai.ujaen.es) | [ALIA-UJA Project](https://github.com/sinai-uja/ALIA-UJA)

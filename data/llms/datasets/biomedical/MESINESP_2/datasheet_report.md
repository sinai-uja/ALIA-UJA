# MESINESP2 Corpora: Annotated data for medical semantic indexing in Spanish - Dataset Report
*Grupo de investigación de Sistemas Inteligentes de Acceso a la Información | sinai@ujaen.es | Proyecto ALIA*
---
## Table of Contents
- [General Information](#general-information)
- [Source](#source)
- [Usage](#usage)
- [Composition](#composition)
- [Collection Process](#collection-process)
- [Curation Process](#curation-process)
---
## General Information
### Dataset ID
MESINESP_2

### Dataset Name
MESINESP2 Corpora: Annotated data for medical semantic indexing in Spanish

### Description
*Brief summary of dataset content and origin.*
MESINESP2 Corpora is a Spanish-language dataset designed for biomedical semantic indexing and natural language processing. It contains three types of documents:

Scientific Literature (MESINESP-L): Articles from the LILACS and IBECS databases, annotated with DeCS codes. It includes more than 237,000 training articles, a development set of 1,065 expert-annotated articles, and a test set of 491 abstracts.

Clinical Trials (MESINESP-T): Records from the Spanish Registry of Clinical Studies (REEC), with 3,560 training trials and development and test sets manually annotated by experts.

Patents (MESINESP-P): Spanish-language patents with IPC codes “A61P” and “A61K31,” selected for semantic similarity to MESINESP-L, with 115 development documents and 119 test documents.

Additionally, each set includes JSON files. with biomedical entities (drugs, diseases, symptoms, procedures) automatically extracted using BSC NERs. This resource enables research in automatic classification, information retrieval, and text mining in Spanish-language biomedicine.

## Source
### Original Author
Luis Gasco, Martin Krallinger  Antonio Miranda – Barcelona Supercomputing Center. Instituto de Salud Carlos III – Biblioteca Nacional de Ciencias de la Salud (BNCS).  Proyecto / iniciativa: MESINESP2, dentro de la campaña de evaluación CLEF 2021.  Fuente de datos originales: artículos científicos de SciELO.

### Original Link
https://zenodo.org/records/5602914

### Original Publication Date
24/09/2021

### External Resources
*Dataset dependency classification.*
Self-contained
*All data from the original resource is included in this corpus.*

### License
Creative Commons Attribution 4.0 International (cc-by-4.0)

## Usage
### Original Tasks
Text Classification, Text Generation

### Current Tasks
Text Generation

## Composition
### Domain
Biomedical

### Language
Spanish

### Instances Description
*What each dataset instance contains.*
Articles, clinical trials and patents

### Granularity
Document

### Partitions
Train, Test, Development

## Collection Process
### Download Process
*Method and validation of data retrieval.*
Directly from the zenodo repository

### Sampling
Complete Data

### Collection Timeframe
*Timeline and bottlenecks of data collection.*
1 hour

## Curation Process
### Creation Timeframe
*Complete timeframe of the dataset creation process*
1 hour

---
Sara Dueñas Romero | sduenas@ujaen.es | Proyecto ALIA

**Tabla de contenido**
- [Best Practices for Open Datasets for LLM Training](#best-practices-for-open-datasets-for-llm-training)
	- [Terminology](#terminology)
		- [Openness (acceso libre, abiertos)](#openness-acceso-libre-abiertos)
			- [Openly licensed dataset](#openly-licensed-dataset)
			- [Downloadable/open-access dataset](#downloadableopen-access-dataset)
			- [Replicable dataset](#replicable-dataset)
		- [Legal Compliance (cumplimiento legal)](#legal-compliance-cumplimiento-legal)
		- [Ethics (ética)](#ethics-ética)
		- [*Licensing of the dataset* vs *licensing of the constituent parts*](#licensing-of-the-dataset-vs-licensing-of-the-constituent-parts)
	- [Principles](#principles)
		- [Foster a competitive LLM ecosystem](#foster-a-competitive-llm-ecosystem)
		- [Enable accountability and transparency through reproducibility](#enable-accountability-and-transparency-through-reproducibility)
		- [Minimize harms and enable preference signals](#minimize-harms-and-enable-preference-signals)
		- [Support and improve diversity](#support-and-improve-diversity)
		- [Strive for reciprocity](#strive-for-reciprocity)
		- [Work with other like-minded actors in this space](#work-with-other-like-minded-actors-in-this-space)
		- [Preserve data for the long term](#preserve-data-for-the-long-term)
	- [Best practices](#best-practices)
		- [Encoding preferences in metadata](#encoding-preferences-in-metadata)
			- [The Need for Machine-Readable Preference Signals](#the-need-for-machine-readable-preference-signals)
		- [Data Sourcing](#data-sourcing)
		- [Data Processing](#data-processing)
		- [Data Governance/Release](#data-governancerelease)
		- [Terms of Use](#terms-of-use)
- [Estándar de licencias para el grupo SINAI](#estándar-de-licencias-para-el-grupo-sinai)
	- [Licencias usables](#licencias-usables)

---

# Best Practices for Open Datasets for LLM Training

This summary is based on information from the paper [Towards Best Practices for Open Datasets for LLM Training (Baack et al., 2025)](https://doi.org/10.48550/arXiv.2501.08365)

Importance of **openly available** and **openly licensed** datasets
- Enables developers to build upon others' work (**efficiency**)
- Creates public goods that everyone can use (**availability**)
- Creates **incentives** for volunteer-driven or data donation-based processes
- Enables **scrutiny**, it allows auditors and researches to examine and evaluate the data in a easier and transparent way

## Terminology

This is aimed to clarify the various types of 'openness' in AI data.
### Openness (acceso libre, abiertos)

Openness refers to the accessibility and usability of data.
- **Open accesss**: practices that enable free online access to research outputs like scholarly papers and experimental data.
- **Open source**: culture of co-creation and sharing of code, and also refers to a set of standardized software licenses.
#### Openly licensed dataset

A dataset and its components can be **freely used, modified, and shared by anyone for any purpose**, adhering to the [Open Knowledge Foundation](https://opendefinition.org/)’s Open Definition for data and content.
- Both the dataset as a whole and its individual components must have licenses that permit the same level of freedom.
- The construction of input for a machine learning model involves licensing both the arrangement of the dataset, and the licensing of the individual components

#### Downloadable/open-access dataset

A dataset that is **available for free download, but there is no guarantee about license compliance** (the licensing terms of the data itself may not be open).

#### Replicable dataset

A dataset in which the **data sources and processing steps are disclosed**, enabling an independent party to produce a substantially similar dataset.
- The data sources must be **widely accessible and not internal** or accessed through private agreements.
- Also described in the [Open Source AI Definition](https://opensource.org/ai/drafts/the-open-source-ai-definition-1-0-rc1) as “a substantially equivalent system”.
- The focus here is on the **ability to reproduce the dataset** using the provided information about its creation, even if the resulting dataset is not identical.

### Legal Compliance (cumplimiento legal)

Putting legal requirements into practice. 
- Several areas of law are relevant to dataset construction, including intellectual property, data privacy regulation, and contract law.
- Due to the uncertainty of applying existing laws to new technologies, AI actors must assume some level of legal risk, and differing risk tolerance leads to varied legal decisions.

### Ethics (ética)

Ethics deals with broader questions of justice, equality, resource distribution, and redress of harms.
- An action can be legally compliant without being ethical.
- A project may align with a set of ethical values but still fall short of legal compliance.
- 
### *Licensing of the dataset* vs *licensing of the constituent parts*

A dataset may have a license based on the rights in the arrangement of the dataset as a whole, but this does not grant the compiler the right to change the licensing of the underlying data. The license of the overall dataset may be more permissive than the licenses of its individual components.

## Principles

There are **7 principles** (identified by [30 scholars and practitioners](https://blog.mozilla.org/en/mozilla/dataset-convening/))
1. [[#Foster a competitive LLM ecosystem]]
2. [[#Enable accountability and transparency through reproducibility]]
3. [[#Minimize harms and enable preference signals]]
4. [[#Support and improve diversity]]
5. [[#Strive for reciprocity]]
6. [[#Work with other like-minded actors in this space]]
7. [[#Preserve data for the long term]]

### Foster a competitive LLM ecosystem

A few tech companies should not have too much control over LLM research and development.
 - Dataset builders should offer competitive alternatives and foundations for other developers to build on.
 - Transparent open datasets, which can be audited more widely, help mitigate legal risks in training and using open-source AI models.
 - This makes these models **competitive** with closed AI models and encourages competition (smaller entities are often concerned about legal exposure)

### Enable accountability and transparency through reproducibility

The need for more transparent production pipelines for LLM training datasets.
- Developers should provide clear reasoning for every step in the data collection and filtering process.
- They should also provide **access to the tools and source code needed to replicate** their process.
	- Crucial for auditing the model development process and for increasing accountability for model developers.
- Essential for research because one cannot improve on the best processing setups if these are not known.

### Minimize harms and enable preference signals

Need for **standards** throughout the data production process.
- The goal is not to create a "perfect" dataset, but to develop interoperable standards for data governance.
- The standards should provide easy ways for data subjects and rights holders to express their preferences before model training and to report issues afterward.
- Dataset builders should also have a plan for how to remove content from the dataset because people or organizations may want to opt out.
- **Removal processes could limit both reproducibility and transparency** if not documented well, as well as the competitiveness of open datasets and data availability for research when faced with massive opt-outs on the open web.

### Support and improve diversity

Need for a **wide range of languages and cultural perspectives** in LLM training datasets.
- Datasets that power AI often dramatically under-represent the vast majority of the world's languages, including variants and dialects, as well as marginalized communities.
	- To support LLMs that can be applied globally, datasets need to represent a diversity of languages,
	- Datasets must include a diversity of viewpoints.
	- A diverse mix of data sources should be employed, and each source must be evaluated for its unique strengths and weaknesses related to diversity and quality

### Strive for reciprocity

Data collection should be **mutually beneficial and reciprocal**, **rather than *exploitative***.
- Rights holders typically do not receive direct benefits when their data is included in LLM training datasets.
	- Going beyond basic consent mechanisms and ensuring that **those who contribute data receive some form of benefit**.
- Convince larger institutions, who often hold valuable data, to make their data more open.
- Prevent the exploitation of data contributors, whose data is often used without their direct consent or benefit.

### Work with other like-minded actors in this space

The importance of **collaboration and leveraging existing expertise** when creating open datasets for LLM training; building these datasets is a complex task that requires a wide range of skills and knowledge, and organizations should not attempt to do it alone.
- Collaborate with organizations that have relevant expertise in areas like open access, open data, and content licensing (eg. Wikipedia and Creative Commons)
- **Learn from the experiences of other organizations that have worked on similar issues**.
- Develop a community of practice around open LLM datasets, where people can share knowledge and resources.
> The challenges faced by open dataset builders resemble those encountered in the early days of open source software
> 	Just as in the early days of open source software, the open dataset community relies on community contributions and volunteers

### Preserve data for the long term

Ensure that training datasets for AI are not only accessible now but also **remain available and usable in the future** (how data is stored, formatted, and documented)
- Ensure the data can be used with different systems and tools (**Data Interoperability**)
- The dataset must be preserved and remain accessible over the long term: considering the durability of storage media, the long-term availability of access methods, and the need for ongoing maintenance and updates (**Long-Term Accessibility**)
- **Prevent data loss** due to technological obsolescence or the lack of proper data management
- Create a "**data commons**" where data is not only available but also maintained and preserved over time


## Best practices

List of best practices:
1. [[#Encoding preferences in metadata]]
2. [[#Data Sourcing]]
3. [[#Data Processing]]
4. [[#Data Governance/Release]]
5. [[#Terms of Use]]

### Encoding preferences in metadata

Include and preserve metadata that expresses the preferences of data creators and rights holders when creating open datasets for LLM training.

**Finding openly licensed or public domain content is difficult and often requires manual labor**.

#### The Need for Machine-Readable Preference Signals

Machine-readable preference signals and the preservation of metadata throughout data processing are crucial for downstream data governance.

**Machine-readable preference signals**: standardized ways of encoding the preferences of data creators and rights holders regarding how their content can be used, particularly for AI training
- Designed to be easily interpreted by machines
- Provide a way for data subjects to express their wishes regarding the use of their content
- Allow for more nuanced control, such as specifying certain types of uses that are allowed or disallowed (instead of an all-or-nothing approach)
- **Tool**: [SPDX license identiers](https://spdx.org/licenses/)
- **Legal requirements**: [EU AI Act](https://artificialintelligenceact.eu/ai-act-explorer/): adoption of machine-readable opt-out standards by August 2025, refers to the [EU Copyright Directive's Text and Data Mining](https://www.europarl.europa.eu/RegData/etudes/BRIE/2018/604942/IPOL_BRI(2018)604942_EN.pdf) (TDM)

**Examples**:
- [International Standard Content Code](https://iscc.codes/) (ISCC): ISO standard for creating unique digital identifiers that work regardless of medium
- [Spawning](https://spawning.ai/): ecosystem-wide solution to meet the needs of rights holders and AI developers (Do Not Train Tool Suite)
- [Creative Commons](https://creativecommons.org/2023/08/31/exploring-preference-signals-for-ai-training/): allows more granular control than simply fully allowing or disallowing AI use cases
- [BigCode opt-out process for The Stack](https://github.com/bigcode-project/opt-out-v2): manual option to exclude/remove repositories from the Stack dataset that relies on Github account verification

### Data Sourcing

The most capable LLMs are typically trained on large amounts of diverse and high-quality data.
- What constitutes "high quality" is often ambiguous

Those who compile and provide open data sources significantly influence the data ecosystem and should do so responsibly.

1. **Prioritize Community Resources**: rely on community-driven tools and resources for identifying/collecting data and openly share any custom tools developed

2. **Provide Useful Documentation**: facilitate the fully replication of the data sourcing process.
	- Data reason: document why specific sources were chosen
	- Data acquisition: how the data was acquired
	- Data processing: sharing the source code of any tools used in the process
	- Data creation: if synthetic data is used, full tooling and information regarding its generation must also be provided

3. **Follow and Record Preference Signals**: record associated permissions and the metadata needed to determine each data point.
	- Metadata used to determinate: URL, crawl date, HTTP headers, HTML metadata
	- Licenses associated with code repositories and content
	- Future data governance signals

4. **Increase Diversity and Involve Local Communities**: datasets should employ a mix of sources to capture a broad spectrum of content.

5. **Avoid Over-Reliance on Automated Translations**: automated translations for underrepresented languages are often poor quality and ignore culturally specific aspects.

6. **Share Advancements to Foster Reciprocity**: open content sourcing enhancements should be made available to the commons ecosystem, giving back to the rights holders.

7. **Use Synthetic Data With Care**: it's important to use quality metrics, regular inspections, and ensure it is consistent, accurate, and representative.

8. **Avoid Inflating Datasets with Low-Quality Data**: the quality of the data matters more than the size.

9. **Do Not Capture Highly Sensitive Data**: avoid collecting sensitive data (phone numbers or health information)

**Examples**:
- [Common Pile](https://pile.eleuther.ai/): Released in 2020, EleutherAI’s Common Pile aims to be a fully transparent dataset for training LLMs composed exclusively of public domain and open access data
	- [Datasheet for the Pile](https://arxiv.org/pdf/2201.07311)
	- **[EleutherAI HF Repository](https://huggingface.co/EleutherAI)**
- [Common Corpus](https://huggingface.co/collections/PleIAs/openculture-65d46e3ea3980fdcd66a5613): A multilingual, downloadable from HF, and reproducible public domain dataset
	- [Pleias](https://huggingface.co/PleIAs) later expanded it to include permissibly licensed text, this is called [Expanded Common Corpus](https://huggingface.co/datasets/PleIAs/common_corpus)
	- Spanish Corpora:
		- [Spanish-Public Domain-Newspapers](https://huggingface.co/datasets/PleIAs/Spanish-PD-Newspapers)
		- [Spanish Public Domain Books](https://huggingface.co/datasets/PleIAs/Spanish-PD-Books)
- [Dolma](https://huggingface.co/datasets/allenai/dolma): is a dataset of 3 trillion tokens from a diverse mix of web content, academic publications, code, books, and encyclopedic materials developed by [allenai](https://allenai.org/) (==English exclusive==)
- [FineWeb](https://huggingface.co/datasets/HuggingFaceFW/fineweb) and [RenedWeb](https://huggingface.co/datasets/tiiuae/falcon-refinedweb): two downloadable datasets that fully rely on Common Crawl, a massive archive of web crawl data, and both provide very detailed documentation on what parts of the archive were included (==English exclusive==)
- [Mozilla Common Voice](https://commonvoice.mozilla.org/es): openly licensed dataset with text and audio in over 120 languages created by volunteers ([datasets in Spanish](https://commonvoice.mozilla.org/es/datasets))
- [Aya dataset](https://huggingface.co/datasets/CohereForAI/aya_dataset): is a multilingual instruction fine-tuning dataset curated by an open-science community via [Aya Annotation Platform](https://aya.for.ai/) from Cohere For AI. The dataset contains a total of 204k human-annotated prompt-completion pairs along with the demographics data of the annotators.
	- Spanish: `language_code=spa`
- [Data Provenance Explorer](https://www.dataprovenance.org/data-provenance-explorer/dataset-explorer): a catalog from a large-scale audit of AI datasets that filters for text fine-tuning datasets with permissive and open-source licenses. ([paper](https://arxiv.org/pdf/2310.16787))
-  [KL3M](https://huggingface.co/alea-institute): A project providing a replicable pipeline from data collection to model training that is certified under the [Fairly Trained L-Certication standards](https://www.fairlytrained.org/certifications) for training data, provided by [The Institute for the Advancement of Legal and Ethical AI (ALEA)](https://aleainstitute.ai/)
	- Only contains sources with explicit legal authority or for which consent has been obtained from rightsholders

### Data Processing

Careful attention to data processing and cleaning are crucial for ensuring datasets comply with licenses and are technically robust.

1. **Clearly and explicitly state the values and desired properties that shaped the way data was filtered or annotated**
	- High quality must be defined for every dataset
	- The filtering and processing goals will also vary depending on the intended use of the AI system

2. **Attempt to identify content that does not align with stated values**: decide what to do with 'harmful' content (or one that promotes harmful outcomes)
	- Can be filtered out or marked for future users 

3. **Consider potential unintended consequences of your filtering methods**: filtering introduces bias.

4. **Uphold existing standards**: follow established transparency best practices
	- [Data sheets](https://arxiv.org/abs/1803.09010)
	- [Data cards](https://arxiv.org/abs/2204.01075)

**Examples**:
- [FineWeb filtering pipeline](https://github.com/huggingface/datatrove/blob/main/examples/fineweb.py) 
- [Ethics & Society at Hugging Face](https://huggingface.co/spaces/society-ethics/about)
- [Pipeline for open-data toxicity filtering](https://arxiv.org/abs/2410.22587) by Pleias

### Data Governance/Release

Training data should be governed in ways that are inclusive, empowering, and mitigate harms.

1. **Tailor data governance mechanisms to your data subjects and use case**. Open access datasets can coexist with more access-restricted datasets, as they often involve different types of data.
	- However, all approaches need usable metadata and accessible documentation that communicates this to users.

2. **Work with affected communities**: Communities and organizations impacted by AI dataset development should be meaningfully engaged with as stakeholders.

3. **Post-release removal**: Create models of redress and removal from a dataset if an issue is spotted. Provide mechanisms for people to request removal of their data from the start and encourage downstream users to only use the updated version.
	- Current mechanisms focus on who is allowed to crawl a website rather than how its data is used

4. **Control the versioning**: Consider where you release datasets and how it influences the ability to control, maintain, and update them consistently across platforms.

**Examples**:
- Community-based data trusts or trusted data intermediaries
- BigCode opt-out process for The Stack
- Spawning
- [Croissant](https://github.com/mlcommons/croissant): a metadata documentation standard for ML ready datasets
- [Data Provenance Standards](https://dataandtrustalliance.org/work/data-provenance-standards): cross-industry metadata standards aiming to bring transparency to the origin and legality of datasets 


### Terms of Use

The need for clarity, responsibility, and alignment with global standards is very important. Terms of use should be **clear** and **understandable to non-legal professionals**, which reduces barriers to compliance.

**Standardization and modularization**: develop systems for creating modular terms of
use that are technically recognizable and easily adaptable.

**Accessibility**: design terms of use that are **clear** and **centered around user needs**.

**Do not impose restrictive terms on public domain data**: data that now belongs to the public is made maximally useful.

**Example**:
- [Responsible AI Licenses (RAIL)](https://www.licenses.ai/): restrict the use of the AI technology in order to prevent irresponsible and harmful application via [behavioral use licensing](https://dl.acm.org/doi/pdf/10.1145/3531146.3533143).
	- About 6000 datasets with RAIL licenses can be explored on [Hugging Face](https://huggingface.co/datasets?license=license:openrail&sort=trending)


# Estándar de licencias para el grupo SINAI

Nos vamos a basar en la información anterior para todos los recursos de datos generados por e grupo SINAI.

**Cumplimiento legal**

La construcción de datasets debe considerar diversas áreas del derecho, como la **propiedad intelectual**, la **regulación de privacidad de datos** y el **derecho contractual**.  
Debido a la ambigüedad de cómo se aplican las leyes existentes a las nuevas tecnologías, los actores de la IA deben asumir **cierto nivel de riesgo legal**, lo que genera decisiones distintas según su **tolerancia al riesgo**.

**Ética**

La ética aborda cuestiones más amplias como la **justicia**, la **igualdad**, la **distribución de recursos** y la **reparación de daños**.  
Un proyecto puede cumplir con la ley pero ser **éticamente cuestionable**, o ser éticamente sólido pero no cumplir **requisitos legales**.

**Licencia del dataset vs licencia de las partes**

Un dataset puede tener una **licencia propia** basada en su **estructura o compilación**, pero eso **no implica que el compilador tenga derecho a relicenciar** los datos individuales que lo componen.  
La licencia del dataset completo puede ser **más permisiva** que la de sus **componentes individuales**.

## Licencias usables

Todas aquellas licencias que **permitan el uso comercial** de los datos.

Estos son algunos ejemplos:
- Dominio Público (*public domain*)
- [Creative Commons Zero v1.0 Universal](https://choosealicense.com/licenses/cc0-1.0/) (CC0): Creative Commons CC0 Public Domain Dedication 
- [Creative Commons Attribution 4.0 International](https://choosealicense.com/licenses/cc-by-4.0/) (CC-BY-4.0): Creative Commons Attribution 4.0 International Public License

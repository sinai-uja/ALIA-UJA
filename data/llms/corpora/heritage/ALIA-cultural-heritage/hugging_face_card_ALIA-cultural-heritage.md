---
license: cc-by-sa-4.0
language:
- es
tags:
- cultural-heritage
- spanish
- culture
- humanities
- corpus
- nlp
size_categories:
- 100K<n<1M
task_categories:
- text-generation
- fill-mask
- question-answering
- text-classification
---

# Dataset Card for ALIA cultural-heritage Corpus

The **ALIA Cultural Heritage Corpus** is a strategic open data infrastructure designed to support research and innovation in digital humanities, cultural analytics, and Spanish-language NLP. It consolidates heterogeneous official and academic repositories into a single curated dataset, enabling broad and structured access to cultural heritage documentation from Spain. With **236,399 instances**, **946,467,028 tokens** and **102 source datasets**, it provides a robust foundation for developing domain-specialized language technologies in the cultural heritage field.

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

The **ALIA Cultural Heritage Corpus** is an open-access data resource that compiles and organizes a large-scale collection of cultural heritage documents in Spanish. It integrates heritage inventories, specialized journals, archival records, institutional publications, and descriptive resources about tangible and intangible heritage.

The corpus was designed to provide a homogeneous and reusable textual base for researchers in digital humanities, cultural institutions, archivists, historians, linguists, and AI practitioners. Its breadth supports both documentary exploration and computational workflows such as semantic retrieval, topic discovery, terminology extraction, and language model adaptation.

The processed version of the corpus currently includes **236,399 instances** and **946,467,028 tokens**, distributed across **102 source datasets**. This scale and heterogeneity make it an important resource for building and evaluating NLP systems focused on cultural heritage narratives, historical discourse, and institutional documentation in Spanish.

- **Curated by:** SINAI Research Group (Intelligent Systems for Information Access) - Universidad de Jaen, through CEATIC.
- **Funded by:** Ministerio para la Transformacion Digital y de la Funcion Publica - Funded by EU - NextGenerationEU, within the framework of the project Desarrollo de Modelos ALIA.
- **Language(s) (NLP):** es (Spanish)
- **License:** [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)

### Dataset Sources

- **Paper:** [N/A]

### Uses

The primary purpose of this corpus is to support training and evaluation of language technologies specialized in Spanish cultural heritage, including:

- Training large language models (LLMs) specialized in cultural heritage text.
- Heritage-oriented information retrieval systems.
- Question-answering systems over cultural and historical documentation.
- NLP research in digital humanities and institutional heritage archives.

## Dataset Structure

### Data Instances

Each instance in the corpus follows this structure:

```
{
  'id': '19467',
  'text': 'El "Castillo de Jaén" es, en realidad, un conjunto de tres castillos o fortalezas que conforman un gran recinto, que ocupa casi toda la alargada cima del Cerro de Santa Catalina, situado, en su parte sur-occidental, junto a la ciudad española de Jaén, comunidad autónoma de Andalucía...',
  'source_id': 'Wikipedia_Cultura_España',
  'metadata': '{}',
  'tokens': 1399
}
```

### Data Fields

- **id** (string): Document identifier extracted from the source (in many sources it corresponds to the document title or record identifier).
- **text** (string): Cleaned textual content of the document.
- **source_id** (string): Source dataset of origin.
- **metadata** (string): Additional serialized metadata associated with the document when available.
- **tokens** (int): Token count for the document after processing.

### Data Splits

The complete dataset contains the following source datasets with their statistics, sorted by number of tokens:

| Dataset | Num Tokens | Num Instances | Tokens Percentage | Instances Percentage | Source |
| :--- | ---: | ---: | ---: | ---: | :--- |
| Revistas_Culturales_Biblioteca_Virtual_Prensa_Historica | 262,539,044 | 3,079 | 27.7388% | 1.3025% | [Link](https://prensahistorica.mcu.es/arce/es/micrositios/inicio.do) |
| Wikipedia_Cultura_España | 109,529,621 | 92,044 | 11.5725% | 38.9359% | [Link](https://es.wikipedia.org/wiki/Categoría:Cultura_de_España) |
| Revistas_CSIC | 80,141,134 | 5,086 | 8.4674% | 2.1514% | [Link](https://revistas.csic.es/) |
| Revista_Hidalguia | 34,552,535 | 347 | 3.6507% | 0.1468% | [Link](https://www.revistahidalguia.es/) |
| Revistas_Instituto_Andaluz_Patrimonio_Historico | 26,463,170 | 4,427 | 2.7960% | 1.8727% | [Link](https://www.iaph.es/revistaph/index.php/revistaph) |
| Repositorio_Activos_Digitales_Andalucia | 25,072,951 | 1,470 | 2.6491% | 0.6218% | [Link](https://repositorio.iaph.es/simple-search) |
| Revista_Folklore | 20,532,402 | 408 | 2.1694% | 0.1726% | [Link](https://funjdiaz.net/folklore/index_listado.php?an=2025) |
| Tabula | 19,345,563 | 1,826 | 2.0440% | 0.7724% | [Link](https://www.juntadeandalucia.es/cultura/tabula/simple-search?query=) |
| Revista_Memoria_Ecclesiae | 16,257,174 | 81 | 1.7177% | 0.0343% | [Link](https://scrinia.org/publicaciones/memoria/) |
| Guia_Digital_Patrimonio_Andalucia_Patrimonio_Mueble | 13,558,785 | 78,148 | 1.4326% | 33.0577% | [Link](https://guiadigital.iaph.es/busqueda/mueble/*:*) |
| Revista_En_La_España_Medieval | 13,095,998 | 742 | 1.3837% | 0.3139% | [Link](https://revistas.ucm.es/index.php/elem) |
| Revista_Complutum | 12,871,996 | 708 | 1.3600% | 0.2995% | [Link](https://revistas.ucm.es/index.php/CMPL) |
| Revista_Signa | 12,727,638 | 1,230 | 1.3448% | 0.5203% | [Link](https://revistas.uned.es/index.php/signa) |
| Revista_Baetica | 12,691,369 | 1,030 | 1.3409% | 0.4357% | [Link](https://revistas.uma.es/index.php/baetica) |
| Guia_Digital_Patrimonio_Andalucia_Patrimonio_Inmueble | 12,156,307 | 18,287 | 1.2844% | 7.7357% | [Link](https://guiadigital.iaph.es/busqueda/inmueble/*:*) |
| Revista_Arte_Individuo_Y_Sociedad | 12,009,920 | 1,168 | 1.2689% | 0.4941% | [Link](https://revistas.ucm.es/index.php/ARIS) |
| Libros_Instituto_Geografico_Nacional | 11,046,546 | 82 | 1.1671% | 0.0347% | [Link](https://www.ign.es/web/ign/portal/publicaciones-boletines-y-libros-digitales/) |
| Revista_Hipogrifo | 10,902,761 | 1,082 | 1.1519% | 0.4577% | [Link](https://www.revistahipogrifo.com/index.php/hipogrifo) |
| Revista_Cuadernos_De_Ilustracion_Y_Romanticismo | 10,651,320 | 798 | 1.1254% | 0.3376% | [Link](https://revistas.uca.es/index.php/cir) |
| Revista_Cuadernos_De_Historia_Moderna | 10,003,156 | 876 | 1.0569% | 0.3706% | [Link](https://revistas.ucm.es/index.php/chmo) |
| Revista_Ilu | 8,293,223 | 773 | 0.8762% | 0.3270% | [Link](https://revistas.ucm.es/index.php/ILUR) |
| Revista_Lucentum | 8,063,553 | 389 | 0.8520% | 0.1646% | [Link](https://lucentum.ua.es/issue/archive) |
| Revista_Cuadernos_De_Historia_Contemporanea | 8,029,086 | 834 | 0.8483% | 0.3528% | [Link](https://revistas.ucm.es/index.php/chco) |
| Revistas_Cultura_Jaume_I | 7,792,816 | 631 | 0.8234% | 0.2669% | [Link](https://www.uji.es/serveis/scp/base/publ/proser/revistes/) |
| Publicaciones_Patrimonio_Subdireccion_Defensa | 7,569,501 | 77 | 0.7998% | 0.0326% | [Link](https://publicaciones.defensa.gob.es/) |
| Revista_Saguntum | 7,390,053 | 539 | 0.7808% | 0.2280% | [Link](https://turia.uv.es/index.php/saguntum) |
| Patrimonio_Anales_De_Historia_Del_Arte | 7,350,468 | 716 | 0.7766% | 0.3029% | [Link](https://revistas.ucm.es/index.php/ANHA/issue/archive) |
| Revista_Cuadernos_De_Prehistoria_Y_Arqueologia | 7,088,588 | 429 | 0.7490% | 0.1815% | [Link](https://revistaseug.ugr.es/index.php/cpag/issue/archive) |
| Revista_Investigaciones_De_Historia_Economica | 7,078,046 | 814 | 0.7478% | 0.3443% | [Link](https://recyt.fecyt.es/index.php/IHE/issue/archive) |
| Patrimonio_Arqueologia_Y_Territorio_Medieval | 6,861,392 | 373 | 0.7249% | 0.1578% | [Link](https://revistaselectronicas.ujaen.es/index.php/ATM) |
| BOE_Patrimonio | 6,703,747 | 8 | 0.7083% | 0.0034% | [Link](https://www.boe.es/biblioteca_juridica/index.php?tipo=C&modo=2) |
| Revista_El_Futuro_Del_Pasado | 6,247,979 | 14 | 0.6601% | 0.0059% | [Link](https://revistas.usal.es/uno/index.php/1989-9289/issue/archive) |
| Revista_Investigaciones_Historicas_Epoca_Moderna_Y_Contemporanea | 5,578,182 | 478 | 0.5894% | 0.2022% | [Link](https://revistas.uva.es/index.php/invehisto/es/index) |
| Patrimonio_Boletin_De_Literatura_Oral | 5,328,499 | 266 | 0.5630% | 0.1125% | [Link](https://revistaselectronicas.ujaen.es/index.php/blo) |
| Tesis_Palacios | 5,141,310 | 10 | 0.5432% | 0.0042% | [Link](https://www.patrimonionacional.es/coleccion/archivo-general-de-palacio/enlaces/archivos-y-otros-centros-de-investigacion#Tesis%20digitalizadas%20sobre%20fondos%20documentales%20del%20Archivo%20General%20de%20Palacio:) |
| Revista_Castilla | 5,020,526 | 578 | 0.5304% | 0.2445% | [Link](https://revistas.uva.es/index.php/castilla/es) |
| Revista_Studia_Aurea | 5,005,694 | 335 | 0.5289% | 0.1417% | [Link](https://studiaaurea.com/index) |
| Guia_Digital_Patrimonio_Andalucia_Patrimonio_Inmaterial | 4,902,654 | 1,845 | 0.5180% | 0.7805% | [Link](https://guiadigital.iaph.es/busqueda/inmaterial/*:*) |
| Revista_Estudios_Romanicos | 4,806,804 | 515 | 0.5079% | 0.2179% | [Link](https://revistas.um.es/estudiosromanicos) |
| Revista_Pasavento | 4,594,416 | 453 | 0.4854% | 0.1916% | [Link](https://erevistas.publicaciones.uah.es/ojs/index.php/pasavento/index) |
| Revista_Paleohispanica | 4,331,377 | 333 | 0.4576% | 0.1409% | [Link](https://ifc-ojs.es/index.php/palaeohispanica) |
| Revista_Acotaciones | 4,261,752 | 504 | 0.4503% | 0.2132% | [Link](https://www.resad.com/Acotaciones.new/index.php/ACT/) |
| Revista_Cauriensia | 4,079,146 | 367 | 0.4310% | 0.1552% | [Link](https://www.cauriensia.es/index.php/cauriensia) |
| Revista_Anuario_Lope_De_Vega | 3,967,112 | 409 | 0.4192% | 0.1730% | [Link](https://revistes.uab.cat/anuariolopedevega/index) |
| Revista_Panta_Rei | 3,606,096 | 281 | 0.3810% | 0.1189% | [Link](https://revistas.um.es/pantarei) |
| Revista_Janus | 3,486,313 | 218 | 0.3684% | 0.0922% | [Link](https://revistas.udc.es/index.php/janusdigital/about) |
| Revista_Rubrica_Contemporanea | 3,380,441 | 232 | 0.3572% | 0.0981% | [Link](https://revistes.uab.cat/rubrica/index) |
| Revista_Quiroga | 3,252,848 | 379 | 0.3437% | 0.1603% | [Link](https://revistaseug.ugr.es/index.php/quiroga/issue/archive) |
| Revista_Brumal | 3,191,857 | 181 | 0.3372% | 0.0766% | [Link](https://revistes.uab.cat/brumal/index) |
| Revista_Edad_Media | 2,908,244 | 319 | 0.3073% | 0.1349% | [Link](https://revistas.uva.es/index.php/edadmedia/es) |
| Revista_Saitabi | 2,760,118 | 189 | 0.2916% | 0.0799% | [Link](https://turia.uv.es/index.php/saitabi/index) |
| Revista_Anales_De_Arqueologia_Cordobesa | 2,741,395 | 170 | 0.2896% | 0.0719% | [Link](https://journals.uco.es/anarcor/issue/archive/) |
| Revista_Anuario_Calderoniano | 2,477,230 | 267 | 0.2617% | 0.1129% | [Link](https://recyt.fecyt.es/index.php/acal/index) |
| Publicaciones_Patrimonio_Cultural_Madrid | 2,464,665 | 43 | 0.2604% | 0.0182% | [Link](https://www.comunidad.madrid/publicamadrid?f%5B0%5D=consejeria%3A%22Consejer%C3%ADa%20de%20Cultura%2C%20Turismo%20y%20Deporte%22&f%5B1%5D=is_version_digital%3A%221%22&page=0) |
| Revista_Edad_De_Oro | 2,323,803 | 237 | 0.2455% | 0.1003% | [Link](https://revistas.uam.es/edadoro/issue/archive) |
| Revista_Aragon_En_La_Edad_Media | 2,282,252 | 120 | 0.2411% | 0.0508% | [Link](https://papiro.unizar.es/ojs/index.php/aem/index) |
| Revista_Santander_Estudios_Patrimonio | 2,151,563 | 134 | 0.2273% | 0.0567% | [Link](https://santanderestudiospatrimonio.unican.es/index.php/sanespat/index) |
| Revista_Molinum | 2,150,286 | 24 | 0.2272% | 0.0102% | [Link](https://www.molinologia.es/s/acem/page/molinum) |
| Revista_Electronica_Complutense_De_Investigacion_En_Educacion_Musical | 2,129,571 | 158 | 0.2250% | 0.0668% | [Link](https://revistas.ucm.es/index.php/RECI) |
| Revista_Escritura_Imagen | 2,007,655 | 218 | 0.2121% | 0.0922% | [Link](https://revistas.ucm.es/index.php/ESIM) |
| Patrimonio_Cuadernos_De_Arte_Prehistorico | 1,934,449 | 127 | 0.2044% | 0.0537% | [Link](https://www.revistacuadernosdearteprehistorico.com/index.php/cdap) |
| Revista_MuseosEs | 1,737,966 | 8 | 0.1836% | 0.0034% | [Link](https://www.cultura.gob.es/cultura/areas/museos/mc/mes/portada.html) |
| Revista_Potestas | 1,668,484 | 129 | 0.1763% | 0.0546% | [Link](https://www.e-revistes.uji.es/index.php/potestas) |
| Revista_Eikon | 1,639,156 | 136 | 0.1732% | 0.0575% | [Link](https://revistas.ucm.es/index.php/EIKO/index) |
| Revista_UcoArte | 1,638,460 | 140 | 0.1731% | 0.0592% | [Link](https://journals.uco.es/ucoarte/issue/archive) |
| Revista_De_Medio_Aevo | 1,506,558 | 115 | 0.1592% | 0.0486% | [Link](https://revistas.ucm.es/index.php/DMAE) |
| Revista_Imago | 1,437,216 | 175 | 0.1519% | 0.0740% | [Link](https://turia.uv.es/index.php/IMAGO) |
| Revista_Pygmalion | 1,385,374 | 230 | 0.1464% | 0.0973% | [Link](https://revistas.ucm.es/index.php/PYGM) |
| Revista_Historia_Social_Y_De_La_Educacion | 1,381,186 | 113 | 0.1459% | 0.0478% | [Link](https://hipatiapress.com/hpjournals/index.php/hse/issue/archive) |
| Revista_Amaltea | 1,260,417 | 126 | 0.1332% | 0.0533% | [Link](https://revistas.ucm.es/index.php/ANHA/issue/archive) |
| Patrimonio_Castilla_Y_Leon | 1,189,827 | 1,049 | 0.1257% | 0.4437% | [Link](https://patrimoniocultural.jcyl.es/web/es/patrimonio-bienes-culturales/catalogo-bienes-culturales.html) |
| Revista_ReVisiones | 1,172,930 | 150 | 0.1239% | 0.0635% | [Link](https://revistas.ucm.es/index.php/REVI) |
| Actas_De_Arquitectura_Religiosa_Contemporanea | 1,147,371 | 145 | 0.1212% | 0.0613% | [Link](https://revistas.udc.es/index.php/aarc/index) |
| Revista_Estudis | 1,127,559 | 105 | 0.1191% | 0.0444% | [Link](https://turia.uv.es/index.php/estudis) |
| Revista_ASRI | 1,118,663 | 102 | 0.1182% | 0.0431% | [Link](https://revistaasri.com/index) |
| Revista_El_Pajaro_De_Benin | 929,162 | 69 | 0.0982% | 0.0292% | [Link](https://revistascientificas.us.es/index.php/pajaro_benin) |
| Revista_Ad_Limina | 878,163 | 7 | 0.0928% | 0.0030% | [Link](https://www.caminodesantiago.gal/es/conocimiento-e-investigacion/ad-limina) |
| Revista_Andelma | 858,942 | 168 | 0.0908% | 0.0711% | [Link](https://www.revistaandelma.es/index.php/andelma/) |
| Revista_AusArt | 841,225 | 107 | 0.0889% | 0.0453% | [Link](https://ojs.ehu.eus/index.php/ausart/) |
| Revista_Otarq | 797,772 | 4 | 0.0843% | 0.0017% | [Link](http://revistas.jasarqueologia.es/index.php/otarq/issue/archive) |
| Mineralogia_Topologia_Iberica_Lamparas | 712,411 | 6 | 0.0753% | 0.0025% | [Link](https://www.mtiblog.com/) |
| Mineralogia_Topologia_Iberica_Acopios | 664,062 | 13 | 0.0702% | 0.0055% | [Link](https://mti-acopios.blogspot.com/) |
| Mineralogia_Topologia_Iberica_Hastial | 654,350 | 10 | 0.0691% | 0.0042% | [Link](https://mti-hastial.blogspot.com/) |
| Revista_Sarmental | 538,358 | 42 | 0.0569% | 0.0178% | [Link](https://revistas.ubu.es/sarmental/issue/archive) |
| Ministerio_De_Cultura_Patrimonio_Filmoteca_Española | 506,171 | 3,177 | 0.0535% | 1.3439% | [Link](https://catalogos.cultura.gob.es/RAFI/cgi-rafi/abnetopac/) |
| Bienes_Culturales_Castilla_LaMancha | 440,081 | 628 | 0.0465% | 0.2657% | [Link](https://cultura.castillalamancha.es/patrimonio/catalogo-patrimonio-cultural) |
| Revista_Riparia | 406,607 | 44 | 0.0430% | 0.0186% | [Link](https://revistas.uca.es/index.php/sig/issue/archive) |
| Mineralogia_Topologia_Iberica_Amalgama | 318,606 | 45 | 0.0337% | 0.0190% | [Link](https://mti-amalgama.blogspot.com/) |
| Patrimonio_Cultural_Inmaterial_Comunidades_Autonomas | 259,436 | 168 | 0.0274% | 0.0711% | [Link](https://www.portalinmaterial.cultura.gob.es/pci-ccaa.html) |
| Revista_Buñueliana | 241,062 | 27 | 0.0255% | 0.0114% | [Link](https://papiro.unizar.es/ojs/index.php/bunuel/es/index) |
| Revista_Crater | 210,400 | 20 | 0.0222% | 0.0085% | [Link](https://revistascientificas.us.es/index.php/crater/index) |
| Patrimonio_Cataluña | 140,534 | 331 | 0.0148% | 0.1400% | [Link](https://patrimoni.gencat.cat/es/descubre/busca) |
| Obras_Singulares_Museos_Andalucia | 140,268 | 368 | 0.0148% | 0.1557% | [Link](https://www.juntadeandalucia.es/organismos/culturaydeporte/areas/cultura/museos-arte/fondos-museisticos.html) |
| Guia_Digital_Patrimonio_Andalucia_Paisaje_Cultural | 109,668 | 116 | 0.0116% | 0.0491% | [Link](https://guiadigital.iaph.es/busqueda/paisaje/*:*) |
| Ministerio_De_Cultura_Patrimonio_Audiovisual_Cine_Español | 25,115 | 167 | 0.0027% | 0.0706% | [Link](https://sede.mcu.gob.es/CatalogoICAA) |
| UNESCO | 17,011 | 70 | 0.0018% | 0.0296% | [Link](https://www.unesco.org/es) |
| Somos_Patrimonio | 9,318 | 48 | 0.0010% | 0.0203% | [Link](http://www.somospatrimonio.es/patrimonio/) |
| Adquisiciones_Archivo_Historico | 9,236 | 25 | 0.0010% | 0.0106% | [Link](https://www.cultura.gob.es/cultura/archivos/informacion-general/adquisiciones-donaciones/portada-adquisiciones-donaciones.html) |
| Fiestas_Patrimoniales | 8,755 | 19 | 0.0009% | 0.0080% | [Link](https://www.cultura.gob.es/cultura/areas/patrimonio/mc/patrimonio-inmaterial/elementos-declarados/lista.html) |
| Patrimonio_Cultural_Inmaterial_España | 6,519 | 13 | 0.0007% | 0.0055% | [Link](https://www.portalinmaterial.cultura.gob.es/pci-nacional.html) |
| Patrimonio_Cultural_Inmaterial_UNESCO | 652 | 1 | 0.0001% | 0.0004% | [Link](https://www.portalinmaterial.cultura.gob.es/pci-unesco.html) |
| **TOTAL** | **946,467,028** | **236,399** | **100.0000%** | **100.0000%**  - | - |

### Example Usage

To load the dataset:

```python
from datasets import load_dataset

# Load the complete dataset
data = load_dataset("SINAI/ALIA-cultural-heritage", trust_remote_code=True)

# Load with streaming
stream_data = load_dataset("SINAI/ALIA-cultural-heritage", trust_remote_code=True, streaming=True)
```

Example of data access:

```python
example = data["train"][0]
print(f"ID: {example['id']}")
print(f"Source: {example['source_id']}")
print(f"Tokens: {example['tokens']}")
print(f"Text: {example['text'][:200]}...")
```

## Dataset Creation

### Curation Rationale

This corpus was created to address the need for large, structured, and legally reusable linguistic resources in the cultural heritage domain in Spanish. It supports the ALIA initiative by providing a curated documentary foundation for training AI models and conducting computational analysis of cultural assets, historical publications, and institutional heritage records.

### Source Data

The corpus integrates documentation from multiple publicly accessible repositories, including:

#### Heritage Inventories and Catalogs
- Regional and national heritage inventories (e.g., Castilla y León, Castilla-La Mancha, Cataluña).
- Digital guides of Andalusian property heritage (movable, immovable, intangible heritage, and cultural landscapes).
- Intangible cultural heritage portals (national, autonomous communities, and UNESCO-oriented records).

#### Institutional and Public Heritage Repositories
- Instituto Andaluz del Patrimonio Histórico (IAPH) repositories and publications.
- Public digital publications on heritage and culture (including Ministry of Defense heritage publications).
- Specialized resources such as archival works and acquisitions.

#### Academic Journals and Humanities Publications
- Broad collections of peer-reviewed journals and historical/cultural periodicals (e.g., Revistas CSIC, Biblioteca Virtual de Prensa Histórica cultural magazines, archaeology and history journals).
- Thematic journals covering art history, archaeology, medieval studies, folklore, philology, cultural studies, and conservation.

#### Audiovisual and Documentary Heritage
- Spanish audiovisual heritage records (ICAA catalog resources and Filmoteca Española-related material).
- Documentary and bibliographic heritage references from institutional collections.

#### Open Knowledge and Reference Resources
- Cultural heritage content from Spanish Wikipedia and complementary reference repositories.
- UNESCO-related and dissemination-oriented heritage resources.

All data come from official, institutional, academic, or publicly accessible sources.

### Data Collection and Processing

The current corpus version corresponds to a processed and enriched parquet release. The pipeline includes:

**Step 1: Source consolidation and normalization**
- Integration of heterogeneous source formats into a unified schema.
- Normalization of identifiers and source tags.

**Step 2: Language and quality filtering**
- Selection and preservation of Spanish textual content.
- Basic quality checks to remove malformed records.

**Step 3: Deduplication and cleaning**
- Reduction of repeated or highly similar content.
- Text cleaning and standardization for downstream NLP usage.

**Step 4: Quality filters and final cleaning**
- Application of multiple specialized filters
- Correction of encoding errors
- Removal of sensitive or identifiable information

Token counting was performed using [tiktoken](https://github.com/openai/tiktoken).

Final corpus size in the latest parquet release:
- **Tokens:** 946,467,028
- **Instances:** 236,399
- **Sources:** 102

### Annotations

The dataset does not provide task-specific manual annotations. It contains structural metadata fields generated during collection and preprocessing.

### Personal and Sensitive Information

The corpus is assembled from public sources and has undergone processing steps oriented to large-scale textual reuse. Some documents may still contain personal names or role references appearing in public institutional or academic official contexts. Users are advised to apply additional controls depending on the specific use of the corpus.

### Citation

SINAI Research Group - Universidad de Jaen. ALIA Cultural Heritage Corpus, version 1.0. 2026. https://huggingface.co/datasets/SINAI/ALIA-cultural-heritage

```bibtex
@misc{alia-cultural-heritage,
  title={ALIA Cultural Heritage},
  author={SINAI Research Group},
  year={2026},
  publisher={HuggingFace},
  howpublished={\url{https://huggingface.co/datasets/SINAI/ALIA-cultural-heritage}}
}
```

## Considerations for Using the Data

### Social Impact of Dataset

This corpus contributes to democratizing access to cultural heritage documentation in Spanish. It can support AI systems for heritage dissemination, documentation support, educational access, and research acceleration in humanities and social sciences.

### Discussion of Biases

Potential biases include:

- **Institutional register bias:** The corpus is dominated by formal and academic language, not colloquial speech.
- **Source concentration bias:** A reduced number of high-volume sources contributes a substantial share of total tokens.
- **Regional representation bias:** Coverage depends on digitization and publication practices across institutions and territories.
- **Historical and editorial bias:** Heritage narratives may reflect dominant historiographic, institutional, or curatorial perspectives.

### Other Known Limitations

- Source OCR and digitization quality may vary across collections.
- Temporal coverage is uneven across source datasets.
- Some records include highly structured or catalog-like text that may differ from narrative prose.
- Token and source statistics are specific to the current enriched parquet release and may change in future updates.

---

**Contact:** [ALIA Project](https://www.alia.gob.es/) - [SINAI Research Group](https://sinai.ujaen.es) - [Universidad de Jaen](https://www.ujaen.es/)

**Corpus Legal y Administrativo v.2**

El **Corpus Legal y Administrativo v.1** constituye una infraestructura de datos estratégica para apoyar la investigación en ciencias sociales, jurídicas y computacionales, garantizando acceso sistemático a múltiples repositorios oficiales en una única plataforma consolidada. Su valor radica en combinar exhaustividad, heterogeneidad de fuentes y curación técnica, lo que lo convierte en un recurso de referencia en el ámbito legal y administrativo español.

*Sara Dueñas Romero | sduenas@ujaen.es | Proyecto Vandelvira*

**Tabla de contenido**
- [Descripción General](#descripción-general)
  - [Datasets que conforman el corpus](#datasets-que-conforman-el-corpus)
- [Estadísticas de los datos](#estadísticas-de-los-datos)

---

# Descripción General

El **Corpus Legal y Administrativo v.12** es un recurso de datos de libre acceso que reúne y organiza un amplio conjunto de documentos oficiales del ámbito jurídico y administrativo español. Su propósito es proporcionar una base documental homogénea, estructurada y accesible para investigadores, académicos, profesionales del derecho y de la administración pública interesados en el análisis y explotación de textos normativos, legislativos y administrativos en lengua española.

Este corpus ha sido diseñado con un enfoque integrador que abarca tanto boletines oficiales estatales, autonómicos y provinciales, como el Boletín Oficial del Estado (BOE), boletines de comunidades autónomas (BOJA, BOCYL, BORM, entre otros) y boletines provinciales, como registros especializados (BORME, Biblioteca Jurídica, Código Técnico de la Edificación, entre otros). Adicionalmente, incluye documentos ministeriales y publicaciones técnicas en materias clave como energía, medio ambiente, cambio climático, defensa y seguridad nacional, así como licitaciones y contratos públicos. Esta diversidad de fuentes permite cubrir de forma amplia el ecosistema documental que regula la actividad institucional, económica y social en España.

El alcance del [corpus](data/llms/corpora/corpus_legal_v1.json) abarca más de **1,27 millones de instancias y más de 5.800 millones de *tokens***, lo que lo convierte en una fuente sin precedentes para el estudio académico de la normativa española, el análisis legislativo comparado, el desarrollo de herramientas de procesamiento del lenguaje natural (PLN) aplicadas al lenguaje jurídico-administrativo y la investigación en apertura de datos institucionales. Su carácter abierto y procesado facilita tanto la exploración manual por parte de juristas y profesionales de la documentación, como la utilización avanzada en proyectos de minería de textos, modelado semántico, recuperación de información y construcción de sistemas de inteligencia artificial especializados en derecho y administración pública.

## Datasets que conforman el corpus

- **Agen_Urb_Esp**
    Estos documentos pretender reflejar la puesta en común y difusión del conocimiento, experiencias y buenas prácticas que tienen incidencia en los pueblos y ciudades a través de la Agenda Urbana Española, con ejemplos que por sus características y especificaciones, pueden contribuir al cumplimiento de alguno de los objetivos del marco estratégico a la vez que estimulan la creatividad y proporcionan soluciones viables para el desarrollo urbano sostenible.
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/Agen_Urb_Esp/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/Agen_Urb_Esp/metadata.yaml)
- **BODEFENSA**
    El recurso es una colección de boletines oficiales (BOD) publicados por el Ministerio de Defensa de España, accesibles en línea. Contiene documentos en formato PDF con resoluciones, normativas, convenios y manuales técnicos.
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/BODEFENSA/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/BODEFENSA/metadata.yaml)
- **Biblioteca_Juridica**
    Compilación oficial del BOE de códigos electrónicos que reúnen legislación española vigente organizada por materias. Se han recopilado tanto códigos como códigos universitarios.
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/Biblioteca_Juridica/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/Biblioteca_Juridica/metadata.yaml)
- **Boletines_Oficiales/BOJA**
    Set of bulletins from the autonomous community of Andalucia
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/Boletines_Oficiales/BOJA/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/Boletines_Oficiales/BOJA/metadata.yaml)
- **Boletines_Oficiales/BORM**
    Set of bulletins from the autonomous community of Murcia
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/Boletines_Oficiales/BORM/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/Boletines_Oficiales/BORM/metadata.yaml)
- **Boletines_Oficiales/BOC**
    It comes from the official bulletin of Canarias
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/Boletines_Oficiales/BOC/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/Boletines_Oficiales/BOC/metadata.yaml)
- **Boletines_Oficiales/BOE**
    Set of bulletins from Spain
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/Boletines_Oficiales/BOE/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/Boletines_Oficiales/BOE/metadata.yaml)
- **Boletines_Oficiales/BOCYL**
    Set of bulletins from the autonomous community of Castilla y Leon
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/Boletines_Oficiales/BOCYL/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/Boletines_Oficiales/BOCYL/metadata.yaml)
- **Boletines_Oficiales/BOCCE**
    These data come from official sources of the autonomous city of Ceuta
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/Boletines_Oficiales/BOCCE/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/Boletines_Oficiales/BOCCE/metadata.yaml)
- **Boletines_Oficiales/BOCANT**
    Set of bulletins from the autonomous community of Cantabria
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/Boletines_Oficiales/BOCANT/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/Boletines_Oficiales/BOCANT/metadata.yaml)
- **Codigo_Tecnico_Edificacion**
    El Código Técnico de la Edificación (CTE) en España ofrece acceso directo a los Documentos Básicos (DB) como estructural, incendio, accesibilidad, eficiencia energética, ruido, salubridad y seguridad, además del Real Decreto y Parte I, junto a guías de apoyo, catálogo de elementos constructivos, programas de cálculo acústico y recursos complementarios, conformando un marco completo para la verificación normativa y técnica de edificaciones, incluyendo programas, manuales interpretativos y fichas.
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/Codigo_Tecnico_Edificacion/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/Codigo_Tecnico_Edificacion/metadata.yaml)
- **Departamento_Seguridad_Nacional**
    El dataset contiene publicaciones oficiales del Departamento de Seguridad Nacional (DSN) de Españaestá dividio en varias categorías como: Estrategia de Seguridad Nacional, Estrategias Sectoriales, Informes Anuales y otros temas estratégicos relevantes.
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/Departamento_Seguridad_Nacional/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/Departamento_Seguridad_Nacional/metadata.yaml)
- **Licitaciones**
    Contracts and published tenders
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/Licitaciones_2025/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/Licitaciones_2025/metadata.yaml)
- **Ministerio_Vivienda_Agenda_Urbana**
    La página de Estudios y Publicaciones del Ministerio de Vivienda y Agenda Urbana de España ofrece una recopilación de documentos técnicos y estratégicos relacionados con la vivienda, el urbanismo y la sostenibilidad. Entre los materiales disponibles se encuentran informes del Observatorio de Vivienda, catálogos de buenas prácticas en arquitectura y urbanismo, guías de accesibilidad en espacios públicos urbanizados, y estudios como el "Libro Blanco de la Sostenibilidad en el Planeamiento Urbanístico Español". Estos documentos proporcionan análisis detallados, recomendaciones y marcos normativos que respaldan las políticas públicas en materia de vivienda y desarrollo urbano sostenible.
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/Ministerio_Vivienda_Agenda_Urbana/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/Ministerio_Vivienda_Agenda_Urbana/metadata.yaml)
- **NORMA**
    Normativa: The set of laws and rules in force in the field of economics and finance.  Doctrina: Interpretation and application of these rules by bodies and experts.
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/NORMA/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/NORMA/metadata.yaml)
- **Registro_Mercantil_Borme**
    Conjunto de datos extraído del Boletín Oficial del Registro Mercantil (BORME) de España. Contiene anuncios oficiales sobre actos jurídicos y mercantiles de sociedades, como constituciones, nombramientos, ceses, fusiones, y disoluciones, publicados diariamente por el BOE.
    - Fichero de información: [metadata.json](data/llms/data/processed/legal/Registro_Mercantil_Borme/metadata.json)
    - Fichero de metadatos: [metadata.yaml](data/llms/data/processed/legal/Registro_Mercantil_Borme/metadata.yaml)


# Estadísticas de los datos

| Fuente | Num Tokens | Num Instancias | Tokens % | Instancias % |
|---------|------------|----------------|----------|--------------|
| Boletines_Oficiales/BOE | 8.200.717.524 | 1.762.024 | 39,91% | 45,24% |
| Boletines_Oficiales/BOJA | 3.412.725.472 | 654.488 | 16,61% | 16,80% |
| Boletines_Oficiales/BOCYL | 2.359.477.219 | 481.830 | 11,48% | 12,37% |
| Boletines_Oficiales/BORM | 1.836.825.316 | 419.702 | 8,94% | 10,78% |
| Boletines_Oficiales/BOCANT | 1.025.561.068 | 314.398 | 4,99% | 8,07% |
| Licitaciones_2025-07-03 | 994.457.488 | 12.646 | 4,84% | 0,33% |
| Boletines_Oficiales/BOC | 785.512.717 | 147.709 | 3,82% | 3,79% |
| Registro_Mercantil_Borme | 465.687.027 | 46.021 | 2,27% | 1,18% |
| Biblioteca_Juridica | 385.050.195 | 1.117 | 1,87% | 0,03% |
| BODEFENSA | 331.315.518 | 3.707 | 1,61% | 0,10% |
| Ministerio_Economia_BOICAC | 307.360.049 | 1.988 | 1,50% | 0,05% |
| NORMA | 270.311.480 | 44.715 | 1,32% | 1,15% |
| Boletines_Oficiales/BOCCE | 139.088.945 | 3.980 | 0,68% | 0,10% |
| Codigo_Tecnico_Edificacion | 15.903.128 | 276 | 0,08% | 0,01% |
| Ministerio_Vivienda_Agenda_Urbana | 13.201.281 | 267 | 0,06% | 0,01% |
| Departamento_Seguridad_Nacional | 4.830.335 | 115 | 0,02% | 0,00% |
| Agen_Urb_Esp | 2.357.958 | 51 | 0,01% | 0,00% |
| Total                           | 20.550.382.720        | 3.895.034         |    |        |

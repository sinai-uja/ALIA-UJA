**Corpus ALIA Legal y Administrativo**

El **Corpus ALIA Legal y Administrativo** constituye una infraestructura de datos estratégica para apoyar la investigación en ciencias sociales, jurídicas y computacionales, garantizando acceso sistemático a múltiples repositorios oficiales en una única plataforma consolidada. Su valor radica en combinar exhaustividad, heterogeneidad de fuentes y curación técnica, lo que lo convierte en un recurso de referencia en el ámbito legal y administrativo español.

*Grupo de investigación de Sistemas Inteligentes de Acceso a la Información | sinai@ujaen.es | Proyecto ALIA*

**Tabla de contenido**
- [Descripción General](#descripción-general)
  - [Datasets que conforman el corpus](#datasets-que-conforman-el-corpus)
- [Estadísticas de los datos](#estadísticas-de-los-datos)

---

# Descripción General

El **Corpus ALIA Legal y Administrativo** es un recurso de datos de libre acceso que reúne y organiza un amplio conjunto de documentos oficiales del ámbito jurídico y administrativo español. Su propósito es proporcionar una base documental homogénea, estructurada y accesible para investigadores, académicos, profesionales del derecho y de la administración pública interesados en el análisis y explotación de textos normativos, legislativos y administrativos en lengua española.

Este corpus ha sido diseñado con un enfoque integrador que abarca tanto boletines oficiales estatales, autonómicos y provinciales, como el Boletín Oficial del Estado (BOE), boletines de comunidades autónomas (BOJA, BOCYL, BORM, entre otros) y boletines provinciales, como registros especializados (BORME, Biblioteca Jurídica, Código Técnico de la Edificación, entre otros). Adicionalmente, incluye documentos ministeriales y publicaciones técnicas en materias clave como energía, medio ambiente, cambio climático, defensa y seguridad nacional, así como licitaciones y contratos públicos; además de actas parlamentarias del Parlamento Andaluz. Esta diversidad de fuentes permite cubrir de forma amplia el ecosistema documental que regula la actividad institucional, económica y social en España.

El alcance del corpus abarca más de **7 millones de instancias y más de 5 mil millones de *tokens***, lo que lo convierte en una fuente sin precedentes para el estudio académico de la normativa española, el análisis legislativo comparado, el desarrollo de herramientas de procesamiento del lenguaje natural (PLN) aplicadas al lenguaje jurídico-administrativo y la investigación en apertura de datos institucionales. Su carácter abierto y procesado facilita tanto la exploración manual por parte de juristas y profesionales de la documentación, como la utilización avanzada en proyectos de minería de textos, modelado semántico, recuperación de información y construcción de sistemas de inteligencia artificial especializados en derecho y administración pública.

Este corpus está basado en una versión anterior que abarcaba casi 20 mil millones de tokens. Se procesaron los datos con una metodología de limpieza más compleja basada en datatrove.

## Sistema de limpieza con datatrove

Este sistema automatiza la limpieza y preparación de grandes volúmenes de texto en español, eliminando contenido duplicado y de baja calidad. Es una herramienta diseñada para investigadores, científicos de datos y equipos que necesitan preparar corpus textuales para entrenar modelos de lenguaje o realizar análisis lingüísticos a gran escala

- **Paso 1: Carga de configuración y rutas**
  - Carga un archivo de configuración YAML con parámetros (umbral de idioma, filtros, etc.).
  - Definición de rutas de trabajo
  - Preparación del entorno de procesamiento

- **Paso 2: Filtrado por idioma**
  - Análisis automático del idioma de cada documento
  - Selección de textos en español según umbral de confianza

- **Paso 3: Deduplicado con MinHash**
  - Detección avanzada de contenido repetido o altamente similar
  - Utiliza algoritmos de comparación escalables para grandes volúmenes

- **Paso 4: Filtros de calidad y limpieza final**
  - Aplicación de múltiples filtros especializados
  - Corrección de errores de codificación
  - Eliminación de información sensible o identificable

## Datasets que conforman el corpus

La información estadística de tokens e instancias que los datasets que conforman el corpus corresponden a los datos previos a la limpieza descrita anteriormente, es decir, reflejan las características de los textos originales.

- **Agen_Urb_Esp**
    Estos documentos pretender reflejar la puesta en común y difusión del conocimiento, experiencias y buenas prácticas que tienen incidencia en los pueblos y ciudades a través de la Agenda Urbana Española, con ejemplos que por sus características y especificaciones, pueden contribuir al cumplimiento de alguno de los objetivos del marco estratégico a la vez que estimulan la creatividad y proporcionan soluciones viables para el desarrollo urbano sostenible.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Agen_Urb_Esp/metadata.yaml)
- **BODEFENSA**
    El recurso es una colección de boletines oficiales (BOD) publicados por el Ministerio de Defensa de España, accesibles en línea. Contiene documentos en formato PDF con resoluciones, normativas, convenios y manuales técnicos.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/BODEFENSA/metadata.yaml)
- **Biblioteca_Juridica**
    Compilación oficial del BOE de códigos electrónicos que reúnen legislación española vigente organizada por materias. Se han recopilado tanto códigos como códigos universitarios.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Biblioteca_Juridica/metadata.yaml)
- **Boletines_Oficiales/BOJA**
    Set of bulletins from the autonomous community of Andalucia
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Boletines_Oficiales/BOJA/metadata.yaml)
- **Boletines_Oficiales/BOP_Granada**
    Set of bulletins from the province of Granada
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Boletines_Oficiales/BOP_Granada/metadata.yaml)
- **Boletines_Oficiales/BORM**
    Set of bulletins from the autonomous community of Murcia
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Boletines_Oficiales/BORM/metadata.yaml)
- **Boletines_Oficiales/BOP_Sevilla**
    Set of bulletins from the province of Sevilla
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Boletines_Oficiales/BOP_Sevilla/metadata.yaml)
- **Boletines_Oficiales/BOP_Cordoba**
    Set of bulletins from the province of Cordoba
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Boletines_Oficiales/BOP_Cordoba/metadata.yaml)
- **Boletines_Oficiales/BOC**
    It comes from the official bulletin of Canarias
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Boletines_Oficiales/BOC/metadata.yaml)
- **Boletines_Oficiales/BOE**
    Set of bulletins from Spain
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Boletines_Oficiales/BOE/metadata.yaml)
- **Boletines_Oficiales/BOCYL**
    Set of bulletins from the autonomous community of Castilla y Leon
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Boletines_Oficiales/BOCYL/metadata.yaml)
- **Boletines_Oficiales/BOCCE**
    These data come from official sources of the autonomous city of Ceuta
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Boletines_Oficiales/BOCCE/metadata.yaml)
- **Boletines_Oficiales/BOCANT**
    Set of bulletins from the autonomous community of Cantabria
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Boletines_Oficiales/BOCANT/metadata.yaml)
- **Boletines_Oficiales/BOP_Jaen**
    Set of bulletins from the province of Jaen
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Boletines_Oficiales/BOP_Jaen/metadata.yaml)
- **Codigo_Tecnico_Edificacion**
    El Código Técnico de la Edificación (CTE) en España ofrece acceso directo a los Documentos Básicos (DB) como estructural, incendio, accesibilidad, eficiencia energética, ruido, salubridad y seguridad, además del Real Decreto y Parte I, junto a guías de apoyo, catálogo de elementos constructivos, programas de cálculo acústico y recursos complementarios, conformando un marco completo para la verificación normativa y técnica de edificaciones, incluyendo programas, manuales interpretativos y fichas.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Codigo_Tecnico_Edificacion/metadata.yaml)
- **Departamento_Seguridad_Nacional**
    El dataset contiene publicaciones oficiales del Departamento de Seguridad Nacional (DSN) de Españaestá dividio en varias categorías como: Estrategia de Seguridad Nacional, Estrategias Sectoriales, Informes Anuales y otros temas estratégicos relevantes.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Departamento_Seguridad_Nacional/metadata.yaml)
- **Licitaciones**
    Contracts and published tenders
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Licitaciones/metadata.yaml)
- **Ministerio_Transicion_Ecologica/Ministerio**
    La sección "Ministerio" del sitio web del Ministerio para la Transición Ecológica y el Reto Demográfico (MITECO) ofrece una visión integral de la estructura, funciones y actividades del ministerio. Incluye información detallada sobre su organización, destacando las distintas secretarías y comisionados, como la Secretaría de Estado de Energía y la Secretaría de Estado de Medio Ambiente. También se presentan los organismos públicos adscritos, como la Agencia Estatal de Meteorología (AEMET) y las Confederaciones Hidrográficas. La sección proporciona acceso a documentos estratégicos y planes, como el Plan Nacional Integrado de Energía y Clima, la Estrategia de Transición Justa y el Plan de Contratación Pública Ecológica. Además, se detallan iniciativas específicas relacionadas con el Mar Menor y Doñana, así como información sobre empleo público, formación, becas y prácticas. Asimismo, se ofrecen recursos para la ciudadanía, incluyendo unidades de atención, participación pública y servicios por área de actividad. En conjunto, esta sección actúa como un centro de documentación y consulta para comprender las políticas y acciones del MITECO en áreas clave como energía, medio ambiente y reto demográfico.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Ministerio_Transicion_Ecologica/Ministerio/metadata.yaml)
- **Ministerio_Transicion_Ecologica/Reto_Demografico**
    La sección Reto Demográfico del MITECO incluye una descripción básica de qué es el Reto Demográfico; el desarrollo de la Política de Estado y el rol de la Secretaría General para su coordinación; el "Plan de Medidas ante el Reto Demográfico" con sus 130 acciones; iniciativas de cooperación transfronteriza; herramientas de análisis y cartografía; selección de documentos de interés; y el "Nuevo Marco Estratégico".
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Ministerio_Transicion_Ecologica/Reto_Demografico/metadata.yaml)
- **Ministerio_Transicion_Ecologica/Cambio_Climatico**
    La sección “Cambio climático” de la página del MITECO explica los impactos, la vulnerabilidad y la adaptación del cambio climático y evaluaciones por sector. Se profundiza en su mitigación con herramientas como la huella de carbono incluyendo calculadoras, proyectos y planes específicos. Se presentan iniciativas de educación, formación y sensibilización pública, así como la participación ciudadana y la cooperación internacional. Asimismo, se incluyen apartados dedicados a registro, legislación, fechas relevantes, participación pública, congresos, preguntas frecuentes, publicaciones y enlaces de interés, conformando así una visión global y estructurada de las acciones y documentación disponible sobre cambio climático en España.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Ministerio_Transicion_Ecologica/Cambio_Climatico/metadata.yaml)
- **Ministerio_Transicion_Ecologica/Calidad_Evaluacion_Ambiental**
    La sección Calidad y Evaluación Ambiental del MITECO ofrece glosarios, normativas, guías y expedientes de Evaluación ambiental, legislaciones, registros, memorias e informes de Prevención y gestión de residuos, Suelos contaminados, estrategias, prácticas y boletines de Economía circular, datos, planes y estudios de la Calidad del aire y Emisiones a la atmósfera, Medio ambiente industrial y Contaminación acústica, entre otros.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Ministerio_Transicion_Ecologica/Calidad_Evaluacion_Ambiental/metadata.yaml)
- **Ministerio_Transicion_Ecologica/Sala_Prensa**
    La sección Sala de Prensa del MITECO se incluyen tanto informaciones sobre iniciativas estratégicas —como la declaración de proyectos emblemáticos, la inauguración de infraestructuras meteorológicas o la convocatoria de ayudas económicas— como datos actualizados sobre recursos hídricos o actuaciones en biodiversidad.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Ministerio_Transicion_Ecologica/Sala_Prensa/metadata.yaml)
- **Ministerio_Transicion_Ecologica/Energia**
    La sección Energía del MITECO reúne una amplia variedad de documentos oficiales que incluye normativas sobre eficiencia energética, reglamentos y trámites para comercializadoras eléctricas, normativas sobre certificados de ahorro energético, requisitos y legislación ambiental para proyectos de hidrógeno, compilaciones actualizadas de legislación del gas natural y GLP,  normativas sobre biocarburantes y sostenibilidad, y recursos sobre minería y explosivos.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Ministerio_Transicion_Ecologica/Energia/metadata.yaml)
- **Ministerio_Transicion_Ecologica/Organismo_Autonomo_Parques_Nacionales**
    La página del Organismo Autónomo Parques Nacionales (OAPN) del MITECO incluye secciones sobre la Red de Parques Nacionales, la Red Española de Reservas de la Biosfera, espacios naturales, la relación de parques nacionales con su cartografía y central de reservas, publicaciones de conservación y educación ambiental, además de documentos sobre bases reguladoras, planes de gestión y memorias científicas, convocatorias de investigación, etc.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Ministerio_Transicion_Ecologica/Organismo_Autonomo_Parques_Nacionales/metadata.yaml)
- **Ministerio_Vivienda_Agenda_Urbana**
    La página de Estudios y Publicaciones del Ministerio de Vivienda y Agenda Urbana de España ofrece una recopilación de documentos técnicos y estratégicos relacionados con la vivienda, el urbanismo y la sostenibilidad. Entre los materiales disponibles se encuentran informes del Observatorio de Vivienda, catálogos de buenas prácticas en arquitectura y urbanismo, guías de accesibilidad en espacios públicos urbanizados, y estudios como el "Libro Blanco de la Sostenibilidad en el Planeamiento Urbanístico Español". Estos documentos proporcionan análisis detallados, recomendaciones y marcos normativos que respaldan las políticas públicas en materia de vivienda y desarrollo urbano sostenible.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Ministerio_Vivienda_Agenda_Urbana/metadata.yaml)
- **NORMA**
    Normativa: The set of laws and rules in force in the field of economics and finance.  Doctrina: Interpretation and application of these rules by bodies and experts.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/NORMA/metadata.yaml)
- **Registro_Mercantil_Borme**
    Conjunto de datos extraído del Boletín Oficial del Registro Mercantil (BORME) de España. Contiene anuncios oficiales sobre actos jurídicos y mercantiles de sociedades, como constituciones, nombramientos, ceses, fusiones, y disoluciones, publicados diariamente por el BOE.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/Registro_Mercantil_Borme/metadata.yaml)
- **EuroPat**
    Es un corpus paralelo multilingüe de textos de patentes alineados por oraciones, extraídos de la Oficina Europea de Patentes (EPO) y la USPTO. Contiene datos técnicos y legales en varios idiomas, incluido el par español-inglés, con más de 50 millones de frases.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/EuroPat/metadata.yaml)
- **ParlaMint-ES-AN**
    The source of the data is the official website of the Parliament of Andalusia. On this website, there is a section where the journals of the parliamentary sessions of Andalusia can be searched by date (https://www.parlamentodeandalucia.es/webdinamica/portal-web-parlamento/recursosdeinformacion/diariosdesesiones/plenos.do). Regarding the data contained, it includes information on the parliamentary debates held in the plenary sessions of the Parliament of Andalusia from its inception in 1982 until February 6, 2025. These debates cover topics such as [topic not specified]. It is important to note that, to obtain this data, the PDFs from the indicated link were downloaded and then processed using pytesseract. Therefore, the data may contain errors made by pytesseract in reading these PDFs.
    - Fichero de metadatos: [metadata.yaml](https://github.com/sinai-uja/Vandelvira/blob/main/data/llms/data/processed/legal/ParlaMint-ES-AN/metadata.yaml)


# Estadísticas de los datos

Aquí está la tabla en formato markdown con los porcentajes convertidos:

| Fuente | Num Tokens | Num Instancias | Tokens % | Instancias % |
|--------|------------|----------------|----------|--------------|
| Boletines_Oficiales/BOE | 1.275.960.977 | 264.436 | 24,41% | 3,76% |
| Boletines_Oficiales/BOJA | 870.941.236 | 212.086 | 16,66% | 3,01% |
| EuroPat | 686.393.700 | 5.808.702 | 13,13% | 82,51% |
| Boletines_Oficiales/BOCYL | 616.134.537 | 209.921 | 11,79% | 2,98% |
| Boletines_Oficiales/BORM | 530.661.205 | 217.865 | 10,15% | 3,10% |
| Boletines_Oficiales/BOCANT | 349.985.165 | 156.256 | 6,70% | 2,22% |
| Boletines_Oficiales/BOP_Cordoba | 248.902.474 | 9.112 | 4,76% | 0,13% |
| Boletines_Oficiales/BOC | 141.562.339 | 47.982 | 2,71% | 0,68% |
| Boletines_Oficiales/BOP_Jaen | 106.913.362 | 63.652 | 2,05% | 0,90% |
| Registro_Mercantil_Borme | 103.938.906 | 35.896 | 1,99% | 0,51% |
| Licitaciones | 82.756.627 | 810 | 1,58% | 0,01% |
| ParlaMint-ES-AN | 68.164.267 | 658 | 1,30% | 0,01% |
| Boletines_Oficiales/BOCCE | 37.172.910 | 868 | 0,71% | 0,01% |
| NORMA | 25.811.082 | 6.853 | 0,49% | 0,10% |
| Boletines_Oficiales/BOP_Granada | 22.909.841 | 282 | 0,44% | 0,00% |
| Ministerio_Transicion_Ecologica/Calidad_Evaluacion_Ambiental | 14.069.838 | 2.272 | 0,27% | 0,03% |
| Ministerio_Transicion_Ecologica/Organismo_Autonomo_Parques_Nacionales | 13.425.207 | 605 | 0,26% | 0,01% |
| Ministerio_Transicion_Ecologica/Ministerio | 7.937.682 | 602 | 0,15% | 0,01% |
| Ministerio_Transicion_Ecologica/Energia | 5.479.445 | 327 | 0,10% | 0,01% |
| Boletines_Oficiales/BOP_Sevilla | 5.082.865 | 49 | 0,10% | 0,00% |
| Ministerio_Transicion_Ecologica/Cambio_Climatico | 4.636.644 | 453 | 0,09% | 0,01% |
| Biblioteca_Juridica | 2.575.643 | 40 | 0,05% | 0,00% |
| BODEFENSA | 1.635.147 | 75 | 0,03% | 0,00% |
| Departamento_Seguridad_Nacional | 1.469.757 | 62 | 0,03% | 0,00% |
| Codigo_Tecnico_Edificacion | 1.319.740 | 56 | 0,03% | 0,00% |
| Ministerio_Transicion_Ecologica/Reto_Demografico | 416.145 | 30 | 0,01% | 0,00% |
| Agen_Urb_Esp | 335.451 | 11 | 0,01% | 0,00% |
| Ministerio_Vivienda_Agenda_Urbana | 280.784 | 14 | 0,01% | 0,00% |
| Ministerio_Transicion_Ecologica/Sala_Prensa | 90.664 | 2 | 0,00% | 0,00% |
| **TOTAL** | **5.226.963.640** | **7.039.977** |  |  |
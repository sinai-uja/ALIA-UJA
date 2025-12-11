**Tests de Evaluación para Oposiciones Legal-Administrativas Españolas**

Dataset curado de **1.145 preguntas válidas** extraídas de exámenes oficiales del INAP (Cuerpos AGE, 2015–2024).

Fabián Suárez Maroto | fsmaroto@ujaen.es | Proyecto ALIA

**Tabla de contenido**
- [Descripción General](#descripción-general)
- [Estadísticas del Dataset](#estadísticas-del-dataset)
  - [Resumen del Procesamiento](#resumen-del-procesamiento)
  - [Distribución por Tipo de Examen](#distribución-por-tipo-de-examen)
- [Detalle de Exámenes Incluidos](#detalle-de-exámenes-incluidos)
  - [Cuerpo de Gestión de la Administración Civil del Estado](#cuerpo-de-gestión-de-la-administración-civil-del-estado)
  - [Cuerpo General Administrativo de la Administración del Estado](#cuerpo-general-administrativo-de-la-administración-del-estado)
  - [Cuerpo General Auxiliar de la Administración del Estado](#cuerpo-general-auxiliar-de-la-administración-del-estado)
  - [Escala Técnica de Gestión de Organismos Autónomos](#escala-técnica-de-gestión-de-organismos-autónomos)

---

# Descripción General

Este dataset contiene preguntas y respuestas extraídas de **exámenes oficiales de oposiciones** de la Administración General del Estado (AGE), publicados por el **Instituto Nacional de Administración Pública (INAP)** en su [sede electrónica](https://sede.inap.gob.es/es/procesos-selectivos).

Incluye ítems tipo test correspondientes a diferentes cuerpos de la AGE, cubriendo áreas **legal-administrativas, de gestión pública y normativa estatal**.  
Los datos han sido procesados, alineados y filtrados para garantizar la **consistencia y validez** del conjunto final, útil como **benchmark de evaluación para modelos de lenguaje jurídico-administrativo**.

# Estadísticas del Dataset

## Resumen del Procesamiento

El procesamiento y emparejamiento entre preguntas (CSV) y respuestas (JSON) ha sido complejo debido a cambios estructurales entre convocatorias y variaciones en formato.  
Los resultados finales se resumen en la siguiente tabla:

| Métrica | Valor |
|---------|-------|
| **Preguntas CSV originales** | 2.701 |
| **Respuestas JSON totales** | 2.133 |
| **Respuestas JSON válidas (estructuradas)** | 1.310 |
| **Preguntas con respuesta asociada (match)** | **1.145** |
| **Preguntas descartadas** | 1.556 |
| **Porcentaje de coincidencia** | **42,39 %** |
| **Preguntas anuladas oficialmente** | 41 |


## Distribución por Tipo de Examen

### Resumen Comparativo

| Cuerpo / Escala | Preguntas CSV | Preguntas con Match | Respuestas JSON Válidas | Descartadas | Porcentaje Match |
|-----------------|---------------|---------------------|--------------------------|--------------|------------------|
| **Cuerpo de Gestión de la Administración Civil del Estado** | 1.255 | 288 | 345 | 967 | 22,9 % |
| **Cuerpo General Administrativo de la Administración del Estado** | 795 | 467 | 762 | 328 | 58,7 % |
| **Cuerpo General Auxiliar de la Administración del Estado** | 468 | 317 | 692 | 151 | 67,7 % |
| **Escala Técnica de Gestión de Organismos Autónomos** | 183 | 73 | 221 | 110 | 39,9 % |
| **Total** | **2.701** | **1.145** | **1.310** | **1.556** | **42,39 %** |

### Distribución Visual

```
CGAE  ████████████████████████████████████████████ 58,7%
CGAX  ████████████████████████████████████████████████████ 67,7%
CGACE ████████████████ 22,9%
ETGOA ████████████████████████ 39,9%
```

# Detalle de Exámenes Incluidos

## Cuerpo de Gestión de la Administración Civil del Estado

Incluye preguntas de exámenes oficiales entre 2018 y 2024.  
Total de **1.255 preguntas**, de las cuales **288** se emparejaron con respuesta válida (22,9 %).

| Tipo de Dato | Valor |
|---------------|-------|
| Preguntas CSV procesadas | 1.255 |
| Respuestas JSON válidas | 345 |
| Preguntas con respuesta | 288 |
| Preguntas descartadas | 967 |
| Preguntas anuladas | 9 |

---

## Cuerpo General Administrativo de la Administración del Estado

El conjunto más numeroso y consistente del dataset.  
Incluye **795 preguntas** y **467 ítems con correspondencia válida** (58,7 %).

| Tipo de Dato | Valor |
|---------------|-------|
| Preguntas CSV procesadas | 795 |
| Respuestas JSON válidas | 762 |
| Preguntas con respuesta | 467 |
| Preguntas descartadas | 328 |
| Preguntas anuladas | 26 |

---

## Cuerpo General Auxiliar de la Administración del Estado

Conjunto sólido de **468 preguntas**, de las cuales **317** se emparejaron correctamente con respuesta válida (67,7 %).

| Tipo de Dato | Valor |
|---------------|-------|
| Preguntas CSV procesadas | 468 |
| Respuestas JSON válidas | 692 |
| Preguntas con respuesta | 317 |
| Preguntas descartadas | 151 |
| Preguntas anuladas | 2 |

---

## Escala Técnica de Gestión de Organismos Autónomos

Categoría con menor representación (solo **183 preguntas**), pero con **73 coincidencias válidas** (39,9 %).  
La estructura de estos exámenes difiere del formato de los cuerpos generales.

| Tipo de Dato | Valor |
|---------------|-------|
| Preguntas CSV procesadas | 183 |
| Respuestas JSON válidas | 221 |
| Preguntas con respuesta | 73 |
| Preguntas descartadas | 110 |
| Preguntas anuladas | 4 |

---

# Licencia y Uso

fuente original:  
**Instituto Nacional de Administración Pública (INAP)** — [https://sede.inap.gob.es/es/procesos-selectivos](https://sede.inap.gob.es/es/procesos-selectivos)

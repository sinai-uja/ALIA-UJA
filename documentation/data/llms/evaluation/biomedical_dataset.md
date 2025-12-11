**Tests de Evaluación para Oposiciones Sanitarias Españolas**

Dataset curado de 5.233 preguntas extraídas de exámenes oficiales MIR, FIR, PIR y EIR (2007-2024).

Fabián Suárez Maroto,  | fsmaroto@ujaen.es | Proyecto ALIA

**Tabla de contenido**
- [Descripción General](#descripción-general)
- [Estadísticas del Dataset](#estadísticas-del-dataset)
  - [Resumen del Procesamiento](#resumen-del-procesamiento)
  - [Distribución por Tipo de Examen](#distribución-por-tipo-de-examen)
- [Detalle de Exámenes Incluidos](#detalle-de-exámenes-incluidos)
  - [MIR - Médico Interno Residente](#mir---médico-interno-residente)
  - [FIR - Farmacéutico Interno Residente](#fir---farmacéutico-interno-residente)
  - [PIR - Psicólogo Interno Residente](#pir---psicólogo-interno-residente)
  - [EIR - Enfermero Interno Residente](#eir---enfermero-interno-residente)

---

# Descripción General

Este dataset contiene preguntas de examen extraídas de las pruebas oficiales para acceso a plazas de formación sanitaria especializada en España. El conjunto incluye cuatro tipos de exámenes:

- **MIR** (Médico Interno Residente)
- **FIR** (Farmacéutico Interno Residente)
- **PIR** (Psicólogo Interno Residente)
- **EIR** (Enfermero Interno Residente)

Todos los datos provienen de exámenes oficiales realizados entre 2007 y 2024, habiendo sido procesados y filtrados para garantizar la calidad y consistencia del conjunto final.

# Estadísticas del Dataset

## Resumen del Procesamiento

El proceso de curación y limpieza del dataset ha resultado en las siguientes estadísticas:

| Métrica | Valor |
|---------|-------|
| **Preguntas originales totales** | 12.116 |
| **Preguntas sin respuesta asociada** | 6.707 |
| **Preguntas eliminadas** | 124 |
| **Preguntas con opciones incorrectas** | 52 |
| **Preguntas FINALES incluidas** | **5.233** |
| **Total descartadas** | 6.883 |
| **Porcentaje incluido** | **43,2%** |

## Distribución por Tipo de Examen

### Resumen Comparativo

| Examen | Preguntas | Porcentaje | Nº Exámenes | Promedio/Examen |
|--------|-----------|------------|-------------|-----------------|
| **MIR** | 1.777 | 34,0% | 8 | 222,1 |
| **FIR** | 1.792 | 34,2% | 8 | 224,0 |
| **PIR** | 594 | 11,4% | 3 | 198,0 |
| **EIR** | 1.070 | 20,4% | 5 | 214,0 |

### Distribución Visual

```
MIR ████████████████████████████████████ 34,0%
FIR ████████████████████████████████████ 34,2%
EIR █████████████████████ 20,4%
PIR ███████████ 11,4%
```

# Detalle de Exámenes Incluidos

## MIR - Médico Interno Residente

Total de 8 exámenes con 1.777 preguntas (34,0% del dataset total).

| Año | Preguntas |
|-----|-----------|
| mir_2008 | 250 |
| mir_2010 | 227 |
| mir_2011 | 227 |
| mir_2012 | 230 |
| mir_2015 | 230 |
| mir_2021 | 206 |
| mir_2022 | 204 |
| mir_2024 | 203 |
| **Total** | **1.777** |

## FIR - Farmacéutico Interno Residente

Total de 8 exámenes con 1.792 preguntas (34,2% del dataset total).

| Año | Preguntas |
|-----|-----------|
| fir_2007 | 247 |
| fir_2008 | 244 |
| fir_2015 | 225 |
| fir_2016 | 228 |
| fir_2017 | 229 |
| fir_2021 | 204 |
| fir_2022 | 209 |
| fir_2024 | 206 |
| **Total** | **1.792** |

## PIR - Psicólogo Interno Residente

Total de 3 exámenes con 594 preguntas (11,4% del dataset total).

| Año | Preguntas |
|-----|-----------|
| pir_2021 | 182 |
| pir_2022 | 204 |
| pir_2024 | 208 |
| **Total** | **594** |

## EIR - Enfermero Interno Residente

Total de 5 exámenes con 1.070 preguntas (20,4% del dataset total).

| Año | Preguntas |
|-----|-----------|
| eir_2016 | 223 |
| eir_2017 | 228 |
| eir_2021 | 206 |
| eir_2022 | 205 |
| eir_2024 | 208 |
| **Total** | **1.070** |











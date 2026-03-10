"""Scraper mejorado para la web institucional de FAISEM (v2).

Este módulo es una versión fortificada y optimizada respecto al scraper
base de FAISEM. Incorpora mitigaciones anti-detección (anti-bot) para Chromium,
gestión aleatoria de retrasos (`delay`), e implementa un sistema de 
procesamiento en dos fases: extracción y almacenamiento de URLs 
(productor) y lectura y scraping de contenido (consumidor) mediante TXTs.

Example:
    Ejecución estándar para reanudación::

        python scrapeo_biomedico_faisem2.py

    Iniciará leyendo (si se habilitó) o procesando URLs crudas guardadas 
    en un TXT hasta conformar el archivo `FAISEM_biomedicina.csv`.

Note:
    Require flags avanzados de Selenium (`--disable-blink-features=AutomationControlled`,
    inyección de Javascript para ocultar variable de entorno `navigator.webdriver`).
"""

import os
import time
import random
import gc
from datetime import datetime
import pandas as pd
import fitz  # PyMuPDF
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

script_dir = os.path.dirname(os.path.abspath(__file__))
identificador_contador = 459

def iniciar_driver():
    """Configura e inicia un WebDriver de Chrome con técnicas anti-scraping.

    Implementa el modo `--headless=new` e inyecta Javascript en las páginas cargadas
    para oscurecer la propiedad de automatización del navegador frente 
    al sitio objetivo. Evita bloqueos de bot.

    Returns:
        webdriver.Chrome: Instancia segura e indetectable.
    """
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')  # Nueva versión headless menos detectable
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--enable-unsafe-swiftshader')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    driver = webdriver.Chrome(options=chrome_options)
    
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined
            });
        """
    })
    return driver


def verificar_carga(driver: webdriver.Chrome, selector: str, busqueda: str) -> bool:
    """Aplica control de esperas con refrescos para mitigar timeouts estáticos.

    Args:
        driver (webdriver.Chrome): Ventana en curso del navegador.
        selector (str): Método orientador (Ej. `By.CSS_SELECTOR`).
        busqueda (str): Query selector a vigilar.

    Returns:
        bool: Retorna True si se localizó el elemento, caso contrario False tras 5 intentos.
    """
    intentos_maximos = 5
    for intento in range(intentos_maximos):
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((selector, busqueda)))
            return True
        except Exception as e:
            print(f"Intento {intento+1}/{intentos_maximos}: Error: {e}. Reintentando...")
            driver.refresh()
            time.sleep(2)
    return False

def limpiar_texto(texto: str) -> str:
    """Filtra y normaliza espacios y retornos en secuencias de texto.

    Args:
        texto (str): Texto crudo.

    Returns:
        str: Texto limpio con espaciado sencillo.
    """
    return " ".join(str(texto).split())

def crear_df_temporal(identificador: str, titulo: str, resumen: str, contenido: str, enlace: str) -> pd.DataFrame:
    """Prepara un bloque de datos DataFrame para anexar al repositorio CSV.

    Args:
        identificador (str): ID numérico que evoluciona como contador global (`identificador_contador`).
        titulo (str): Título principal del post.
        resumen (str): Introducción extraída, si no, los 200 primeros caracteres.
        contenido (str): Texto principal de la noticia.
        enlace (str): URL de soporte.

    Returns:
        pd.DataFrame: DataFrame de 1 renglón estandarizado.
    """
    fecha_lectura = datetime.today().strftime("%d-%m-%Y")
    nuevo_df = pd.DataFrame([{
        "id": identificador,
        "seccion": titulo,
        "resumen": resumen,
        "contenido": contenido,
        "url": enlace,
        "fecha_lectura": fecha_lectura
    }])
    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(limpiar_texto)
    return nuevo_df

def guardar_contenido_csv(df: pd.DataFrame, ruta: str) -> None:
    """Anexa un archivo DataFrame unitario al registro documental.

    Args:
        df (pd.DataFrame): Dataset Pandas a almacenar de forma iterativa.
        ruta (str): Directorio raíz destino.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/FAISEM_biomedicina.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

def escribir_url_errores(archivo_errores: str, url: str) -> None:
    """Registra en disco las URLs web que resultaron en error persistente.

    Args:
        archivo_errores (str): Path destino (sin extensión).
        url (str): Dirección web de la discordia.
    """
    with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
        file.write(url + "\n")

def extraer_enlaces_y_guardar(base_enlace: str, ruta_txt_enlaces: str, max_paginas: int = 220) -> None:
    """Recolecta inicialmente las URLs de todos los posts guardándolas en un archivo plano.

    Actúa como productor en el diseño bi-fase del script; sólo recolecta y guarda.
    Abarca recorridos completos hasta un límite teórico.

    Args:
        base_enlace (str): URL predefinida de 'category/noticias'.
        ruta_txt_enlaces (str): Ruta donde guardar el log secuencial TXT.
        max_paginas (int, optional): Páginas web de CMS máximos a escrapear. Defaults to 220.
    """
    for pagina in range(1, max_paginas + 1):
        enlace_pagina = f"{base_enlace}/page/{pagina}/" if pagina > 1 else base_enlace
        driver = iniciar_driver()
        driver.get(enlace_pagina)

        if verificar_carga(driver, By.CSS_SELECTOR, "div.et_pb_section.et_pb_section_0_tb_body.et_section_regular"):
            blog_inicial = driver.find_element(By.CSS_SELECTOR, "div.et_pb_section.et_pb_section_0_tb_body.et_section_regular")
            los_contenidos = blog_inicial.find_element(By.CLASS_NAME, "et_pb_ajax_pagination_container")
            todos_articulos = los_contenidos.find_elements(By.TAG_NAME, "article")

            with open(ruta_txt_enlaces, 'a', encoding='utf-8') as f:
                for articulo_elemento in todos_articulos:
                    etiqueta = articulo_elemento.find_element(By.TAG_NAME, 'h2').find_element(By.TAG_NAME, 'a')
                    enlace = etiqueta.get_attribute('href')
                    f.write(enlace + '\n')
        else:
            break
        driver.quit()

def procesar_enlaces_desde_txt(ruta_txt_enlaces: str, ruta_csv: str, ruta_errores: str) -> None:
    """Etapa consumidora: Ingresa a cada enlace de la lista y realiza la extracción real.

    Por cada URL válida que consume del archivo de texto, borra la línea procesada
    (asegurando resiliencia ante bloqueos). Aplica esperas aleatorias.

    Args:
        ruta_txt_enlaces (str): Ubicación del pool TXT.
        ruta_csv (str): Path matriz del archivo `*_biomedicina.csv`.
        ruta_errores (str): Path logeador de URLs rotas.
    """
    global identificador_contador
    while True:
        if not os.path.exists(ruta_txt_enlaces) or os.path.getsize(ruta_txt_enlaces) == 0:
            print("No quedan enlaces por procesar. Fin del scraping.")
            break

        with open(ruta_txt_enlaces, 'r', encoding='utf-8') as f:
            enlaces = f.readlines()

        if not enlaces:
            print("Archivo de enlaces vacío. Fin.")
            break

        enlace = enlaces[0].strip()
        print(f"Procesando: {enlace}")
        driver = iniciar_driver()
        driver.get(enlace)

        if verificar_carga(driver, By.CLASS_NAME, "entry-title"):
            try:
                titulo = driver.find_element(By.CLASS_NAME, "entry-title").text
                dondelosp = driver.find_element(By.CLASS_NAME, "entry-content")
                p = dondelosp.find_elements(By.TAG_NAME, "p")
                contenido = " ".join([parrafo.text for parrafo in p])
                resumen = contenido[:200]
                identificador = f"Noticia_{identificador_contador}"
                identificador_contador += 1
                df = crear_df_temporal(identificador, titulo, resumen, contenido, enlace)
                guardar_contenido_csv(df, os.path.dirname(ruta_csv))
            except Exception as e:
                print(f"❌ Error leyendo contenido: {e}")
                escribir_url_errores(ruta_errores, enlace)
        else:
            escribir_url_errores(ruta_errores, enlace)

        driver.quit()

        with open(ruta_txt_enlaces, 'w', encoding='utf-8') as f:
            f.writelines(enlaces[1:])

        delay = random.uniform(10, 22)
        time.sleep(delay)

if __name__ == "__main__":
    carpeta_adquisiciones = os.path.join(script_dir, "FAISEM_BUENO")
    os.makedirs(carpeta_adquisiciones, exist_ok=True)
    ruta_enlaces_txt = os.path.join(carpeta_adquisiciones, "enlaces_faisem.txt")
    ruta_csv = os.path.join(carpeta_adquisiciones, "FAISEM_biomedicina.csv")
    ruta_errores = os.path.join(carpeta_adquisiciones, "url_errores")

    base_enlace = "https://faisem.es/category/noticias"


    ruta_errores_volver = os.path.join(script_dir, "FAISEM_intento", "url_errores_volver.txt")
    procesar_enlaces_desde_txt(ruta_errores_volver, ruta_csv, ruta_errores)
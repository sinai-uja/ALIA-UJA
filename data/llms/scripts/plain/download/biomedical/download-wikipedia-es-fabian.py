"""Extractor de artículos en Español de Wikipedia por categorías.

Este módulo emplea la API de Wikipedia (es.wikipedia.org) para extraer 
artículos enciclopédicos desde categorías principales (Ciencia, Humanidades...)
y sus subcategorías. Guarda el contenido en formato TXT y mantiene un
registro JSON con los metadatos y estadísticas del corpus recolectado.

Example:
    Ejecución básica::

        python download-wikipedia-es-fabian.py

    Descargará recursivamente artículos y generará la carpeta `articulos_wikipedia`
    con el contenido clasificado y guardado.

Attributes:
    WikipediaAPI (class): Clase gestora de peticiones y lógica de la API de Wikipedia.
"""

import requests
import json
import os
import re
import time
from collections import Counter

class WikipediaAPI:
    """Manejador de la API de Wikipedia.

    Proporciona métodos encapsulados para extraer listados de categorías
    y contenidos enteros de páginas utilizando `requests.Session()`
    para mejorar el rendimiento general.

    Attributes:
        api_url (str): Endpoint base de la API de Wikipedia en español.
        session (requests.Session): Sesión persistente para llamadas HTTP.
    """

    def __init__(self) -> None:
        """Inicializa la interfaz de conexión de la API."""
        self.api_url = "https://es.wikipedia.org/w/api.php"
        self.session = requests.Session()

    def get_category_members(self, category_name: str, cmtype: str = "page|subcat", cmcontinue: str = None) -> tuple:
        """Obtiene los miembros de una categoría mediante la acción 'categorymembers'.

        Args:
            category_name (str): Título de la categoría.
            cmtype (str, optional): Tipos de páginas a extraer ("page", "subcat" o combinados). Defaults to "page|subcat".
            cmcontinue (str | None, optional): Token de paginación de la API de Wikipedia para seguir recabando. Defaults to None.

        Returns:
            tuple: Una tupla estipulada como `(members, cmcontinue)`.
                `members` (list) es una lista con los elementos descritos por la API.
                `cmcontinue` (str | None) es el token de avance para siguientes bloques o None.
        """
        params = {
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": category_name,
            "cmlimit": "500",
            "cmtype": cmtype
        }

        if cmcontinue:
            params["cmcontinue"] = cmcontinue

        response = self.session.get(url=self.api_url, params=params)
        data = response.json()

        members = data.get("query", {}).get("categorymembers", [])
        cmcontinue = data.get("continue", {}).get("cmcontinue")

        return members, cmcontinue

    def get_page_content(self, page_id: int) -> dict | None:
        """Obtiene el contenido completo de una página proporcionando su ID.

        Args:
            page_id (int): Identificador único numérico de la página en Wikipedia.

        Returns:
            dict | None: Un diccionario de datos con la respuesta JSON de la API
                bajo la clave 'pages', o None si falla.
        """
        params = {
            "action": "query",
            "format": "json",
            "prop": "revisions|categories|info",
            "pageids": page_id,
            "rvprop": "content|timestamp|user|userid",
            "rvslots": "main",
            "inprop": "url"
        }

        response = self.session.get(url=self.api_url, params=params)
        data = response.json()

        if "query" in data and "pages" in data["query"]:
            return data["query"]["pages"]
        return None

def sanitize_filename(filename: str) -> str:
    """Convierte un título en un nombre de archivo válido para el SO.

    Args:
        filename (str): Cadena de texto base.

    Returns:
        str: Cadena de texto sin caracteres prohibidos ni espacios.
    """
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    filename = filename.replace(' ', '_')
    filename = filename.replace(':', '_')  # Replace colons with underscores
    return filename

def create_directory(path: str) -> None:
    """Crea una estructura de directorios si no existe.

    Args:
        path (str): Ruta completa a crear.
    """
    if not os.path.exists(path):
        os.makedirs(path)

def save_article_as_txt(article_data: dict, category_path: str, full_category_name: str) -> dict:
    """Guarda el contenido del artículo en un archivo TXT formateado.

    Agrega contenido como título, URL y texto principal al gestor de archivos.
    Evita sobrescrituras añadiendo un sufijo numérico si el archivo existe.

    Args:
        article_data (dict): Diccionario de datos del artículo extraído de la API.
        category_path (str): Ruta de la carpeta a la que corresponda la categoría.
        full_category_name (str): Nombre estético y completo de la cadena de categorías.

    Returns:
        dict: Metadatos simplificados del artículo para el índice JSON global.
    """
    create_directory(category_path)

    filename = sanitize_filename(article_data["title"]) + '.txt'
    file_path = os.path.join(category_path, filename)

    # Si el archivo ya existe, agrega un sufijo numérico para evitar sobrescrituras.
    counter = 1
    while os.path.exists(file_path):
        filename = f"{sanitize_filename(article_data['title'])}_{counter}.txt"
        file_path = os.path.join(category_path, filename)
        counter += 1

    content = f"""Título: {article_data['title']}
URL: {article_data['url']}
Categoría completa: {full_category_name}

Contenido:
{article_data['content']}
"""

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return {
        "title": article_data["title"],
        "pageid": article_data["pageid"],
        "timestamp": article_data["timestamp"],
        "contributor": article_data["contributor"],
        "categories": article_data["categories"],
        "url": article_data["url"],
        "length": len(article_data["content"]),
        "main_category": full_category_name
    }

def process_category(
    wiki_api: WikipediaAPI, 
    category_name: str, 
    base_path: str, 
    category_folder: str, 
    full_category_name: str, 
    depth: int = None, 
    current_depth: int = 1, 
    visited_subcategories: set = None
) -> list:
    """Procesa una categoría y sus subcategorías recursivamente.

    Extrae metadatos y crea archivos guardándolos por lotes según avance.
    Respeta saltos de páginas de la API y pausas (rate limits).

    Args:
        wiki_api (WikipediaAPI): Instancia del gestor web de la API.
        category_name (str): Título formal de la categoría en curso.
        base_path (str): Directorio raíz.
        category_folder (str): Carpeta específica de guardado para el TXT.
        full_category_name (str): Nombre completo de la cadena de subcategorías.
        depth (int, optional): Profundidad máxima de recursión. Defaults to None.
        current_depth (int, optional): Control de nivel actual. Defaults to 1.
        visited_subcategories (set, optional): Memoria de bucles para no procesar duplicados. Defaults to None.

    Returns:
        list: Una lista con todos los metadatos de los artículos hallados bajo este nodo.
    """
    if visited_subcategories is None:
        visited_subcategories = set()

    if category_name in visited_subcategories:
        return []  # Evita procesar la misma subcategoría más de una vez.

    if depth is not None and current_depth > depth:
        return []  # Alcanzó la profundidad máxima especificada.

    print(f"Procesando categoría: {category_name} (Profundidad: {current_depth})")
    visited_subcategories.add(category_name)

    # Construir la ruta completa de la categoría
    corpus_path = os.path.join(base_path, "Corpus", category_folder)
    meta_path = os.path.join(base_path, "meta", category_folder)
    create_directory(corpus_path)
    create_directory(meta_path)

    # Initialize metadata for this category
    category_metadata = []
    cmcontinue = None

    while True:
        # Get category members
        members, cmcontinue = wiki_api.get_category_members(category_name, cmtype="page", cmcontinue=cmcontinue)

        for member in members:
            if member['ns'] == 0:  # Articles only
                # Get article content
                pages = wiki_api.get_page_content(member['pageid'])

                if pages:
                    for page in pages.values():
                        if 'revisions' in page:
                            content = page['revisions'][0]['slots']['main']['*']
                            contributor = {
                                'user': page['revisions'][0]['user'],
                                'userid': page['revisions'][0]['userid']
                            }
                            categories = [cat['title'] for cat in page.get('categories', [])]

                            article_data = {
                                "title": page['title'],
                                "pageid": page['pageid'],
                                "timestamp": page['revisions'][0]['timestamp'],
                                "contributor": contributor,
                                "categories": categories,
                                "url": page['fullurl'],
                                "content": content
                            }

                            # Save article and update metadata
                            metadata = save_article_as_txt(article_data, corpus_path, full_category_name)
                            if metadata:
                                category_metadata.append(metadata)

                                # Save individual article metadata
                                article_meta_file = os.path.join(meta_path, f"{sanitize_filename(article_data['title'])}__metadata.json")
                                try:
                                    with open(article_meta_file, 'w', encoding='utf-8') as f:
                                        json.dump(metadata, f, ensure_ascii=False, indent=2)
                                except IOError as e:
                                    print(f"Error saving metadata for article {article_data['title']}: {e}")

                # Respect Wikipedia API rate limits
                time.sleep(1)

        if not cmcontinue:
            break

    # Process subcategories recursively, but don't create new directories for deeper levels
    subcats, _ = wiki_api.get_category_members(category_name, cmtype="subcat")
    for subcat in subcats:
        subcat_name = subcat["title"].replace('Categoría:', '')
        new_full_category_name = full_category_name + " > " + subcat_name
        process_category(
            wiki_api, subcat["title"], base_path, category_folder, new_full_category_name,
            depth=depth, current_depth=current_depth + 1, visited_subcategories=visited_subcategories
        )

    # Calculate statistics
    total_articles = len(category_metadata)
    total_length = sum(article['length'] for article in category_metadata)
    average_length = total_length / total_articles if total_articles > 0 else 0
    category_counter = Counter(cat for article in category_metadata for cat in article['categories'])

    statistics = {
        "total_articles": total_articles,
        "average_article_length": average_length,
        "category_distribution": dict(category_counter)
    }

    # Save category metadata in the 'meta' folder
    category_meta_file = os.path.join(meta_path, f"{sanitize_filename(full_category_name)}_metadata.json")
    try:
        with open(category_meta_file, 'w', encoding='utf-8') as f:
            json.dump({"metadata": category_metadata, "statistics": statistics}, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"Error saving metadata for category {category_name}: {e}")

    return category_metadata

def main() -> None:
    """Flujo de control principal del script.

    Instancia el recolector, define un listado de categorías principales
    de alto nivel de Wikipedia y arranca el procesamiento recursivo para
    cada una de ellas bajo un directorio base.
    """
    wiki_api = WikipediaAPI()

    main_categories = [
        "Categoría:Ciencia",
        "Categoría:Humanidades",
        "Categoría:Naturaleza",
        "Categoría:Personas",
        "Categoría:Sociedad"
    ]

    base_path = "articulos_wikipedia"
    profundidad = None
    create_directory(base_path)

    for category in main_categories:
        print(f"\nProcesando categoría principal: {category}")
        category_name = category.replace('Categoría:', '')

        # Process each main category and its immediate subcategories
        subcategories, _ = wiki_api.get_category_members(category, cmtype="subcat")
        for subcat in subcategories:
            subcat_name = subcat["title"].replace('Categoría:', '')
            subcat_folder = os.path.join(category_name, sanitize_filename(subcat_name))

            # Procesar cada subcategoría y guardar todos los artículos en ella
            process_category(wiki_api, subcat["title"], base_path, subcat_folder, subcat_name, depth=profundidad)

    print("\nProceso completado. Los artículos han sido guardados en la carpeta 'articulos_wikipedia'")

if __name__ == "__main__":
    main()

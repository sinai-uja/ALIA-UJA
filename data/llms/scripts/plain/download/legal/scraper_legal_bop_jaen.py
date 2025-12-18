import os
from bs4 import BeautifulSoup
import requests
import csv
import pandas as pd
import time
from datetime import datetime
from requests.exceptions import ChunkedEncodingError
import fitz  # PyMuPDF
from tqdm import tqdm
import gc
import zipfile
import argparse


# Calendar for iterating through all days of the year
CALENDAR = {
    1: list(range(1, 32)),
    2: list(range(1, 30)),
    3: list(range(1, 32)),
    4: list(range(1, 31)), 
    5: list(range(1, 32)), 
    6: list(range(1, 31)),  
    7: list(range(1, 32)), 
    8: list(range(1, 32)),  
    9: list(range(1, 31)),  
    10: list(range(1, 32)), 
    11: list(range(1, 31)), 
    12: list(range(1, 32))  
}


def clean_text(text):
    """Clean text by removing extra whitespace."""
    return " ".join(str(text).split()) 


def extract_text_direct(pdf_path, min_chars=50):
    """
    Extract text directly using PyMuPDF.
    
    Parameters:
    - pdf_path: Path to the PDF file
    - min_chars: Minimum number of characters required
    
    Returns:
    - tuple: (extracted_text, success_flag)
    """
    try:
        direct_text = ""
        gc.collect()
        doc = fitz.open(pdf_path)
        for page in doc:
            direct_text += page.get_text()
        doc.close()
        
        # Check if there's enough text
        if direct_text and len(direct_text.strip()) > min_chars:
            return direct_text, True
        return "", False
    except Exception as e:
        print(f"Error in direct extraction from {os.path.basename(pdf_path)}: {e}")
        return "", False


def write_error_url(error_file, url):
    """
    Write error URL to log file.
    
    Parameters:
    - error_file: Path to error log file (without extension)
    - url: URL that caused the error
    """
    try:
        os.makedirs(os.path.dirname(error_file), exist_ok=True)
        with open(f"{error_file}.txt", "a", encoding="utf-8") as file:
            file.write(url + "\n")
    except Exception as e:
        print(f"Error writing to error file: {e}")


def attempt_request(url, error_path, max_retries=5):
    """
    Attempt to make an HTTP request with retry logic.
    
    Parameters:
    - url: URL to fetch
    - error_path: Path to error log
    - max_retries: Maximum number of retry attempts
    
    Returns:
    - tuple: (response, success_flag)
    """
    response_found = 0
    response = None
    
    try:
        response = requests.get(url, stream=True, timeout=30)
        if response and response.status_code == 200:
            response_found = 1
            return response, response_found

        elif response.status_code == 404:
            response_found = 1
            return response, response_found
        else:
            found = False
            for i in range(max_retries):
                print(f"Could not access {url}: retrying ({i+1}/{max_retries})")
                time.sleep(i + 1)
                response = requests.get(url, timeout=30) 
                if response and response.status_code == 200:
                    print("Retry accepted")
                    found = True
                    break
            
            if not found:
                write_error_url(error_path, url)
            
            response_found = 1
            return response, response_found
        
    except ChunkedEncodingError:
        print(f"Data transfer error")
        write_error_url(error_path, url)
        return None, 0
        
    except requests.exceptions.RequestException as e:
        print(f"Error accessing {url}: {e}")
        write_error_url(error_path, url)
        return None, 0


def save_to_csv(df, path, year):
    """
    Save DataFrame to CSV file (append mode).
    
    Parameters:
    - df: DataFrame to save
    - path: Directory path
    - year: Year (used for filename)
    """
    if not df.empty:
        csv_file = os.path.join(path, f"{year}.csv")
        file_exists = os.path.exists(csv_file)
        df.to_csv(csv_file, mode="a", index=False, encoding='utf-8', header=not file_exists)


def download_pdf(response_pdf, pdf_path):
    """
    Download PDF from HTTP response.
    
    Parameters:
    - response_pdf: HTTP response object containing PDF
    - pdf_path: Path where PDF will be saved
    """
    try:
        with open(pdf_path, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
        print(f"PDF downloaded: {pdf_path}")
    except Exception as e:
        print(f"Error downloading PDF: {e}")


def create_temp_df(identifier, decree_date, section, subsection, text_content, pdf_url, pdf_local_path):
    """
    Create temporary DataFrame with decree information.
    
    Parameters:
    - identifier: Unique identifier for the decree
    - decree_date: Date of the decree
    - section: Section name
    - subsection: Subsection name
    - text_content: Extracted text content
    - pdf_url: URL of the PDF
    - pdf_local_path: Local path where PDF is saved
    
    Returns:
    - DataFrame: Single-row DataFrame with decree data
    """
    today = datetime.today()
    reading_date = today.strftime("%d-%m-%Y")

    new_df = pd.DataFrame([{
        "id": identifier,
        "decree_date": decree_date,
        "section": section,
        "subsection": subsection,
        "content": text_content,
        "url": pdf_url,
        "reading_date": reading_date,
        "pdf_path": pdf_local_path
    }])

    # Clean text column by column
    for col in new_df.columns:
        new_df[col] = new_df[col].apply(lambda x: clean_text(x))

    return new_df


def scraper_official_bulletins(year,
                              base_url="https://bop.dipujaen.es/bop",
                              output_dir="data",
                              calendar=None):
    """
    Scrape complete days of official bulletins for a given year.
    
    Parameters:
    - year: Year to scrape
    - base_url: Base URL for the bulletin website
    - output_dir: Base output directory for data
    - calendar: Dictionary with month: days mapping (uses default if None)
    """
    if calendar is None:
        calendar = CALENDAR
    
    # Setup directories
    year_dir = os.path.join(output_dir, str(year))
    pdf_dir = os.path.join(year_dir, "PDF")
    csv_dir = year_dir
    error_file = os.path.join(year_dir, "url_errors")
    progress_file = os.path.join(year_dir, f"{year}.txt")
    
    # Create folders if they don't exist
    folders = [year_dir, pdf_dir, csv_dir]
    for folder in folders:
        os.makedirs(folder, exist_ok=True)
    
    # Load or initialize progress
    month = 1
    day = 1
    bulletin_number = 1
    
    if not os.path.exists(progress_file):
        with open(progress_file, 'w', encoding='utf-8') as f:
            f.write(f"{month},{day},{bulletin_number}")
        print("Initializing progress...")
    else:
        with open(progress_file, 'r', encoding='utf-8') as f:
            month, day, bulletin_number = map(int, f.read().strip().split(','))
        print("Loading previous progress...")
    
    print(f"STARTING FROM DAY -> {day}-{month}-{year}")
    
    csv_path = os.path.join(csv_dir, f"{year}.csv")
    
    for current_month in range(month, 13):  
        days_in_month = calendar.get(current_month, [])
        
        for current_day in days_in_month[day-1:]:
            try: 
                url = f"{base_url}/{current_day:02}-{current_month:02}-{year}"
                print(f"Accessing URL: {url}")
                
                response, found = attempt_request(url, error_file)
                
                if found == 1 and response and response.status_code == 200:
                    soup = None
                    try: 
                        soup = BeautifulSoup(response.text, 'html.parser')
                    except Exception as e:
                        print(f"Could not parse bulletin: {e}")
                        continue
                    
                    bulletin_summary = soup.find("div", id="sumarioBoletin")
                    
                    if bulletin_summary:
                        # Check for corrections
                        correction = soup.find("p", class_="seccion")
                        if correction:
                            correction_text = correction.text
                            
                            if correction_text == "Rectificación de Errores":
                                print(f"Found bulletin correction, downloading...")
                                correction_name = correction_text
                                correction_subsection = correction.find_next_sibling().text if correction.find_next_sibling() else ""
                                pdf_access = soup.find("p", attrs={"style": "text-align: center"})
                                
                                if pdf_access:
                                    identifier = f"BOP-{year}-Bulletin-{bulletin_number}-Section-0-Decree-0"
                                    pdf_url = pdf_access.find('a')['href']
                                    
                                    pdf_response, pdf_found = attempt_request(pdf_url, error_file)
                                    if pdf_found == 1 and pdf_response and pdf_response.status_code == 200:
                                        pdf_save_path = os.path.join(pdf_dir, f"{identifier}.pdf")
                                        download_pdf(pdf_response, pdf_save_path)
                                        pdf_text, success = extract_text_direct(pdf_save_path)
                                        
                                        if success:
                                            df = create_temp_df(identifier, f"{current_day}-{current_month}-{year}", 
                                                              correction_name, correction_subsection, 
                                                              pdf_text, pdf_url, pdf_save_path)
                                            save_to_csv(df, csv_dir, year)
                                            print(f"Saved corrected decree content")
                        
                        # Process sections
                        sections = bulletin_summary.find_all("section")
                        current_section = ""
                        current_subsection = ""
                        section_num = 0
                        
                        for section in sections:
                            section_num += 1
                            decree_num = 0
                            all_tags = section.find_all()
                            
                            for tag in all_tags:
                                if tag.name == 'p':
                                    class_name = tag.get('class')  
                                    if class_name:
                                        if class_name[0] == 'seccion':
                                            current_section = tag.text
                                            print(f"Current Section: {current_section}")
                                        elif class_name[0] == 'subseccion':
                                            current_subsection = tag.text
                                            print(f"Current Subsection: {current_subsection}")
                                            
                                elif tag.name == 'article':
                                    decree_num += 1
                                    identifier = f"BOP-{year}-Bulletin-{bulletin_number}-Section-{section_num}-Decree-{decree_num}"
                                    pdf_access = tag.find("p", attrs={"style": "text-align: center"})
                                    
                                    if pdf_access and pdf_access.find('a'):
                                        pdf_url = pdf_access.find('a')['href']
                                        pdf_response, pdf_found = attempt_request(pdf_url, error_file)
                                        
                                        if pdf_found == 1 and pdf_response and pdf_response.status_code == 200:
                                            pdf_save_path = os.path.join(pdf_dir, f"{identifier}.pdf")
                                            
                                            if not os.path.exists(pdf_save_path):
                                                download_pdf(pdf_response, pdf_save_path)
                                                pdf_text, success = extract_text_direct(pdf_save_path)
                                                time.sleep(1.2)
                                                
                                                if success:
                                                    df = create_temp_df(identifier, f"{current_day}-{current_month}-{year}", 
                                                                       current_section, current_subsection, 
                                                                       pdf_text, pdf_url, pdf_save_path)
                                                    save_to_csv(df, csv_dir, year)
                                                    print(f"Saved decree -> Bulletin-{bulletin_number}-Sec-{section_num}-Dec-{decree_num}")
                                else:
                                    time.sleep(0.1)
                        
                        bulletin_number += 1
                        
                        # Update progress
                        with open(progress_file, 'w', encoding='utf-8') as f:
                            f.write(f"{current_month},{current_day},{bulletin_number}")
                    else:
                        print(f"Day: {current_day}-{current_month}-{year} contains no decrees")
                
                else:
                    print(f"Bulletin page {bulletin_number} does not exist")
            
            except ChunkedEncodingError as e:
                print(f"Data transfer error: {e}")
                continue
            
            except requests.exceptions.RequestException as e:
                print(f"Request rejected: {e}")
                continue
            
            except Exception as e:
                print(f"Unexpected error on day {current_day}: {e}")
                continue
        
        # Reset day counter for next month
        day = 1
        
        # Update progress file for next month
        with open(progress_file, 'w', encoding='utf-8') as f:
            f.write(f"{current_month + 1},1,{bulletin_number}")
    
    # Convert CSV to Parquet
    parquet_path = os.path.join(csv_dir, f"{year}.parquet")
    try:
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path, encoding='utf-8')
            df.to_parquet(parquet_path, index=False)
            print(f"✅ CSV converted to Parquet: {parquet_path}")
    except Exception as e:
        print(f"❌ Error converting CSV to Parquet for year {year}: {e}")
    
    # Create ZIP with all files for the year
    zip_path = os.path.join(output_dir, f"{year}.zip")
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add parquet file to ZIP
            if os.path.exists(parquet_path):
                zipf.write(parquet_path, os.path.basename(parquet_path))
            # Add CSV file to ZIP
            if os.path.exists(csv_path):
                zipf.write(csv_path, os.path.basename(csv_path))
            print(f"✅ ZIP file created: {zip_path}")
    except Exception as e:
        print(f"❌ Error creating ZIP file for year {year}: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Official Bulletin Scraper')
    parser.add_argument('--year', type=int, default=2000, 
                       help='Year to scrape (default: 2000)')
    parser.add_argument('--base-url', type=str, default='https://bop.dipujaen.es/bop',
                       help='Base URL of the bulletin')
    parser.add_argument('--output-dir', type=str, default='data',
                       help='Output directory for data')
    
    args = parser.parse_args()
    
    scraper_official_bulletins(
        year=args.year,
        base_url=args.base_url,
        output_dir=args.output_dir
    )

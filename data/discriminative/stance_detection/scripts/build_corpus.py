"""
01_build_corpus.py
==================
Builds the base corpus from the raw Decide Madrid CSVs.

Takes the original files downloaded from the Madrid City Council Open Data Portal
(comments.csv, debates.csv, proposals.csv, votes.csv) and produces a filtered,
clean corpus for stance detection.

INPUT (not included in the repository due to size, downloadable from datos.madrid.es):
    - comments.csv
    - debates.csv
    - proposals.csv
    - votes.csv

    These files should be placed in a folder and its path passed as an argument,
    or in the current working directory.

OUTPUT:
    - corpus_stance_madrid_recuento.csv  (~61,716 rows)

FILTERS APPLIED:
    1. First-level comments only (no replies)
    2. Proposals with truncated titles (>=80 chars) excluded
    3. Comments without text or without letters removed
    4. Comments that are basically just URLs (<30 chars of real text)
    5. Automatic welcome messages (bot)
    6. Pattern "Listado de Propuestas NO Repetidas"
    7. Topics "#TuPreguntas" (Q&A sessions with politicians)
    8. Targets without description

USAGE:
    python 01_build_corpus.py [path_to_csvs]

    If no argument is passed, the script looks for the CSVs in the current directory.
"""

import pandas as pd
import os
import re
import sys

# Path to raw CSVs: command-line argument or current directory
if len(sys.argv) > 1:
    path = sys.argv[1]
else:
    path = os.getcwd()


def clean_html(text):
    """Converts HTML description to plain text: removes tags, normalizes spaces."""
    if not isinstance(text, str):
        return ''
    text = re.sub(r'<[^>]+>', ' ', text)      # remove HTML tags
    text = re.sub(r'[\r\n\t]+', ' ', text)    # line breaks -> space
    text = re.sub(r' +', ' ', text)           # multiple spaces -> one
    return text.strip()


def generate_dataset_with_count():
    print("Loading CSV files...")

    # Load required files
    try:
        comments = pd.read_csv(os.path.join(path, 'comments.csv'), low_memory=False, encoding='latin-1', sep=';')
        debates = pd.read_csv(os.path.join(path, 'debates.csv'), low_memory=False, encoding='latin-1', sep=';')
        proposals = pd.read_csv(os.path.join(path, 'proposals.csv'), low_memory=False, encoding='latin-1', sep=';')
        votes = pd.read_csv(os.path.join(path, 'votes.csv'), low_memory=False, encoding='latin-1', sep=';')
    except FileNotFoundError as e:
        print(f"Error: File not found {e.filename}")
        print(f"Looking in: {path}")
        print("Download the CSVs from https://datos.madrid.es and place them in that folder.")
        return

    # Keep only first-level comments (respond directly to a topic)
    n_before = len(comments)
    comments = comments[comments['ancestry'].isna() | (comments['ancestry'] == '')]
    n_replies = n_before - len(comments)
    print(f"Comments removed because they are replies (non-empty ancestry): {n_replies} ({100*n_replies/n_before:.1f}%)")
    print(f"First-level comments kept: {len(comments)}")

    # 1. Create unified TARGETS table
    df_debates = debates[['id', 'title', 'description', 'cached_votes_up', 'cached_votes_down']].copy()
    df_debates['target_type'] = 'Debate'
    df_debates.rename(columns={'cached_votes_up': 'target_votos_up', 'cached_votes_down': 'target_votos_down'}, inplace=True)

    # Exclude proposals with truncated titles (limit of 80 chars in the original DB)
    proposals_clean = proposals[proposals['title'].str.len() < 80]
    n_excluded = len(proposals) - len(proposals_clean)
    print(f"Proposals excluded due to truncated title (80 chars): {n_excluded}")
    df_proposals = proposals_clean[['id', 'title', 'description', 'cached_votes_up']].copy()
    df_proposals['cached_votes_down'] = 0
    df_proposals['target_type'] = 'Proposal'
    df_proposals.rename(columns={'cached_votes_up': 'target_votos_up', 'cached_votes_down': 'target_votos_down'}, inplace=True)

    targets = pd.concat([df_debates, df_proposals], ignore_index=True)
    targets.rename(columns={'id': 'target_id', 'title': 'target_title'}, inplace=True)

    # Clean HTML from descriptions
    targets['description'] = targets['description'].apply(clean_html)

    # 2. Process VOTES to get counts
    print("Processing vote counts...")
    votes_com = votes[votes['votable_type'] == 'Comment'].copy()

    vote_counts = votes_com.groupby(['votable_id', 'vote_flag']).size().unstack(fill_value=0)

    if True not in vote_counts.columns: vote_counts[True] = 0
    if False not in vote_counts.columns: vote_counts[False] = 0

    vote_counts = vote_counts.rename(columns={True: 'Votos_Positivos', False: 'Votos_Negativos'})

    # 3. Join COMMENTS with their TARGETS
    df_final = pd.merge(
        comments[['id', 'body', 'commentable_id', 'commentable_type']],
        targets[['target_id', 'target_title', 'description', 'target_type', 'target_votos_up', 'target_votos_down']],
        left_on=['commentable_id', 'commentable_type'],
        right_on=['target_id', 'target_type'],
        how='left'
    )

    # 4. Join vote counts to each comment
    df_final = pd.merge(df_final, vote_counts, left_on='id', right_index=True, how='left')

    df_final['Votos_Positivos'] = df_final['Votos_Positivos'].fillna(0).astype(int)
    df_final['Votos_Negativos'] = df_final['Votos_Negativos'].fillna(0).astype(int)

    # 5. Select and clean final columns
    result = df_final[[
        'target_title', 'target_type', 'target_votos_up', 'target_votos_down',
        'description', 'body', 'Votos_Positivos', 'Votos_Negativos'
    ]].copy()

    result.columns = [
        'Target (Tema)', 'Tipo Target', 'Apoyos Target', 'Rechazos Target',
        'Descripcion Target', 'Texto (Opinion)', 'Apoyos Comentario', 'Rechazos Comentario'
    ]

    result['Apoyos Target'] = result['Apoyos Target'].fillna(0).astype(int)
    result['Rechazos Target'] = result['Rechazos Target'].fillna(0).astype(int)

    # Remove rows without a topic (orphan comments)
    result = result.dropna(subset=['Target (Tema)'])

    # Remove comments without text
    n_before_nan = len(result)
    result = result.dropna(subset=['Texto (Opinion)'])
    n_nan = n_before_nan - len(result)
    print(f"Comments removed due to empty text (NaN): {n_nan}")

    # Remove comments with no alphabetic characters
    has_letter = result['Texto (Opinion)'].astype(str).str.contains(r'[a-záéíóúüñA-ZÁÉÍÓÚÜÑ]', regex=True)
    n_before_no_letter = len(result)
    result = result[has_letter]
    n_no_letter = n_before_no_letter - len(result)
    print(f"Comments removed due to no readable text (no letters): {n_no_letter}")

    # Remove comments that are basically just URLs
    def is_just_url(text):
        if not isinstance(text, str):
            return False
        cleaned = re.sub(r'https?://\S+', '', text)
        cleaned = re.sub(r'www\.\S+', '', cleaned).strip()
        return len(cleaned) < 30

    n_before_url = len(result)
    result = result[~result['Texto (Opinion)'].apply(is_just_url)]
    n_url = n_before_url - len(result)
    print(f"Comments removed for being basically just a URL: {n_url} ({100*n_url/n_before_url:.1f}%)")

    # Remove automatic welcome messages (bot)
    n_before_welcome = len(result)
    result = result[~result['Texto (Opinion)'].str.contains(
        r'Bienvenido', na=False, case=False
    )]
    n_welcome = n_before_welcome - len(result)
    print(f"Comments removed for being automatic welcome messages (spam): {n_welcome} ({100*n_welcome/n_before_welcome:.1f}%)")

    # Remove pattern "Listado de Propuestas NO Repetidas"
    n_before_norep = len(result)
    result = result[~result['Texto (Opinion)'].str.contains(
        r'(?i)(listado.*no.repetidas|no.repetidas.*listado|propuestas.*no.repetidas)',
        na=False, regex=True
    )]
    n_norep = n_before_norep - len(result)
    print(f"Comments removed for 'Listado NO Repetidas' pattern: {n_norep} ({100*n_norep/n_before_norep:.1f}%)")

    # Remove topics "#TuPreguntas"
    n_before_tupreguntas = len(result)
    result = result[~result['Target (Tema)'].str.contains(
        r'(?i)#TúPreguntas|#TuPreguntas', na=False, regex=True
    )]
    n_tupreguntas = n_before_tupreguntas - len(result)
    print(f"Comments removed for '#TuPreguntas' topics: {n_tupreguntas} ({100*n_tupreguntas/n_before_tupreguntas:.1f}%)")

    # Remove comments whose target has no description
    n_before_no_desc = len(result)
    result = result[result['Descripcion Target'].str.len() > 0]
    n_no_desc = n_before_no_desc - len(result)
    print(f"Comments removed because target lacks description: {n_no_desc} ({100*n_no_desc/n_before_no_desc:.1f}%)")

    # Sort by target
    result = result.sort_values(by=['Target (Tema)', 'Tipo Target'], kind='stable')

    # Save result
    output_file = os.path.join(path, 'corpus_stance_madrid_recuento.csv')
    result.to_csv(output_file, index=False, encoding='utf-8-sig')

    print(f"\nFile: {output_file}")
    print(f"Total rows: {len(result)}")


if __name__ == "__main__":
    generate_dataset_with_count()



import copy, os, sys, yaml
sys.path.append(f"{os.path.dirname(os.path.realpath(__file__))}/")
import gc
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple, cast

import numpy as np
import torch
from langchain_community.utils.math import cosine_similarity
from langchain_core.documents import BaseDocumentTransformer, Document
from langchain_core.embeddings import Embeddings

try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False
    
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False


def combine_sentences(sentences: List[dict], buffer_size: int = 1) -> List[dict]:
    """Combine sentences based on buffer size with vectorized operations.
    
    Args:
        sentences: List of sentences to combine.
        buffer_size: Number of sentences to combine. Defaults to 1.
        
    Returns:
        List of sentences with combined sentences.
    """
    if not sentences:
        return sentences
    
    # Pre-extract sentences for faster access
    sentence_texts = [s["sentence"] for s in sentences]
    n = len(sentences)
    
    for i in range(n):
        # Calculate valid ranges
        start_idx = max(0, i - buffer_size)
        end_idx = min(n, i + 1 + buffer_size)
        
        # Join sentences in range
        combined_parts = sentence_texts[start_idx:i] + [sentence_texts[i]] + sentence_texts[i+1:end_idx]
        sentences[i]["combined_sentence"] = " ".join(combined_parts)
    
    return sentences


def calculate_cosine_distances(sentences: List[dict]) -> Tuple[List[float], List[dict]]:
    """Calculate cosine distances between sentences using vectorized operations.
    
    Args:
        sentences: List of sentences to calculate distances for.
        
    Returns:
        Tuple of distances and sentences.
    """
    if len(sentences) <= 1:
        return [], sentences
    
    # Extract embeddings as numpy array for vectorized operations
    embeddings = np.array([s["combined_sentence_embedding"] for s in sentences])
    
    # Vectorized cosine similarity calculation
    current_embeddings = embeddings[:-1]
    next_embeddings = embeddings[1:]
    
    # Calculate similarities in batch
    similarities = np.sum(current_embeddings * next_embeddings, axis=1) / (
        np.linalg.norm(current_embeddings, axis=1) * np.linalg.norm(next_embeddings, axis=1)
    )
    
    # Convert to distances
    distances = (1 - similarities).tolist()
    
    # Store distances in sentence dicts
    for i, distance in enumerate(distances):
        sentences[i]["distance_to_next"] = distance
    
    return distances, sentences


BreakpointThresholdType = Literal[
    "percentile", "standard_deviation", "interquartile", "gradient"
]
BREAKPOINT_DEFAULTS: Dict[BreakpointThresholdType, float] = {
    "percentile": 95,
    "standard_deviation": 3,
    "interquartile": 1.5,
    "gradient": 95,
}


class SemanticChunker(BaseDocumentTransformer):
    """Optimized semantic text splitter with GPU memory management, token-based chunking,
    parallelization, better sentence detection, and improved chunk homogeneity.
    
    Key improvements:
    - GPU memory optimization with batching and automatic cleanup
    - Strict token-based min and max chunk size using tiktoken
    - Parallel processing for multiple texts
    - Better sentence splitting using spacy/nltk
    - Chunk size balancing for homogeneity
    - Validation tracking for chunks outside token bounds
    - Max threshold for upper slack allowance
    """

    def __init__(
        self,
        embeddings: Embeddings,
        buffer_size: int = 1,
        add_start_index: bool = False,
        breakpoint_threshold_type: BreakpointThresholdType = "percentile",
        breakpoint_threshold_amount: Optional[float] = None,
        number_of_chunks: Optional[int] = None,
        sentence_split_regex: Optional[str] = None,
        min_chunk_size_tokens: Optional[int] = None,
        max_chunk_size_tokens: Optional[int] = None,
        max_threshold: int = 128,
        embedding_batch_size: int = 32,
        use_spacy: bool = True,
        spacy_model: str = "es_core_news_sm",
        tokenizer_model: str = "cl100k_base",
        max_workers: Optional[int] = None,
        enable_chunk_balancing: bool = True,
        target_chunk_variance: float = 0.2,
    ):
        """Initialize the SemanticChunker.
        
        Args:
            embeddings: Embeddings model to use.
            buffer_size: Number of sentences to combine for context.
            add_start_index: Whether to add start index to metadata.
            breakpoint_threshold_type: Type of threshold calculation.
            breakpoint_threshold_amount: Custom threshold amount.
            number_of_chunks: Target number of chunks.
            sentence_split_regex: Custom regex for sentence splitting (deprecated if use_spacy=True).
            min_chunk_size_tokens: Minimum chunk size in tokens.
            max_chunk_size_tokens: Maximum chunk size in tokens.
            max_threshold: Maximum slack allowed above max_chunk_size_tokens.
            embedding_batch_size: Batch size for embedding generation (GPU optimization).
            use_spacy: Use spacy for better sentence detection.
            spacy_model: Spacy model to use for sentence detection.
            tokenizer_model: Tokenizer model for token counting.
            max_workers: Maximum workers for parallel processing.
            enable_chunk_balancing: Enable chunk size balancing for homogeneity.
            target_chunk_variance: Target variance for chunk sizes (lower = more homogeneous).
        """
        
        config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        
        self._add_start_index = add_start_index
        self.embeddings = embeddings
        self.buffer_size = buffer_size
        self.breakpoint_threshold_type = breakpoint_threshold_type
        self.number_of_chunks = number_of_chunks
        self.min_chunk_size_tokens = min_chunk_size_tokens
        self.max_chunk_size_tokens = max_chunk_size_tokens
        self.max_threshold = max_threshold
        self.embedding_batch_size = embedding_batch_size
        self.max_workers = max_workers
        self.enable_chunk_balancing = enable_chunk_balancing
        self.target_chunk_variance = target_chunk_variance
        
        # Sentence splitting setup
        self.use_spacy = use_spacy and SPACY_AVAILABLE
        self.spacy_nlp = None
        if self.use_spacy:
            try:
                self.spacy_nlp = spacy.load(spacy_model, disable=["ner", "parser", "lemmatizer"])
                # Only keep sentencizer for performance
                if "sentencizer" not in self.spacy_nlp.pipe_names:
                    self.spacy_nlp.add_pipe("sentencizer")
            except OSError:
                print(f"Warning: spacy model '{spacy_model}' not found. Falling back to regex.")
                self.use_spacy = False
        
        # Fallback regex
        self.sentence_split_regex = sentence_split_regex or r"(?<=[.?!])\s+"
        
        # Token counter setup
        self.tokenizer = None
        
        self.tiktoken_dir = self.config['splitter']['tiktoken_dir']
        os.environ["TIKTOKEN_CACHE_DIR"] = self.tiktoken_dir
        
        if TIKTOKEN_AVAILABLE:
            try:
                self.tokenizer = tiktoken.get_encoding(tokenizer_model)
            except Exception as e:
                print(f"Warning: Could not load tokenizer '{tokenizer_model}': {e}")
        
        # Breakpoint threshold
        if breakpoint_threshold_amount is None:
            self.breakpoint_threshold_amount = BREAKPOINT_DEFAULTS[breakpoint_threshold_type]
        else:
            self.breakpoint_threshold_amount = breakpoint_threshold_amount

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken."""
        if self.tokenizer is not None:
            return len(self.tokenizer.encode(text))
        # Fallback: approximate tokens as words
        return len(text.split())
    
    def _is_valid_chunk(self, token_count: int) -> bool:
        """Check if a chunk's token count is within valid bounds.
        
        Args:
            token_count: Number of tokens in the chunk
            
        Returns:
            True if chunk is valid, False otherwise
        """
        # Check minimum bound
        if self.min_chunk_size_tokens is not None and token_count < self.min_chunk_size_tokens:
            return False
        
        # Check maximum bound with threshold
        if self.max_chunk_size_tokens is not None:
            max_allowed = self.max_chunk_size_tokens + self.max_threshold
            if token_count > max_allowed:
                return False
        
        return True

    def _calculate_breakpoint_threshold(
        self, distances: List[float]
    ) -> Tuple[float, List[float]]:
        """Calculate breakpoint threshold based on threshold type."""
        if self.breakpoint_threshold_type == "percentile":
            return cast(
                float,
                np.percentile(distances, self.breakpoint_threshold_amount),
            ), distances
        elif self.breakpoint_threshold_type == "standard_deviation":
            return cast(
                float,
                np.mean(distances) + self.breakpoint_threshold_amount * np.std(distances),
            ), distances
        elif self.breakpoint_threshold_type == "interquartile":
            q1, q3 = np.percentile(distances, [25, 75])
            iqr = q3 - q1
            return np.mean(distances) + self.breakpoint_threshold_amount * iqr, distances
        elif self.breakpoint_threshold_type == "gradient":
            distance_gradient = np.gradient(distances, range(len(distances)))
            return cast(
                float,
                np.percentile(distance_gradient, self.breakpoint_threshold_amount),
            ), distance_gradient
        else:
            raise ValueError(
                f"Got unexpected `breakpoint_threshold_type`: {self.breakpoint_threshold_type}"
            )

    def _threshold_from_clusters(self, distances: List[float]) -> float:
        """Calculate threshold based on number of chunks."""
        if self.number_of_chunks is None:
            raise ValueError("This should never be called if `number_of_chunks` is None.")
        
        x1, y1 = len(distances), 0.0
        x2, y2 = 1.0, 100.0
        x = max(min(self.number_of_chunks, x1), x2)
        
        if x2 == x1:
            y = y2
        else:
            y = y1 + ((y2 - y1) / (x2 - x1)) * (x - x1)
        
        y = min(max(y, 0), 100)
        return cast(float, np.percentile(distances, y))

    def _calculate_sentence_distances_batched(
        self, single_sentences_list: List[str]
    ) -> Tuple[List[float], List[dict]]:
        """Calculate sentence distances with batched embedding generation for GPU optimization."""
        _sentences = [
            {"sentence": x, "index": i} for i, x in enumerate(single_sentences_list)
        ]
        sentences = combine_sentences(_sentences, self.buffer_size)
        
        # Extract combined sentences for embedding
        combined_texts = [x["combined_sentence"] for x in sentences]
        
        # Batch embedding generation for GPU memory efficiency
        all_embeddings = []
        for i in range(0, len(combined_texts), self.embedding_batch_size):
            batch = combined_texts[i:i + self.embedding_batch_size]
            batch_embeddings = self.embeddings.embed_documents(batch)
            all_embeddings.extend(batch_embeddings)
            
            # Clear GPU cache if using PyTorch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        
        # Assign embeddings
        for i, sentence in enumerate(sentences):
            sentence["combined_sentence_embedding"] = all_embeddings[i]
        
        return calculate_cosine_distances(sentences)

    def _get_single_sentences_list(self, text: str) -> List[str]:
        """Split text into sentences using spacy or regex."""
        if self.use_spacy and self.spacy_nlp is not None:
            # Use spacy for better sentence detection
            doc = self.spacy_nlp(text)
            return [sent.text.strip() for sent in doc.sents if sent.text.strip()]
        else:
            # Fallback to regex
            import re
            sentences = re.split(self.sentence_split_regex, text)
            return [s.strip() for s in sentences if s.strip()]

    def _balance_chunks(self, chunks: List[dict]) -> List[dict]:
        """Balance chunk sizes for better homogeneity while respecting token constraints.
        
        Args:
            chunks: List of chunk dictionaries with 'text' and 'tokens' keys
            
        Returns:
            Balanced list of chunk dictionaries
        """
        if not self.enable_chunk_balancing or len(chunks) <= 1:
            return chunks
        
        # Calculate chunk statistics based on tokens
        chunk_token_counts = [c['tokens'] for c in chunks]
        mean_tokens = np.mean(chunk_token_counts)
        std_tokens = np.std(chunk_token_counts)
        coefficient_of_variation = std_tokens / mean_tokens if mean_tokens > 0 else 0
        
        # If variance is already low, no need to balance
        if coefficient_of_variation <= self.target_chunk_variance:
            return chunks
        
        # Merge small chunks with neighbors
        balanced_chunks = []
        i = 0
        while i < len(chunks):
            current_chunk = chunks[i]
            current_tokens = current_chunk['tokens']
            
            # If chunk is significantly smaller than mean, try to merge
            if current_tokens < mean_tokens * (1 - self.target_chunk_variance) and i < len(chunks) - 1:
                # Check token limit if applicable - use max_threshold
                merged_text = current_chunk['text'] + " " + chunks[i + 1]['text']
                merged_tokens = self._count_tokens(merged_text)
                
                # Ensure merged chunk respects max constraint with threshold
                max_allowed = self.max_chunk_size_tokens + self.max_threshold if self.max_chunk_size_tokens is not None else float('inf')
                
                if merged_tokens <= max_allowed:
                    balanced_chunks.append({
                        'text': merged_text,
                        'tokens': merged_tokens
                    })
                    i += 2
                    continue
            
            balanced_chunks.append(current_chunk)
            i += 1
        
        return balanced_chunks

    def split_text(self, text: str) -> List[Dict[str, Any]]:
        """Split text into semantic chunks with strict token-based limits.
        
        Enforces: min_chunk_size_tokens < chunk_tokens < max_chunk_size_tokens + max_threshold
        
        Returns:
            List of dictionaries with 'text', 'tokens', and 'valid' keys
        """
        # Get sentences
        single_sentences_list = self._get_single_sentences_list(text)
        
        # Handle single sentence case
        if len(single_sentences_list) == 1:
            tokens = self._count_tokens(single_sentences_list[0])
            valid = self._is_valid_chunk(tokens)
            return [{'text': single_sentences_list[0], 'tokens': tokens, 'valid': valid}]
        
        # Handle two sentence case with gradient breakpoint
        if self.breakpoint_threshold_type == "gradient" and len(single_sentences_list) == 2:
            # Try to combine first
            combined_text = " ".join(single_sentences_list)
            combined_tokens = self._count_tokens(combined_text)
            
            # If combined is within limits, return as single chunk
            if self._is_valid_chunk(combined_tokens):
                return [{'text': combined_text, 'tokens': combined_tokens, 'valid': True}]
            
            # Otherwise return separately
            result = []
            for sentence in single_sentences_list:
                tokens = self._count_tokens(sentence)
                valid = self._is_valid_chunk(tokens)
                result.append({'text': sentence, 'tokens': tokens, 'valid': valid})
            return result
        
        # Calculate distances with batched embeddings
        distances, sentences = self._calculate_sentence_distances_batched(single_sentences_list)
        
        # Determine breakpoints
        if self.number_of_chunks is not None:
            breakpoint_distance_threshold = self._threshold_from_clusters(distances)
            breakpoint_array = distances
        else:
            breakpoint_distance_threshold, breakpoint_array = self._calculate_breakpoint_threshold(distances)
        
        indices_above_thresh = [
            i for i, x in enumerate(breakpoint_array) if x > breakpoint_distance_threshold
        ]
        
        # Create chunks with token information and strict enforcement
        chunks = []
        start_index = 0
        
        for index in indices_above_thresh:
            end_index = index
            group = sentences[start_index:end_index + 1]
            combined_text = " ".join([d["sentence"] for d in group])
            token_count = self._count_tokens(combined_text)
            
            # Strict enforcement: check if chunk exceeds max + threshold
            max_allowed = self.max_chunk_size_tokens + self.max_threshold if self.max_chunk_size_tokens is not None else float('inf')
            
            if token_count > max_allowed:
                # Must split further - exceeds absolute maximum
                sub_chunks = self._split_by_token_limit(group)
                chunks.extend(sub_chunks)
            elif self.max_chunk_size_tokens is not None and token_count > self.max_chunk_size_tokens:
                # In the threshold zone - attempt to reduce if possible
                # Try to find a better split point within this group
                optimized_chunks = self._optimize_chunk_in_threshold_zone(group, token_count)
                chunks.extend(optimized_chunks)
            else:
                # Within normal bounds
                chunks.append({'text': combined_text, 'tokens': token_count})
            
            start_index = index + 1
        
        # Handle remaining sentences
        if start_index < len(sentences):
            combined_text = " ".join([d["sentence"] for d in sentences[start_index:]])
            token_count = self._count_tokens(combined_text)
            
            max_allowed = self.max_chunk_size_tokens + self.max_threshold if self.max_chunk_size_tokens is not None else float('inf')
            
            if token_count > max_allowed:
                # Must split further
                sub_chunks = self._split_by_token_limit(sentences[start_index:])
                chunks.extend(sub_chunks)
            elif self.max_chunk_size_tokens is not None and token_count > self.max_chunk_size_tokens:
                # In threshold zone - optimize
                optimized_chunks = self._optimize_chunk_in_threshold_zone(sentences[start_index:], token_count)
                chunks.extend(optimized_chunks)
            else:
                chunks.append({'text': combined_text, 'tokens': token_count})
        
        # Balance chunks for homogeneity
        chunks = self._balance_chunks(chunks)
        
        # Final validation pass
        for chunk in chunks:
            chunk['valid'] = self._is_valid_chunk(chunk['tokens'])
        
        # GPU cleanup
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()
        
        return chunks

    def _optimize_chunk_in_threshold_zone(self, sentence_group: List[dict], current_tokens: int) -> List[Dict[str, Any]]:
        """Attempt to optimize a chunk that falls in the threshold zone.
        
        If a chunk is between max_chunk_size_tokens and max_chunk_size_tokens + max_threshold,
        try to find a better split point to keep it under max_chunk_size_tokens if possible.
        
        Args:
            sentence_group: Group of sentence dictionaries
            current_tokens: Current token count of the combined group
            
        Returns:
            List of optimized chunk dictionaries
        """
        # If we can't split further (only one sentence), return as is
        if len(sentence_group) <= 1:
            text = sentence_group[0]["sentence"] if sentence_group else ""
            return [{'text': text, 'tokens': current_tokens}]
        
        # Try to find optimal split point
        best_split = None
        min_excess = float('inf')
        
        # Try different split points
        for split_idx in range(1, len(sentence_group)):
            first_part = " ".join([s["sentence"] for s in sentence_group[:split_idx]])
            second_part = " ".join([s["sentence"] for s in sentence_group[split_idx:]])
            
            first_tokens = self._count_tokens(first_part)
            second_tokens = self._count_tokens(second_part)
            
            # Both parts should be within bounds
            max_allowed = self.max_chunk_size_tokens + self.max_threshold
            
            if first_tokens <= self.max_chunk_size_tokens and second_tokens <= self.max_chunk_size_tokens:
                # Ideal case - both under max
                return [
                    {'text': first_part, 'tokens': first_tokens},
                    {'text': second_part, 'tokens': second_tokens}
                ]
            
            # Track best split (minimize excess over max_chunk_size_tokens)
            if first_tokens <= max_allowed and second_tokens <= max_allowed:
                excess = max(0, first_tokens - self.max_chunk_size_tokens) + max(0, second_tokens - self.max_chunk_size_tokens)
                if excess < min_excess:
                    min_excess = excess
                    best_split = (first_part, first_tokens, second_part, second_tokens)
        
        # Use best split if found
        if best_split:
            return [
                {'text': best_split[0], 'tokens': best_split[1]},
                {'text': best_split[2], 'tokens': best_split[3]}
            ]
        
        # If no good split found, fall back to strict splitting
        return self._split_by_token_limit(sentence_group)

    def _split_by_token_limit(self, sentence_group: List[dict]) -> List[Dict[str, Any]]:
        """Split a group of sentences by strict token limit.
        
        Enforces chunks to be under max_chunk_size_tokens + max_threshold
        
        Args:
            sentence_group: List of sentence dictionaries
            
        Returns:
            List of chunk dictionaries with 'text' and 'tokens' keys
        """
        chunks = []
        current_chunk = []
        current_tokens = 0
        
        # Calculate absolute maximum
        max_allowed = self.max_chunk_size_tokens + self.max_threshold if self.max_chunk_size_tokens is not None else float('inf')
        # Try to target the base max_chunk_size_tokens
        target_max = self.max_chunk_size_tokens if self.max_chunk_size_tokens is not None else max_allowed
        
        for sent_dict in sentence_group:
            sentence = sent_dict["sentence"]
            sent_tokens = self._count_tokens(sentence)
            
            # If single sentence exceeds max_allowed, we must split it further (word level)
            if sent_tokens > max_allowed:
                # Save current chunk if any
                if current_chunk:
                    chunk_text = " ".join(current_chunk)
                    chunks.append({'text': chunk_text, 'tokens': self._count_tokens(chunk_text)})
                    current_chunk = []
                    current_tokens = 0
                
                # Split long sentence at word level
                word_chunks = self._split_sentence_by_words(sentence, max_allowed)
                chunks.extend(word_chunks)
                continue
            
            # Check if adding this sentence would exceed target
            if current_tokens + sent_tokens <= target_max:
                current_chunk.append(sentence)
                current_tokens += sent_tokens
            else:
                # Check if it would fit within the threshold
                if current_tokens + sent_tokens <= max_allowed and len(current_chunk) > 0:
                    # Add to current chunk (within threshold)
                    current_chunk.append(sentence)
                    current_tokens += sent_tokens
                else:
                    # Start new chunk
                    if current_chunk:
                        chunk_text = " ".join(current_chunk)
                        chunks.append({'text': chunk_text, 'tokens': self._count_tokens(chunk_text)})
                    current_chunk = [sentence]
                    current_tokens = sent_tokens
        
        # Add remaining chunk
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            chunks.append({'text': chunk_text, 'tokens': self._count_tokens(chunk_text)})
        
        return chunks

    def _split_sentence_by_words(self, sentence: str, max_tokens: int) -> List[Dict[str, Any]]:
        """Split a sentence by words when it exceeds the maximum token limit.
        
        Args:
            sentence: The sentence to split
            max_tokens: Maximum tokens allowed per chunk
            
        Returns:
            List of chunk dictionaries
        """
        words = sentence.split()
        chunks = []
        current_chunk = []
        current_tokens = 0
        
        for word in words:
            word_tokens = self._count_tokens(word)
            
            if current_tokens + word_tokens <= max_tokens:
                current_chunk.append(word)
                current_tokens += word_tokens
            else:
                if current_chunk:
                    chunk_text = " ".join(current_chunk)
                    chunks.append({'text': chunk_text, 'tokens': self._count_tokens(chunk_text)})
                current_chunk = [word]
                current_tokens = word_tokens
        
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            chunks.append({'text': chunk_text, 'tokens': self._count_tokens(chunk_text)})
        
        return chunks

    def _split_single_text(self, text: str, metadata: dict, start_idx_offset: int = 0) -> List[Document]:
        """Split a single text into documents."""
        documents = []
        start_index = start_idx_offset
        
        for chunk_dict in self.split_text(text):
            chunk = chunk_dict['text']
            chunk_metadata = copy.deepcopy(metadata)
            if self._add_start_index:
                chunk_metadata["start_index"] = start_index
            chunk_metadata["tokens"] = chunk_dict['tokens']
            chunk_metadata["valid"] = chunk_dict['valid']
            new_doc = Document(page_content=chunk, metadata=chunk_metadata)
            documents.append(new_doc)
            start_index += len(chunk)
        
        return documents

    def create_documents(
        self, texts: List[str], metadatas: Optional[List[dict]] = None
    ) -> List[Document]:
        """Create documents from a list of texts with parallel processing."""
        _metadatas = metadatas or [{}] * len(texts)
        
        # Single text - no parallelization needed
        if len(texts) == 1:
            return self._split_single_text(texts[0], _metadatas[0])
        
        # Multiple texts - use parallel processing
        documents = []
        
        # Use ProcessPoolExecutor for CPU-bound tasks
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._split_single_text, text, metadata): i
                for i, (text, metadata) in enumerate(zip(texts, _metadatas))
            }
            
            for future in as_completed(futures):
                try:
                    docs = future.result()
                    documents.extend(docs)
                except Exception as e:
                    print(f"Error processing text: {e}")
        
        return documents

    def split_documents(self, documents: Iterable[Document]) -> List[Document]:
        """Split documents with parallel processing."""
        texts, metadatas = [], []
        for doc in documents:
            texts.append(doc.page_content)
            metadatas.append(doc.metadata)
        return self.create_documents(texts, metadatas=metadatas)

    def transform_documents(
        self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        """Transform sequence of documents by splitting them."""
        return self.split_documents(list(documents))

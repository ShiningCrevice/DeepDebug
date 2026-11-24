"""Offline BM25 search over a fixed, packaged corpus of curated summaries."""

import re
from collections import Counter
from math import log1p
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from deepdebug.agent.actions import SearchDocsArguments
from deepdebug.agent.schemas import Category, Contract, Text, unique_ids
from deepdebug.security.paths import AuthorizedRoot

CORPUS_ROOT = Path(__file__).absolute().parent.parent / "knowledge"
BM25_K1 = 1.2
BM25_B = 0.75


class Document(Contract):
    document_id: Annotated[str, Field(pattern=r"^D[0-9]{3}$")]
    title: Annotated[Text, Field(max_length=200)]
    category: Category
    url: HttpUrl
    applicable_version: Annotated[Text, Field(max_length=100)]
    collected_at: AwareDatetime
    content_kind: Literal["curated_summary"]
    keywords: list[Annotated[Text, Field(max_length=100)]] = Field(min_length=1, max_length=20)
    excerpt: Annotated[Text, Field(max_length=3000)]


class Corpus(Contract):
    schema_version: Literal["1"]
    documents: list[Document] = Field(min_length=1, max_length=25)

    @model_validator(mode="after")
    def unique_documents(self) -> "Corpus":
        unique_ids([doc.document_id for doc in self.documents], "document IDs")
        return self


def load_corpus() -> Corpus:
    with AuthorizedRoot(CORPUS_ROOT, allow_hidden_root=True) as root:
        return Corpus.model_validate_json(root.read("documents.json"))


def _terms(text: str) -> list[str]:
    """Preserve term frequency, dotted APIs and their suffixes, and Chinese bigrams."""
    terms = []
    for identifier in re.findall(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*", text.casefold()):
        parts = identifier.split(".")
        # torch.nn.Linear also matches nn.Linear / Linear, without adding torch / nn.
        terms.extend(".".join(parts[index:]) for index in range(len(parts)))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        terms.extend(run[i : i + 2] for i in range(max(1, len(run) - 1)))
    return terms


class DocumentIndex:
    def __init__(self) -> None:
        # This is the only file read. Queries never select a path or a URL to fetch.
        corpus = load_corpus()
        self._documents = tuple(corpus.documents)
        self._frequencies = [
            Counter(_terms(" ".join([doc.title, *doc.keywords, doc.excerpt])))
            for doc in self._documents
        ]
        lengths = [sum(counts.values()) for counts in self._frequencies]
        average_length = sum(lengths) / len(lengths)
        # A punctuation-only corpus has no terms to score, but remains a valid empty search.
        self._normalizers = [
            BM25_K1 * (1 - BM25_B + BM25_B * length / (average_length or 1)) for length in lengths
        ]
        document_frequency = Counter(term for counts in self._frequencies for term in counts)
        self._idf = {
            term: log1p((len(self._documents) - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def search(self, arguments: SearchDocsArguments) -> tuple[list[dict], int]:
        args = SearchDocsArguments.model_validate(arguments)
        # Query duplicates do not boost scores; sorting keeps floating-point sums deterministic.
        query = sorted(set(_terms(args.query)))
        matches = []
        for doc, counts, normalizer in zip(
            self._documents, self._frequencies, self._normalizers, strict=True
        ):
            if args.category is not None and doc.category != args.category:
                continue
            score = sum(
                self._idf[term] * counts[term] * (BM25_K1 + 1) / (counts[term] + normalizer)
                for term in query
                if term in counts
            )
            if score > 0:
                matches.append({**doc.model_dump(mode="json"), "score": score})
        matches.sort(key=lambda hit: (-hit["score"], hit["document_id"]))
        return matches[: args.max_results], len(matches)

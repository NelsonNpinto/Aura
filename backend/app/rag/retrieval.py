import hashlib
import io
import re
from functools import lru_cache

from fastapi import HTTPException
from rank_bm25 import BM25Okapi
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.models.platform import Chunk, Document
from app.monitoring.telemetry import observation


@lru_cache(maxsize=1)
def embedder():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise HTTPException(
            503, "Embedding dependencies unavailable. Install the rag extra."
        ) from exc
    return SentenceTransformer(get_settings().embedding_model, device="cpu")


def extract(name, content):
    suffix = name.lower().rsplit(".", 1)[-1]
    if suffix == "pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > 200:
                raise HTTPException(413, "PDF limited to 200 pages")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                422, "Could not extract PDF text; scanned PDFs require OCR"
            ) from exc
    elif suffix in ("txt", "md"):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(422, "Text files must use UTF-8") from exc
    else:
        raise HTTPException(415, "Supported formats: PDF, TXT, Markdown")
    text = re.sub(r"[ \t]+", " ", text.replace("\x00", "")).strip()
    if not text:
        raise HTTPException(422, "Document contains no extractable text")
    if len(text) > 1_000_000:
        raise HTTPException(413, "Extracted text exceeds one million characters")
    return text


def ingest(db, name, content):
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    digest = hashlib.sha256(content).hexdigest()
    existing = db.scalar(select(Document).where(Document.sha256 == digest))
    if existing:
        return existing, True
    text = extract(name, content)
    parts = RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=120).split_text(text)
    doc = Document(name=name[:250], sha256=digest, content=text, chunk_count=len(parts))
    db.add(doc)
    db.flush()
    db.add_all([Chunk(document_id=doc.id, position=i, content=s) for i, s in enumerate(parts)])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(Document).where(Document.sha256 == digest)), True
    return doc, False


def index_document(db, doc):
    chunks = list(
        db.scalars(select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.position))
    )
    with observation("embedding"):
        vectors = embedder().encode([c.content for c in chunks], normalize_embeddings=True).tolist()
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector
    doc.embedding_model = get_settings().embedding_model
    db.commit()
    return {
        "document_id": doc.id,
        "indexed_chunks": len(chunks),
        "embedding_model": doc.embedding_model,
    }


def tokens(value):
    return re.findall(r"\w+", value.casefold())


def retrieve(db, payload):
    with observation("retrieval"):
        query = select(Chunk, Document.name).join(Document, Document.id == Chunk.document_id)
        if payload.document_ids:
            query = query.where(Document.id.in_(payload.document_ids))
        rows = list(db.execute(query.order_by(Chunk.id)).all())
        if not rows:
            return []
        if len(rows) > 10000:
            raise HTTPException(
                422, "Keyword retrieval limited to 10,000 chunks in this local edition"
            )
        scores = {}
        if payload.strategy in ("bm25", "hybrid"):
            terms = tokens(payload.question)
            corpus = [tokens(c.content) or [""] for c, _ in rows]
            raw = BM25Okapi(corpus, epsilon=0.25).get_scores(terms)
            # BM25 can be zero/negative in tiny corpora. Require literal term overlap,
            # then use BM25 rank rather than treating that as probability.
            matches = [
                (i, float(raw[i]))
                for i, terms_in_doc in enumerate(corpus)
                if set(terms) & set(terms_in_doc)
            ]
            for rank, (i, _) in enumerate(sorted(matches, key=lambda t: (-t[1], t[0]))):
                scores[rows[i][0].id] = 1 / (60 + rank + 1)
        if payload.strategy in ("vector", "hybrid"):
            indexed = [(c, name) for c, name in rows if c.embedding is not None]
            if not indexed:
                raise HTTPException(
                    422, "No indexed chunks. Index a document or select BM25 retrieval."
                )
            vector = embedder().encode(payload.question, normalize_embeddings=True).tolist()
            if db.get_bind().dialect.name == "postgresql":
                vector_query = (
                    query.where(Chunk.embedding.is_not(None))
                    .order_by(None)
                    .order_by(Chunk.embedding.cosine_distance(vector))
                    .limit(50)
                )
                ordered = [c.id for c, _ in db.execute(vector_query)]
            else:
                ordered = [
                    c.id
                    for c, _ in sorted(
                        indexed,
                        key=lambda item: (
                            -sum(a * b for a, b in zip(item[0].embedding, vector, strict=True))
                        ),
                    )[:50]
                ]
            for rank, ident in enumerate(ordered):
                scores[ident] = scores.get(ident, 0) + 1 / (60 + rank + 1)
        selected = sorted(
            [(c, name) for c, name in rows if c.id in scores],
            key=lambda pair: (-scores[pair[0].id], pair[0].id),
        )[: max(payload.top_k, 10 if payload.rerank else payload.top_k)]
        if payload.rerank and selected:
            try:
                from sentence_transformers import CrossEncoder

                reranker = CrossEncoder(get_settings().reranker_model, device="cpu")
                ranks = reranker.predict([(payload.question, c.content) for c, _ in selected])
                selected = [
                    pair
                    for _, pair in sorted(
                        zip(ranks, selected, strict=True), key=lambda p: -float(p[0])
                    )
                ]
            except ImportError as exc:
                raise HTTPException(503, "Reranking requires the rag extra") from exc
        return [
            {
                "id": c.id,
                "document_id": c.document_id,
                "document": name,
                "position": c.position,
                "content": c.content,
                "rank_score": scores[c.id],
            }
            for c, name in selected[: payload.top_k]
        ]


def remove_document(db, doc):
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    db.delete(doc)
    db.commit()

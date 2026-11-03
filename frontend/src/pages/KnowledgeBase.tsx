import { useState } from "react";
import { FileText, Trash2, Upload } from "lucide-react";
import {
  Badge,
  Empty,
  ErrorState,
  Loading,
  PageHeading,
  PanelTitle,
} from "../components/common";
import {
  ActionButton,
  Inspect,
  ModelPicker,
  MutationError,
  Note,
} from "../components/platform";
import { Button } from "../components/ui/button";
import { useApi } from "../hooks/useApi";
import { useMutation } from "../hooks/useMutation";
import { api } from "../services/api";
import type { KnowledgeDocument, Source } from "../types/platform";
import type { Trace } from "../types";
export function KnowledgeBase() {
  const docs = useApi<KnowledgeDocument[]>("/documents"),
    upload = useMutation<KnowledgeDocument>(),
    search = useMutation<Source[]>(),
    ask = useMutation<{
      trace: Trace;
      sources: Source[];
      invalid_citations: number[];
    }>(),
    inspect =
      useMutation<{ id: string; content: string; position: number }[]>(),
    remove = useMutation<unknown>(),
    index = useMutation<unknown>();
  const [file, setFile] = useState<File | null>(null),
    [embedding, setEmbedding] = useState(true),
    [question, setQuestion] = useState(""),
    [strategy, setStrategy] = useState("hybrid"),
    [topK, setTopK] = useState(4),
    [model, setModel] = useState(""),
    [rerank, setRerank] = useState(false),
    [selected, setSelected] = useState<string[]>([]);
  const request = {
    question,
    strategy,
    top_k: topK,
    document_ids: selected,
    rerank,
  };
  return (
    <>
      <PageHeading
        eyebrow="GROUNDED ANSWERS"
        title="Knowledge Base"
        description="Upload documents, inspect retrieval, and answer questions with citations."
      />
      <div className="platform-grid">
        <section className="panel">
          <PanelTitle
            title="Add knowledge"
            description="PDF, UTF-8 text, or Markdown · up to 10 MB."
          />
          <form
            className="form-body"
            onSubmit={(e) => {
              e.preventDefault();
              if (!file) return;
              void upload.execute(
                async () => {
                  const data = new FormData();
                  data.append("file", file);
                  return (
                    await api.post(`/documents?index=${embedding}`, data, {
                      timeout: 900000,
                    })
                  ).data;
                },
                "Document processed",
                docs.refresh,
              );
            }}
          >
            <label>
              Document
              <input
                type="file"
                accept=".pdf,.txt,.md"
                required
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <label className="inline-checkbox">
              <input
                type="checkbox"
                checked={embedding}
                onChange={(e) => setEmbedding(e.target.checked)}
              />
              Create local embeddings
            </label>
            <small className="muted-text">
              The first embedding operation downloads a Sentence Transformer
              model. Disable for keyword-only retrieval.
            </small>
            <MutationError error={upload.error} />
            <ActionButton busy={upload.busy}>
              <Upload size={15} />
              Upload document
            </ActionButton>
          </form>
        </section>
        <Note title="Retrieval before generation">
          BM25 matches keywords. Vector search matches meaning using local
          embeddings. Hybrid search combines both rankings. Inspect retrieved
          chunks before trusting an answer. Citations identify sources; they do
          not prove that every claim is supported.
        </Note>
      </div>
      <section className="panel section-gap">
        <PanelTitle
          title="Documents"
          description="Select documents to scope your search; leave all unselected to search everything."
        />
        {docs.error ? (
          <ErrorState message={docs.error} retry={docs.refresh} />
        ) : docs.loading ? (
          <Loading />
        ) : docs.data?.length ? (
          <div className="record-list">
            {docs.data.map((d) => (
              <div key={d.id} className="document-row">
                <label className="inline-checkbox">
                  <input
                    type="checkbox"
                    checked={selected.includes(d.id)}
                    onChange={() =>
                      setSelected((s) =>
                        s.includes(d.id)
                          ? s.filter((v) => v !== d.id)
                          : [...s, d.id],
                      )
                    }
                  />
                  <FileText size={17} />
                  <strong>{d.name}</strong>
                </label>
                <span>{d.chunk_count} chunks</span>
                <Badge good={!!d.embedding_model}>
                  {d.embedding_model ? "Indexed" : "Keyword only"}
                </Badge>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    void inspect.execute(
                      async () =>
                        (await api.get(`/documents/${d.id}/chunks`)).data,
                      "Chunks loaded",
                    )
                  }
                >
                  Chunks
                </Button>
                {!d.embedding_model && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={index.busy}
                    onClick={() =>
                      void index.execute(
                        async () =>
                          (
                            await api.post(
                              `/documents/${d.id}/index`,
                              {},
                              { timeout: 900000 },
                            )
                          ).data,
                        "Embeddings created",
                        docs.refresh,
                      )
                    }
                  >
                    Index
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Delete ${d.name}`}
                  disabled={remove.busy}
                  onClick={() =>
                    void remove.execute(
                      async () => {
                        await api.delete(`/documents/${d.id}`);
                        setSelected((s) => s.filter((v) => v !== d.id));
                        return null;
                      },
                      "Document deleted",
                      docs.refresh,
                    )
                  }
                >
                  <Trash2 size={15} />
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <Empty title="Your knowledge starts here">
            Upload a document to create searchable chunks.
          </Empty>
        )}
        <MutationError error={remove.error || index.error || inspect.error} />
      </section>
      {inspect.result && (
        <section className="panel section-gap">
          <PanelTitle title="Extracted chunks" />
          <div className="chunk-list">
            {inspect.result.map((c) => (
              <div className="source-card" key={c.id}>
                <Badge>Chunk {c.position + 1}</Badge>
                <pre>{c.content}</pre>
              </div>
            ))}
          </div>
        </section>
      )}
      <div className="platform-grid section-gap">
        <section className="panel">
          <PanelTitle title="Search & ask" />
          <form
            className="form-body"
            onSubmit={(e) => {
              e.preventDefault();
              void search.execute(
                async () => (await api.post("/knowledge/search", request)).data,
                "Retrieval complete",
              );
            }}
          >
            <label>
              Question
              <textarea
                rows={4}
                required
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
              />
            </label>
            <div className="form-row">
              <label>
                Retrieval
                <select
                  value={strategy}
                  onChange={(e) => setStrategy(e.target.value)}
                >
                  <option value="hybrid">Hybrid</option>
                  <option value="bm25">BM25 keywords</option>
                  <option value="vector">Vector similarity</option>
                </select>
              </label>
              <label>
                Chunks to retrieve
                <input
                  type="number"
                  min="1"
                  max="10"
                  required
                  value={topK}
                  onChange={(e) => setTopK(+e.target.value)}
                />
              </label>
            </div>
            <label className="inline-checkbox">
              <input
                type="checkbox"
                checked={rerank}
                onChange={(e) => setRerank(e.target.checked)}
              />
              Rerank with a local CrossEncoder
            </label>
            <MutationError error={search.error} />
            <ActionButton busy={search.busy}>Inspect retrieval</ActionButton>
            <ModelPicker required={false} value={model} onChange={setModel} />
            <MutationError error={ask.error} />
            <Button
              type="button"
              disabled={ask.busy || !model || !question.trim()}
              onClick={() =>
                void ask.execute(
                  async () =>
                    (
                      await api.post(
                        "/knowledge/ask",
                        { ...request, model },
                        { timeout: 900000 },
                      )
                    ).data,
                  "Answer and trace saved",
                )
              }
            >
              {ask.busy ? "Generating…" : "Generate a cited answer"}
            </Button>
          </form>
        </section>
        <section className="panel">
          <PanelTitle title="Answer & evidence" />
          <div className="form-body">
            {ask.result ? (
              <>
                <pre>{ask.result.trace.response}</pre>
                <Badge>
                  {ask.result.trace.model} ·{" "}
                  {Math.round(ask.result.trace.latency_ms)} ms
                </Badge>
                {ask.result.invalid_citations.length > 0 && (
                  <div className="inline-error">
                    Invalid citation references:{" "}
                    {ask.result.invalid_citations.join(", ")}
                  </div>
                )}
                {ask.result.sources.map((c) => (
                  <div key={c.id} className="source-card">
                    <Badge good={c.cited}>
                      [{c.citation}] {c.document}
                    </Badge>
                    <p>{c.content}</p>
                  </div>
                ))}
              </>
            ) : search.result ? (
              search.result.length ? (
                search.result.map((c, i) => (
                  <div key={c.id} className="source-card">
                    <h3>
                      {i + 1}. {c.document} · chunk {c.position + 1}
                    </h3>
                    <p>{c.content}</p>
                    <Inspect
                      label="Retrieval identifiers & rank"
                      value={{
                        id: c.id,
                        document_id: c.document_id,
                        rank_score: c.rank_score,
                      }}
                    />
                  </div>
                ))
              ) : (
                <p className="muted-text">No relevant chunks matched.</p>
              )
            ) : (
              <p className="muted-text">
                Search to inspect your evidence before generating an answer.
              </p>
            )}
          </div>
        </section>
      </div>
    </>
  );
}

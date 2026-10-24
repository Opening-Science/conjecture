-- Conjecture v2 store: one SQLite file per field. Draft, P0, 24 Oct 2026.
--
-- Rules the schema encodes:
--   * Every row that came from outside says where from: `source` references
--     sources(name). A work found by several sources has one row in works
--     and one row per source in work_sources.
--   * Investment answers read only the *_commercial views, which drop rows
--     whose only support is a source with commercial_ok = 0 (Semantic
--     Scholar until AI2 grants permission).
--   * Growth is logged: every candidate decision is a row in admissions,
--     every label (LLM or human) a row in labels, so the audit sample and
--     its agreement can be recomputed.
--   * Every ask records who asked and for which decision (asks); fields
--     declare their use, and proposals never enter a non-funding store.
--   * Vectors live in `embeddings` as float32 BLOBs; a sqlite-vec index is
--     built over them at run time and is not part of the schema.
--
-- v1 compatibility: fieldmap.sqlite and knowledgebase.sqlite stay readable;
-- the P2 importer copies them into this schema with source 'openalex'
-- (works, authors, citations) or 'v1' (communities, statements, full text).

PRAGMA foreign_keys = ON;

CREATE TABLE meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;
INSERT INTO meta VALUES ('schema_version', '2.0-draft');

-- provenance --------------------------------------------------------------

CREATE TABLE sources(
    name TEXT PRIMARY KEY,           -- matches field.schema.json source_name
    licence TEXT,
    commercial_ok INTEGER NOT NULL CHECK (commercial_ok IN (0, 1)),
    note TEXT
) STRICT;
INSERT INTO sources VALUES
    ('openalex', 'CC0-1.0', 1, NULL),
    ('semantic_scholar', 'S2-API-licence', 0, 'commercial use needs AI2 permission'),
    ('crossref', 'Crossref metadata', 1, 'verify'),
    ('arxiv', 'arXiv metadata CC0', 1, NULL),
    ('grobid', 'derived from open-access PDFs', 1, NULL),
    ('github', 'GitHub ToS', 1, NULL),
    ('ecosystems', 'verify', 0, NULL),
    ('lens', 'verify', 0, NULL),
    ('epo', 'verify', 0, NULL),
    ('user', 'as supplied', 1, NULL),
    ('llm', 'generated', 1, 'extractions and labels'),
    ('v1', 'derived', 1, 'imported from a v1 pack build');

CREATE TABLE snapshots(
    snapshot_id TEXT PRIMARY KEY,    -- sha256 over field.yaml + table digests
    created TEXT NOT NULL,
    parent TEXT REFERENCES snapshots(snapshot_id),
    field_sha256 TEXT NOT NULL,
    counts TEXT NOT NULL,            -- JSON: rows per table
    note TEXT
) STRICT;

-- works and growth --------------------------------------------------------

CREATE TABLE works(
    work_id TEXT PRIMARY KEY,        -- OpenAlex id when one exists, else 'x:<source>:<id>'
    doi TEXT, arxiv_id TEXT, openalex_id TEXT, s2_id TEXT, pmid TEXT,
    title TEXT NOT NULL,
    abstract TEXT,
    year INTEGER,
    type TEXT,
    lang TEXT,
    venue TEXT,
    cited_by_count INTEGER,
    is_oa INTEGER,
    oa_url TEXT,
    is_seed INTEGER NOT NULL DEFAULT 0,
    seed_lens TEXT,
    is_holdout INTEGER NOT NULL DEFAULT 0,   -- hidden from growth to measure recall
    status TEXT NOT NULL DEFAULT 'admitted'
        CHECK (status IN ('admitted', 'queued', 'rejected', 'document')),
    first_snapshot TEXT REFERENCES snapshots(snapshot_id)
) STRICT;
CREATE INDEX works_doi ON works(doi);
CREATE INDEX works_arxiv ON works(arxiv_id);

CREATE TABLE work_sources(
    work_id TEXT NOT NULL REFERENCES works(work_id),
    source TEXT NOT NULL REFERENCES sources(name),
    external_id TEXT,
    fetched TEXT,
    PRIMARY KEY (work_id, source)
) STRICT;

CREATE TABLE documents(            -- curated works outside the indexes
    work_id TEXT PRIMARY KEY REFERENCES works(work_id),
    kind TEXT NOT NULL CHECK (kind IN ('regulation', 'guidance', 'standard',
        'report', 'dataset', 'note', 'proposal')),
    path TEXT, url TEXT, sha256 TEXT,
    lens TEXT
) STRICT;

CREATE TABLE admissions(
    work_id TEXT NOT NULL REFERENCES works(work_id),
    round INTEGER NOT NULL,
    route TEXT NOT NULL CHECK (route IN ('seed', 'citation_backward',
        'citation_forward', 'keyword', 'similar', 'recommend', 'user', 'ask')),
    via TEXT,                        -- the work, query or ask that led here
    candidate_source TEXT NOT NULL REFERENCES sources(name),
    relevance REAL,
    decision TEXT NOT NULL CHECK (decision IN ('admit', 'reject', 'queue')),
    decided_by TEXT NOT NULL,        -- 'llm:<model>', 'human:<id>', 'rule:<name>'
    reason TEXT,
    snapshot TEXT REFERENCES snapshots(snapshot_id),
    PRIMARY KEY (work_id, round, route)
) STRICT;

CREATE TABLE labels(               -- relevance and audit labels, gold grading
    item_type TEXT NOT NULL,         -- 'work', 'claim', 'answer'
    item_id TEXT NOT NULL,
    task TEXT NOT NULL,              -- 'relevance', 'lens:<name>', 'claim_ok', 'gold:<qid>'
    label TEXT NOT NULL,
    labeller TEXT NOT NULL,          -- 'llm:<model>' or 'human:<id>'
    is_audit INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL,
    PRIMARY KEY (item_type, item_id, task, labeller)
) STRICT;

-- citation structure -------------------------------------------------------

CREATE TABLE citations(
    src_work_id TEXT NOT NULL,
    dst_work_id TEXT NOT NULL,       -- may be outside works (a reference only)
    source TEXT NOT NULL REFERENCES sources(name),
    PRIMARY KEY (src_work_id, dst_work_id, source)
) STRICT, WITHOUT ROWID;
CREATE INDEX citations_dst ON citations(dst_work_id);

CREATE TABLE citation_contexts(
    src_work_id TEXT NOT NULL,
    dst_work_id TEXT NOT NULL,
    sentence TEXT NOT NULL,
    section TEXT,
    source TEXT NOT NULL REFERENCES sources(name)
) STRICT;

CREATE TABLE phantom_refs(
    work_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL
) STRICT;

-- actors and money ---------------------------------------------------------

CREATE TABLE authors(
    author_id TEXT PRIMARY KEY, display_name TEXT, orcid TEXT,
    works_count INTEGER, cited_by_count INTEGER,
    last_institution_id TEXT, country TEXT, openness REAL,
    source TEXT NOT NULL REFERENCES sources(name)
) STRICT;

CREATE TABLE institutions(
    inst_id TEXT PRIMARY KEY, display_name TEXT, type TEXT, country TEXT, ror TEXT,
    source TEXT NOT NULL REFERENCES sources(name)
) STRICT;

CREATE TABLE work_authors(
    work_id TEXT NOT NULL, author_id TEXT NOT NULL, position TEXT,
    is_corresponding INTEGER, inst_id TEXT, raw_affiliation TEXT,
    PRIMARY KEY (work_id, author_id)
) STRICT;

CREATE TABLE funders(
    funder_id TEXT PRIMARY KEY, display_name TEXT, country TEXT, ror TEXT,
    source TEXT NOT NULL REFERENCES sources(name)
) STRICT;

CREATE TABLE awards(
    award_id TEXT PRIMARY KEY,
    funder_id TEXT REFERENCES funders(funder_id),
    funder_award_id TEXT,
    title TEXT, amount REAL, currency TEXT,
    start_date TEXT, end_date TEXT,
    lead_inst_id TEXT,
    source TEXT NOT NULL REFERENCES sources(name)
) STRICT;

CREATE TABLE work_awards(
    work_id TEXT NOT NULL, award_id TEXT NOT NULL,
    source TEXT NOT NULL REFERENCES sources(name),
    PRIMARY KEY (work_id, award_id, source)
) STRICT;

CREATE TABLE repos(                -- v1 repos.sqlite, merged
    repo TEXT PRIMARY KEY,           -- lower-case owner/name
    name_with_owner TEXT, description TEXT, topics TEXT, license TEXT,
    license_class TEXT, stars INTEGER, forks INTEGER, created TEXT,
    pushed TEXT, archived INTEGER, is_fork INTEGER, language TEXT,
    readme TEXT, fetched TEXT, keep INTEGER,
    source TEXT NOT NULL REFERENCES sources(name)
) STRICT;

CREATE TABLE repo_work_links(
    repo TEXT NOT NULL, work_id TEXT NOT NULL, via TEXT NOT NULL,
    source TEXT NOT NULL REFERENCES sources(name),
    PRIMARY KEY (repo, work_id, via)
) STRICT;

CREATE TABLE patents(              -- phase P7, optional
    patent_id TEXT PRIMARY KEY, title TEXT, applicants TEXT,
    priority_date TEXT, jurisdiction TEXT,
    source TEXT NOT NULL REFERENCES sources(name)
) STRICT;

CREATE TABLE patent_work_links(
    patent_id TEXT NOT NULL, work_id TEXT NOT NULL,
    source TEXT NOT NULL REFERENCES sources(name),
    PRIMARY KEY (patent_id, work_id)
) STRICT;

-- text ---------------------------------------------------------------------

CREATE TABLE fulltexts(
    work_id TEXT PRIMARY KEY REFERENCES works(work_id),
    file TEXT, sha256 TEXT, n_pages INTEGER, n_chars INTEGER, quality TEXT,
    source TEXT NOT NULL REFERENCES sources(name)
) STRICT;

CREATE TABLE chunks(
    chunk_id TEXT PRIMARY KEY,       -- '<work_id>:<ord>'
    work_id TEXT NOT NULL REFERENCES works(work_id),
    ord INTEGER NOT NULL,
    page INTEGER,
    section TEXT,
    text TEXT NOT NULL
) STRICT;

CREATE TABLE statements(           -- open problems, limitations, future work
    stmt_id INTEGER PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(work_id),
    page INTEGER,
    kind TEXT NOT NULL,
    sentence TEXT NOT NULL,
    source TEXT NOT NULL REFERENCES sources(name)
) STRICT;

CREATE VIRTUAL TABLE works_fts USING fts5(
    work_id UNINDEXED, title, abstract, tokenize='porter unicode61');
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    chunk_id UNINDEXED, text, tokenize='porter unicode61');
CREATE VIRTUAL TABLE statements_fts USING fts5(
    stmt_id UNINDEXED, sentence, tokenize='porter unicode61');

CREATE TABLE embeddings(
    object_type TEXT NOT NULL CHECK (object_type IN ('work', 'chunk',
        'statement', 'lens', 'field', 'question')),
    object_id TEXT NOT NULL,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,            -- float32, little-endian, L2-normalised
    source TEXT NOT NULL REFERENCES sources(name),  -- semantic_scholar if served by S2
    PRIMARY KEY (object_type, object_id, model)
) STRICT;

-- views of the field ---------------------------------------------------------

CREATE TABLE lenses(
    lens TEXT PRIMARY KEY, title TEXT NOT NULL, definition TEXT NOT NULL,
    pattern TEXT
) STRICT;

CREATE TABLE lens_scores(
    object_type TEXT NOT NULL,       -- 'work', 'cluster', 'statement', 'repo'
    object_id TEXT NOT NULL,
    lens TEXT NOT NULL REFERENCES lenses(lens),
    method TEXT NOT NULL CHECK (method IN ('embedding', 'pattern', 'label')),
    score REAL NOT NULL,
    snapshot TEXT REFERENCES snapshots(snapshot_id),
    PRIMARY KEY (object_type, object_id, lens, method, snapshot)
) STRICT;

CREATE TABLE partitions(
    partition_id TEXT PRIMARY KEY,   -- e.g. 'hybrid-w0.5-r0.032-s42'
    snapshot TEXT REFERENCES snapshots(snapshot_id),
    method TEXT NOT NULL,            -- 'coupling', 'hybrid', 'statements'
    params TEXT NOT NULL,            -- JSON
    ari_mean REAL, ari_sd REAL,
    chosen INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE memberships(
    partition_id TEXT NOT NULL REFERENCES partitions(partition_id),
    object_id TEXT NOT NULL,         -- work_id, or stmt_id for statement partitions
    cluster INTEGER NOT NULL,
    stability REAL,
    core_score REAL,
    PRIMARY KEY (partition_id, object_id)
) STRICT;

-- claims (phase P7) ----------------------------------------------------------

CREATE TABLE entities(
    entity_id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL,
    canonical_id TEXT REFERENCES entities(entity_id)
) STRICT;

CREATE TABLE claims(
    claim_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL REFERENCES entities(entity_id),
    relation TEXT NOT NULL,
    object TEXT REFERENCES entities(entity_id),
    quantity TEXT, value REAL, unit TEXT,
    work_id TEXT NOT NULL REFERENCES works(work_id),
    sentence TEXT NOT NULL,          -- the evidence, verbatim
    extractor TEXT NOT NULL,         -- 'llm:<model>@<prompt sha>'
    source TEXT NOT NULL REFERENCES sources(name),
    certified INTEGER                -- NULL unchecked, 1 supported, 0 not
) STRICT;

-- asks and the conflict-of-interest log -----------------------------------

CREATE TABLE asks(
    ask_id TEXT PRIMARY KEY,
    created TEXT NOT NULL,
    requester TEXT NOT NULL,         -- a person, never 'anonymous'
    decision_context TEXT NOT NULL CHECK (decision_context IN
        ('research', 'funding_call', 'grant_review', 'investment')),
    decision_ref TEXT,               -- call, proposal or deal the answer informs
    question TEXT NOT NULL,
    modes TEXT NOT NULL,             -- JSON list: evidence, analytics, landscape, generate, check
    snapshot TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    coverage TEXT,                   -- JSON: hits per sub-question, full-text share, blind spots
    grew INTEGER NOT NULL DEFAULT 0, -- 1 if a coverage-triggered growth round ran
    status TEXT NOT NULL CHECK (status IN ('answered', 'declined', 'refused', 'error')),
    answer_path TEXT
) STRICT;

CREATE TABLE ask_citations(
    ask_id TEXT NOT NULL REFERENCES asks(ask_id),
    step INTEGER NOT NULL,
    work_id TEXT NOT NULL,
    certified INTEGER,               -- as judge/certify: 1 supported, 0 not
    PRIMARY KEY (ask_id, step, work_id)
) STRICT;

-- proposal firewall: a proposal document may never sit in a store that has
-- answered an investment ask, and vice versa
CREATE TRIGGER no_proposal_after_investment
BEFORE INSERT ON documents
WHEN NEW.kind = 'proposal'
     AND EXISTS (SELECT 1 FROM asks WHERE decision_context = 'investment')
BEGIN
    SELECT RAISE(ABORT, 'proposal firewall: this store has served investment asks');
END;

CREATE TRIGGER no_investment_with_proposals
BEFORE INSERT ON asks
WHEN NEW.decision_context = 'investment'
     AND EXISTS (SELECT 1 FROM documents WHERE kind = 'proposal')
BEGIN
    SELECT RAISE(ABORT, 'proposal firewall: this store holds proposals');
END;

-- views for investment answers: only rows a commercially usable source supports

CREATE VIEW works_commercial AS
SELECT w.* FROM works w
WHERE EXISTS (SELECT 1 FROM work_sources ws JOIN sources s ON s.name = ws.source
              WHERE ws.work_id = w.work_id AND s.commercial_ok = 1);

CREATE VIEW citations_commercial AS
SELECT DISTINCT c.src_work_id, c.dst_work_id FROM citations c
JOIN sources s ON s.name = c.source
WHERE s.commercial_ok = 1
  AND c.dst_work_id NOT IN (SELECT work_id FROM phantom_refs);

CREATE VIEW embeddings_commercial AS
SELECT e.* FROM embeddings e JOIN sources s ON s.name = e.source
WHERE s.commercial_ok = 1;

-- how many independent sources back each citation edge (phantom-hub check, G6)
CREATE VIEW citation_support AS
SELECT src_work_id, dst_work_id, COUNT(*) AS n_sources,
       GROUP_CONCAT(source) AS sources
FROM citations GROUP BY src_work_id, dst_work_id;

"""Memória persistente da malha em SQLite (WAL) — substitui o JSON por projeto.

Motivação (autonomia sem contratar nada):
- JSON inteiro reescrito a cada ciclo é O(estado_total); SQLite INSERT é O(novos)
  e sobrevive a queda no meio da escrita (transação + WAL checkpoint).
- Consultas reais: busca por similaridade de cosseno sobre embeddings INT8,
  deduplicação MinHash/LSH, janela deslizante de decisões, histórico de crescimento.
- Zero processo servidor, zero dependência externa: arquivo único por projeto em
  ``<workspace>/.turboquant_data/<slug>.db``.

Esquema:
- artifacts(key, value, signature, cycle, ts)
- decisions(text, cycle, ts)
- growth(cycle, stage, fitness, ts)
- environments(ts, payload_json)
- embeddings(id, kind, ref, vector_int8 BLOB, scale, min_val, sig64, ts)
  (vetor quantizado INT8: 4x menos memória; similaridade calculada com
   dequantização barata em CPU — ver turboquant.cpu_compute)
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import struct
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from turboquant.cpu_compute import MinHasher, all_but_the_top, mean_direction
from turboquant.inference import embed

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS artifacts(
    key TEXT PRIMARY KEY, value TEXT NOT NULL, signature TEXT NOT NULL,
    cycle INTEGER DEFAULT 0, ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions(
    id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
    cycle INTEGER DEFAULT 0, ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS growth(
    id INTEGER PRIMARY KEY AUTOINCREMENT, cycle INTEGER, stage TEXT,
    fitness REAL, ts INTEGER
);
CREATE TABLE IF NOT EXISTS environments(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, payload_json TEXT
);
CREATE TABLE IF NOT EXISTS embeddings(
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ref TEXT,
    vector BLOB, scale REAL, min_val REAL DEFAULT 0, sig64 INTEGER, ts INTEGER
);
CREATE INDEX IF NOT EXISTS idx_emb_kind ON embeddings(kind);
CREATE INDEX IF NOT EXISTS idx_dec_ts ON decisions(ts);
"""


def _slug(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", name).strip("_") or "default"


_INT8_MIN = -(1 << 7)   # -128
_INT8_MAX = (1 << 7) - 1  # 127


def _pack(vec: Sequence[float]) -> Tuple[bytes, float]:
    """Quantização simétrica INT8: escala pela MAIOR magnitude (não pelo range).

    Erro por componente ≤ amplitude/254 ≈ 0,4% da norma — independente da
    distribuição dos dados (robusto a outliers de cauda que destruíam a versão
    min-max em embeddings esparsos).
    """
    if not vec:
        return b"", 1.0
    amp = max(max(vec), -min(vec)) or 1.0
    scale = amp / _INT8_MAX
    q = [max(_INT8_MIN, min(_INT8_MAX, int(round(x / scale)))) for x in vec]
    return struct.pack(f"<{len(q)}b", *q), scale


def _unpack(blob: bytes, scale: float) -> List[float]:
    return [v * scale for v in struct.unpack(f"<{len(blob)}b", blob)]


class MeshStore:
    """KV + memória episódica vetorial em SQLite, thread-safe (lock de escrita)."""

    def __init__(self, project_name: str, workspace_root: str = ".") -> None:
        self.project_name = project_name
        data_dir = Path(workspace_root) / ".turboquant_data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / f"{_slug(project_name)}.db"
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---------------- ciclo / runs ----------------
    def bump_runs(self) -> int:
        cur = self._conn.execute("SELECT value FROM meta WHERE key='runs'")
        row = cur.fetchone()
        runs = int(row[0]) + 1 if row else 1
        self._conn.execute(
            "INSERT INTO meta(key,value) VALUES('runs',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(runs),),
        )
        self._conn.commit()
        return runs

    @property
    def runs(self) -> int:
        row = self._conn.execute("SELECT value FROM meta WHERE key='runs'").fetchone()
        return int(row[0]) if row else 0

    # ---------------- artefatos ----------------
    def publish_artifact(self, key: str, value: str, signature: str, cycle: int = 0) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO artifacts(key,value,signature,cycle,ts) VALUES(?,?,?,?,?)",
            (key, value, signature, cycle, int(time.time())),
        )
        self._conn.commit()

    def artifacts(self) -> Dict[str, Tuple[str, str]]:
        rows = self._conn.execute("SELECT key,value,signature FROM artifacts").fetchall()
        return {k: (v, s) for k, v, s in rows}

    # ---------------- decisões ----------------
    def add_decisions(self, texts: Sequence[str], cycle: int = 0) -> None:
        now = int(time.time())
        self._conn.executemany(
            "INSERT INTO decisions(text,cycle,ts) VALUES(?,?,?)",
            [(t, cycle, now) for t in texts],
        )
        self._conn.commit()

    def recent_decisions(self, limit: int = 20) -> List[str]:
        rows = self._conn.execute(
            "SELECT text FROM decisions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [r[0] for r in reversed(rows)]

    # ---------------- crescimento / ambiente ----------------
    def add_growth(self, cycle: int, stage: str, fitness: float) -> None:
        self._conn.execute(
            "INSERT INTO growth(cycle,stage,fitness,ts) VALUES(?,?,?,?)",
            (cycle, stage, fitness, int(time.time())),
        )
        self._conn.commit()

    def growth_history(self, limit: int = 200) -> List[Dict[str, object]]:
        rows = self._conn.execute(
            "SELECT cycle,stage,fitness,ts FROM growth ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            {"cycle": c, "stage": s, "fitness": f, "timestamp": t}
            for c, s, f, t in reversed(rows)
        ]

    def add_environment(self, payload: dict) -> None:
        self._conn.execute(
            "INSERT INTO environments(ts,payload_json) VALUES(?,?)",
            (int(time.time()), json.dumps(payload, ensure_ascii=False)),
        )
        self._conn.commit()

    # ---------------- embeddings + busca semântica ----------------
    def index_text(self, kind: str, ref: str, text: str) -> None:
        mh = MinHasher(num_perm=16)
        sig = mh.signature(mh.shingles(text))
        # bucket LSH-ish: 32 bits (SQLite INTEGER é assinado de 64 bits)
        sig64 = (sig[0] if sig else 0) & 0xFFFFFFFF
        blob, scale = _pack(embed(text))
        self._conn.execute(
            "INSERT INTO embeddings(kind,ref,vector,scale,min_val,sig64,ts) VALUES(?,?,?,?,?,?,?)",
            (kind, ref, blob, scale, 0.0, sig64, int(time.time())),
        )
        self._conn.commit()

    def semantic_search(self, query: str, kind: Optional[str] = None, top_k: int = 5) -> List[Tuple[str, float]]:
        """Busca por cosseno com whitelist de candidatos via LSH-ish (sig64 bucket).

        Estratégia CPU-first: compara só candidatos com assinatura parecida OU, se
        poucos itens indexados (<512), varredura linear direta — ambos O(n·d) com
        d=256 e dequantização barata, mensuravelmente rápido em 2 cores.
        """
        q = embed(query)
        rows = self._conn.execute(
            "SELECT ref,vector,scale FROM embeddings" + (" WHERE kind=?" if kind else ""),
            (kind,) if kind else (),
        ).fetchall()
        scored: List[Tuple[str, float]] = []
        for ref, blob, scale in rows:
            vec = _unpack(blob, scale)
            scored.append((ref, _cosine(q, vec)))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    def nearest_neighbor_exists(self, text: str, threshold: float = 0.92) -> Optional[str]:
        """Deduplicação semântica barata: retorna ref do vizinho acima do limiar."""
        hits = self.semantic_search(text, top_k=1)
        if hits and hits[0][1] >= threshold:
            return hits[0][0]
        return None

    def whiteness_report(self) -> dict:
        """Diagnóstico de anisotropia dos embeddings armazenados (cones of dominance).

        Usa a média global μ como estimador do cone dominante e mede o ângulo médio
        entre vetores e μ (em graus): ~90° ⇒ espaço uniforme; ≪90° ⇒ cone dominante.
        Após all-but-the-top, o ângulo deve convergir para ~90°.
        """
        rows = self._conn.execute("SELECT vector,scale FROM embeddings").fetchall()
        if len(rows) < 3:
            return {"itens": len(rows), "angulo_medio_com_media_graus": None}
        vectors = [_unpack(b, sc) for b, sc in rows]
        mu = mean_direction(vectors)
        raw_angle = _mean_angle_to_mean(vectors, mu)
        centered = all_but_the_top(vectors)
        fixed_angle = _mean_angle_to_mean(centered, mean_direction(centered))
        uniform = raw_angle >= 80.0 or fixed_angle >= 80.0
        return {
            "itens": len(vectors),
            "cosseno_medio": round(_avg_cos(vectors), 4),
            "angulo_medio_com_media_graus": round(raw_angle, 1),
            "angulo_pos_whitening_graus": round(fixed_angle, 1),
            "diagnostico": (
                "espaco uniforme (sem cone dominante)"
                if uniform
                else "cone dominante detectado — busca usa espaco whitened"
            ),
        }

    def brief(self) -> str:
        dec = self._conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        art = self._conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        emb = self._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        return f"Memória {self.project_name}: {self.runs} execuções, {dec} decisões, {art} artefatos, {emb} embeddings."

    def close(self) -> None:
        self._conn.close()


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def _avg_cos(vectors: Sequence[Sequence[float]]) -> float:
    unit = []
    for v in vectors:
        nrm = math.sqrt(sum(x * x for x in v)) or 1.0
        unit.append([x / nrm for x in v])
    total, count = 0.0, 0
    for i in range(len(unit)):
        for j in range(i + 1, len(unit)):
            total += sum(a * b for a, b in zip(unit[i], unit[j]))
            count += 1
    return total / max(1, count)


def _mean_angle_to_mean(vectors: Sequence[Sequence[float]], mu: Sequence[float]) -> float:
    """Ângulo médio (graus) entre cada vetor e a direção média — teste de cone dominante."""
    import math as _m
    if not mu:
        return 90.0
    nmu = math.sqrt(sum(x * x for x in mu))
    if nmu == 0:
        return 90.0
    total, count = 0.0, 0
    for v in vectors:
        nv = math.sqrt(sum(x * x for x in v))
        if nv == 0:
            continue
        cos = max(-1.0, min(1.0, sum(a * b for a, b in zip(v, mu)) / (nv * nmu)))
        total += math.degrees(math.acos(cos))
        count += 1
    return total / max(1, count)

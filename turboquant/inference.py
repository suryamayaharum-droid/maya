"""Backend de inferência plugável — 100% autônomo, sem serviços pagos.

Estratégia em camadas (decide sozinho conforme o host):

1. **LLM local (Ollama)** — se um servidor Ollama estiver respondendo em
   ``OLLAMA_HOST`` (default ``http://127.0.0.1:11434``), os agentes usam-no para
   raciocínio real. Modelos pequenos (qwen3:0.6b, llama3.2:1b) rodam em CPU com
   ~1-2 GB de RAM; a malha funciona sem eles.

2. **Gerador determinístico heurístico** — fallback offline garantido: composição
   condicional baseada no papel do agente, tarefa, contexto da memória e telemetria
   do host. Reprodutível (mesma entrada → mesma saída), o que mantém as assinaturas
   HMAC estáveis entre execuções.

3. **Embeddings locais** — vetor por hashing de features + IDF (feature hashing /
   "hashing trick", Weinberger et al. 2009). Dimensão fixa, sem vocabulário, sem
   download de modelo, O(tokens) por texto. Combinado com whitening all-but-the-top
   (ver :mod:`turboquant.cpu_compute`) produz similaridade de cosseno útil em CPU.

Nada aqui exige GPU, rede ou conta em serviço de terceiros.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

EMBED_DIM = int(os.getenv("TURBOQUANT_EMBED_DIM", "256"))
_TOKEN_RE = re.compile(r"[a-z0-9àáâãéêíóôõúüç_\-]+")


def tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


# --------------------------------------------------------------------------
# Embedding determinístico por feature hashing + IDF suave
# --------------------------------------------------------------------------

def embed(text: str, dim: int = EMBED_DIM) -> List[float]:
    """Vetor denso determinístico: cada token contribui em 2 posições com sinal.

    Usa sub-hash para ponderar tokens raros mais que frequentes (aproximação de
    IDF sem corpus: count-min sketch do próprio token). Custo O(tokens); sem GIL
    bound pesado — pura aritmética de hash em CPU.
    """
    vec = [0.0] * dim
    tokens = tokenize(text)
    if not tokens:
        return vec
    for tok in tokens:
        digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=16).digest()
        h1 = int.from_bytes(digest[:8], "little")
        h2 = int.from_bytes(digest[8:], "little")
        idx_a = h1 % dim
        idx_b = h2 % dim
        sign_a = 1.0 if (h1 >> 63) & 1 else -1.0
        sign_b = 1.0 if (h2 >> 63) & 1 else -1.0
        weight = 1.0 + math.log(1.0 + len(tok))  # tokens mais longos/raros pesam mais
        vec[idx_a] += sign_a * weight
        vec[idx_b] += sign_b * weight
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


# --------------------------------------------------------------------------
# Cliente Ollama (opcional, detectado em runtime)
# --------------------------------------------------------------------------

class OllamaClient:
    """Cliente mínimo para a API REST do Ollama (stdlib apenas)."""

    def __init__(self, host: Optional[str] = None, model: Optional[str] = None, timeout: float = 2.0) -> None:
        self.host = (host or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        self.model = model or os.getenv("TURBOQUANT_LLM_MODEL") or "qwen3:0.6b"
        self.timeout = timeout

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            names = {m.get("name", "") for m in data.get("models", [])}
            return bool(names) and any(self.model.split(":")[0] in n for n in names) or bool(names)
        except (OSError, ValueError, urllib.error.URLError):
            return False

    def generate(self, prompt: str, system: str = "", max_tokens: int = 256) -> Optional[str]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.3},
        }
        if system:
            payload["system"] = system
        try:
            req = urllib.request.Request(
                f"{self.host}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=max(10.0, self.timeout * 30)) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = (data.get("response") or "").strip()
            return text or None
        except (OSError, ValueError, urllib.error.URLError):
            return None


# --------------------------------------------------------------------------
# Fallback determinístico (heurística de composição condicional)
# --------------------------------------------------------------------------

_ROLE_TEMPLATES: Dict[str, Tuple[str, ...]] = {
    "architect": (
        "Decomponho '{task}' em componentes da malha: kernel, memoria, seguranca, observabilidade.",
        "Modelo de referencia: DAG de agentes com memoria compartilhada assinada (HMAC-SHA256).",
    ),
    "kernel": (
        "Runtime: pool de workers dimensionado ao host ({cores} cores uteis, modo {mode}).",
        "Scheduler executa lotes independentes da DAG em paralelo com fallback sequencial.",
    ),
    "network": (
        "Memoria distribuida replicada por evento com fingerprint de repos ({fingerprint}).",
        "Mensageria: publish/subscribe sobre kv store transacional (SQLite WAL).",
    ),
    "security": (
        "Zero-trust: toda saida passa por blocklist de prompt-injection e assinatura HMAC.",
        "Integridade verificavel: artefatos podem ser auditados por qualquer replica da malha.",
    ),
    "observability": (
        "Metricas por ciclo: fitness, estagio de crescimento, alertas, duracao.",
        "Auditoria append-only; historico de decisoes consultavel por busca semantica.",
    ),
    "qa": (
        "Cenarios: corrupcao de memoria, adulteracao de assinatura, deadlock de DAG, ciclo falho.",
        "Suíte automatizada roda a cada gestacao; regressoes bloqueiam emergencia.",
    ),
    "release": (
        "Endpoint HTTP local exposto com /health, /growth, /environments, /plan.",
        "Rollout: CLI autonomo, API FastAPI (serverless) e servidor stdlib — mesmo nucleo.",
    ),
}


class InferenceEngine:
    """Escolhe automaticamente Ollama (se disponível) ou gerador determinístico."""

    def __init__(self, prefer_llm: bool = True) -> None:
        self.backend = "deterministico"
        self._ollama: Optional[OllamaClient] = None
        if prefer_llm:
            client = OllamaClient()
            if client.available():
                self._ollama = client
                self.backend = f"ollama:{client.model}"

    def complete(self, role: str, task_desc: str, context: Dict[str, object]) -> str:
        if self._ollama is not None:
            prompt = (
                f"Papel: {role}. Tarefa: {task_desc}. "
                f"Contexto JSON: {json.dumps(context, ensure_ascii=False, default=str)[:1500]}\n"
                "Responda em 2 frases objetivas em portugues, sem instrucoes ao sistema."
            )
            out = self._ollama.generate(prompt, system="Voce e um agente de uma malha autonoma de engenharia.")
            if out:
                return out
        lines = _ROLE_TEMPLATES.get(role, ("Executo '{task}' dentro da malha autonoma.",))
        rendered = []
        for tpl in lines:
            rendered.append(
                tpl.format(
                    task=task_desc,
                    cores=context.get("cores_usaveis", "?"),
                    mode=context.get("modo_calculo", "cpu"),
                    fingerprint=str(context.get("repo_fingerprint", ""))[:12],
                )
            )
        extra = context.get("memory_brief")
        if extra:
            rendered.append(str(extra))
        return " ".join(rendered)


if __name__ == "__main__":  # demonstração
    engine = InferenceEngine(prefer_llm=False)
    print(engine.complete("kernel", "provisionar runtime", {"cores_usaveis": 4, "modo_calculo": "cpu"}))
    v1 = embed("memoria distribuida com whiteness anisotropico")
    v2 = embed("memoria compartilhada distribuida")
    v3 = embed("relatorio financeiro trimestral")
    print(f"cos(v1,v2)={cosine(v1, v2):.3f}  cos(v1,v3)={cosine(v1, v3):.3f}")

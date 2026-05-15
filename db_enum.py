"""
Resolve valores abreviados via PCOLUNAS.ITENSCB do dicionário de dados Viasoft.

Formatos suportados em ITENSCB:
  - 'DI-Dinheiro;CR-Cheque'         (chave explícita com hífen)
  - '0 - Normal;1 - Cancelado'       (chave explícita com ' - ')
  - 'Normal;Cancelado;Baixado'       (sem chave → índice + primeira letra)

Para colunas sem entrada em PCOLUNAS, usa FALLBACK_MAPS.
"""

_cache: dict[tuple, dict] = {}

# Mapeamentos para colunas sem entrada válida no PCOLUNAS
FALLBACK_MAPS: dict[tuple, dict] = {
    ("PRDUPREC", "TIPOREC"): {
        "D": "Dinheiro/Débito",
        "C": "Crédito",
        "R": "Recibo",
    },
    ("PPDUPPAG", "TIPOACERTO"): {
        "DI": "Dinheiro",
        "CE": "Cheque Emitido",
        "CT": "Cheque Terceiro",
        "CM": "Conta Movimento",
    },
    ("CONTAMOVLAN", "SITUACAO"): {
        "P": "Pendente",
        "A": "Acertado Parcialmente",
        "B": "Baixado",
    },
}


def _parse_itenscb(raw: str) -> dict:
    result = {}
    if not raw:
        return result
    items = [i.strip() for i in raw.split(";") if i.strip()]
    for idx, item in enumerate(items):
        if " - " in item:
            k, _, v = item.partition(" - ")
            result[k.strip()] = v.strip()
        elif " = " in item:
            k, _, v = item.partition(" = ")
            result[k.strip()] = v.strip()
        elif "=" in item:
            k, _, v = item.partition("=")
            result[k.strip()] = v.strip()
        elif "-" in item:
            k, _, v = item.partition("-")
            result[k.strip()] = v.strip()
        else:
            # Indexado: sem chave explícita
            # Adiciona tanto índice quanto primeira letra como chaves
            result[str(idx)] = item
            if item:
                result[item[0].upper()] = item  # ex: 'B' → 'Baixado'
    return result


def load_enum(cur, tabela: str, coluna: str) -> dict:
    """Retorna {valor: descrição} para a coluna, com cache por sessão."""
    key = (tabela.upper(), coluna.upper())
    if key in _cache:
        return _cache[key]

    # Fallback manual tem prioridade quando não há PCOLUNAS válido
    if key in FALLBACK_MAPS:
        _cache[key] = FALLBACK_MAPS[key]
        return _cache[key]

    cur.execute(
        """SELECT ITENSCB FROM VIASOFT.PCOLUNAS
           WHERE TABELA = :t AND COLUNA = :c AND ITENSCB IS NOT NULL
             AND ROWNUM = 1""",
        t=key[0], c=key[1],
    )
    row = cur.fetchone()
    result = _parse_itenscb(row[0]) if row else {}

    # Se PCOLUNAS não resolveu, checar fallback mesmo assim
    if not result and key in FALLBACK_MAPS:
        result = FALLBACK_MAPS[key]

    _cache[key] = result
    return result


def resolve(cur, tabela: str, coluna: str, valor) -> str:
    """Retorna a descrição do valor, ou o próprio valor se não encontrado."""
    if valor is None:
        return ""
    enum = load_enum(cur, tabela, coluna)
    return enum.get(str(valor).strip(), str(valor))


def clear_cache():
    _cache.clear()

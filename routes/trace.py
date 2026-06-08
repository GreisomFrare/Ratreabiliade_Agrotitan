from flask import Blueprint, request, jsonify
from db_oracle import get_connection
from db_enum import resolve
import re

bp = Blueprint("trace", __name__, url_prefix="/api/trace")

_TIPOREC = {'R': 'Capital', 'J': 'Juros', 'D': 'Desconto', 'M': 'Multa'}
_TIPOPAG = {'P': 'Capital', 'J': 'Juros', 'D': 'Desconto', 'M': 'Multa'}

def _norm_duprec(v):
    return re.sub(r"\s*-\s*", "-", str(v).strip())


def _fmtval(v):
    try:
        s = f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {s}"
    except Exception:
        return ""


def _trunc(s, n=24):
    s = s or ""
    return s[:n] + "…" if len(s) > n else s


# ─── helpers de consulta ──────────────────────────────────────────────────────

def _filial(cur, estab):
    cur.execute(
        "SELECT RAZAOSOC, REDUZIDO, CNPJ FROM VIASOFT.FILIAL WHERE ESTAB = :e",
        e=estab,
    )
    r = cur.fetchone()
    if not r:
        return {}
    reduzido = f"{estab} - {r[1]}" if r[1] else f"{estab} - {r[0]}"
    razaosoc = f"{estab} - {r[0]}" if r[0] else str(estab)
    return {"razaosoc": razaosoc, "reduzido": reduzido, "cnpj": r[2]}


def _pessoa(cur, numerocm):
    cur.execute(
        "SELECT NOME, APELIDO, CNPJF FROM VIASOFT.CONTAMOV WHERE NUMEROCM = :n",
        n=numerocm,
    )
    r = cur.fetchone()
    if not r:
        return {}
    nome   = f"{numerocm} - {r[0]}" if r[0] else str(numerocm)
    apelido = f"{numerocm} - {r[1]}" if r[1] else nome
    return {"nome": nome, "apelido": apelido, "cnpjf": r[2]}


def _rotina(cur, rotina_id):
    if rotina_id is None:
        return None
    cur.execute(
        "SELECT DESCRICAO FROM VIASOFT.ROTINASISTEMA WHERE ID = :id",
        id=rotina_id,
    )
    r = cur.fetchone()
    return f"{rotina_id} - {r[0]}" if r else str(rotina_id)


def _pedcab_pgto(cur, estab, serie, numero):
    cur.execute(
        """SELECT p.SEQUENCIA, p.FORMAPGTO, f.DESCRICAO,
                  p.VALORPAGAMENTO, p.PRAZOPAGAMENTO, p.SITUACAO, s.DESCRICAO,
                  p.SALDOPEDFIN, p.SALDOPEDCM, p.SALDOPEDANTEC,
                  p.BONIFICACAO, p.VALORJURO
           FROM VIASOFT.PEDCABPGTO p
           LEFT JOIN VIASOFT.FORMAPGTO  f ON f.FORMAPGTO = p.FORMAPGTO
           LEFT JOIN VIASOFT.PSITUACA   s ON s.SITUACAO  = p.SITUACAO
           WHERE p.ESTAB=:e AND p.SERIE=:s AND p.NUMERO=:n
           ORDER BY p.SEQUENCIA""",
        e=estab, s=serie, n=numero,
    )
    rows = cur.fetchall()
    if not rows:
        return {}

    parcelas = []
    tot_valor = tot_saldo_fin = tot_saldo_cm = tot_saldo_antec = 0
    tot_bonif  = tot_juro = 0

    for r in rows:
        seq, fpgto_id, fpgto_desc, valor, prazo, sit_id, sit_desc, \
            saldo_fin, saldo_cm, saldo_antec, bonif, juro = r

        fp_label = f"{fpgto_id} - {fpgto_desc}" if fpgto_desc else str(fpgto_id)
        st_label = f"{sit_id} - {sit_desc}"     if sit_desc  else str(sit_id) if sit_id else None

        parcelas.append({
            "seq":      seq,
            "forma":    fp_label,
            "prazo":    prazo.strftime("%d/%m/%Y") if prazo else None,
            "valor":    float(valor)      if valor      else 0,
            "situacao": st_label,
            "saldo_fin":   float(saldo_fin)   if saldo_fin   else 0,
            "saldo_cm":    float(saldo_cm)    if saldo_cm    else 0,
            "saldo_antec": float(saldo_antec) if saldo_antec else 0,
        })
        tot_valor      += float(valor)      if valor      else 0
        tot_saldo_fin  += float(saldo_fin)  if saldo_fin  else 0
        tot_saldo_cm   += float(saldo_cm)   if saldo_cm   else 0
        tot_saldo_antec+= float(saldo_antec)if saldo_antec else 0
        tot_bonif      += float(bonif)      if bonif      else 0
        tot_juro       += float(juro)       if juro       else 0

    return {
        "parcelas":    parcelas,
        "tot_valor":   tot_valor,
        "tot_saldo_fin":   tot_saldo_fin   if tot_saldo_fin   else None,
        "tot_saldo_cm":    tot_saldo_cm    if tot_saldo_cm    else None,
        "tot_saldo_antec": tot_saldo_antec if tot_saldo_antec else None,
        "tot_bonif":   tot_bonif  if tot_bonif  else None,
        "tot_juro":    tot_juro   if tot_juro   else None,
    }


def _nfcab_agrfin(cur, estab, seqnota):
    cur.execute(
        """SELECT n.SEQPAGAMENTO, n.FORMAPGTO, f.DESCRICAO,
                  n.PARCELAMENT, afd.DUPREC,
                  COALESCE(d.VALOR, pv.VALOR, pl.VALOR) as VALOR,
                  d.DTVENCTO, d.QUITADA
           FROM VIASOFT.NFCABAGRFIN n
           LEFT JOIN VIASOFT.FORMAPGTO     f    ON f.FORMAPGTO        = n.FORMAPGTO
           LEFT JOIN VIASOFT.AGRFINDUPREC  afd  ON afd.SEQPAGAMENTO   = n.SEQPAGAMENTO
           LEFT JOIN VIASOFT.PDUPREC       d    ON REPLACE(d.DUPREC,' ','') = REPLACE(afd.DUPREC,' ','')
           LEFT JOIN VIASOFT.AGRFINCARTAO  ac   ON ac.SEQPAGAMENTO    = n.SEQPAGAMENTO
           LEFT JOIN VIASOFT.PRVDACAR      pv   ON pv.SEQPRVDACAR     = ac.SEQPRVDACAR
           LEFT JOIN VIASOFT.AGRFINCARTDIG afcd ON afcd.SEQPAGAMENTO  = n.SEQPAGAMENTO
           LEFT JOIN VIASOFT.ACERCARTDIG   acer ON acer.IDACERCARTDIG = afcd.IDACERCARTDIG
           LEFT JOIN VIASOFT.PLANCA        pl   ON pl.EMPRESA=acer.EMPRESA
                                                AND pl.DTLANCA=acer.DTLANCA
                                                AND pl.SEQLANCA=acer.SEQLANCA
           WHERE n.ESTAB=:e AND n.SEQNOTA=:s
           ORDER BY n.SEQPAGAMENTO""",
        e=estab, s=seqnota,
    )
    rows = cur.fetchall()
    if not rows:
        return {}

    parcelas = []
    tot_valor = 0

    for r in rows:
        seq_pag, fpgto_id, fpgto_desc, parcela, duprec, valor, dtvencto, quitada = r
        fp_label = f"{fpgto_id} - {fpgto_desc}" if fpgto_desc else str(fpgto_id)
        parcelas.append({
            "seq":     parcela,
            "forma":   fp_label,
            "duprec":  duprec,
            "valor":   float(valor) if valor else 0,
            "vencto":  dtvencto.strftime("%d/%m/%Y") if dtvencto else None,
            "quitada": quitada,
        })
        tot_valor += float(valor) if valor else 0

    return {
        "parcelas":  parcelas,
        "tot_valor": tot_valor,
    }


def _representante(cur, empresa, represent):
    if represent is None:
        return None
    cur.execute(
        "SELECT DESCRICAO FROM VIASOFT.PREPRESE WHERE EMPRESA=:e AND REPRESENT=:r",
        e=empresa, r=represent,
    )
    r = cur.fetchone()
    return f"{represent} - {r[0]}" if r else str(represent)


def _analitica(cur, empresa, analitica):
    if analitica is None:
        return None
    cur.execute(
        "SELECT DESCRICAO, RECEITA FROM VIASOFT.PANALITI WHERE EMPRESA=:e AND ANALITICA=:a",
        e=empresa, a=analitica,
    )
    r = cur.fetchone()
    if not r:
        return str(analitica)
    tipo = "Receita" if r[1] == "S" else "Despesa"
    return f"{analitica} - {r[0]} ({tipo})"


def _situacao(cur, situacao):
    if situacao is None:
        return None
    cur.execute(
        "SELECT DESCRICAO FROM VIASOFT.PSITUACA WHERE SITUACAO=:s",
        s=situacao,
    )
    r = cur.fetchone()
    return f"{situacao} - {r[0]}" if r else str(situacao)


def _banco(cur, banco):
    if banco is None:
        return None
    cur.execute(
        "SELECT DESCRICAO FROM VIASOFT.PCOBBANCO WHERE BANCO=:b",
        b=banco,
    )
    r = cur.fetchone()
    return f"{banco} - {r[0]}" if r else str(banco)


def _cobcab(cur, empresa, seqcobcab):
    if seqcobcab is None:
        return None
    cur.execute(
        """SELECT c.BANCO, c.DESCRICAO, b.DESCRICAO
           FROM VIASOFT.PCOBCAB c
           LEFT JOIN VIASOFT.PCOBBANCO b ON b.BANCO = c.BANCO
           WHERE c.EMPRESA=:e AND c.SEQCOBCAB=:s AND ROWNUM=1""",
        e=empresa, s=seqcobcab,
    )
    r = cur.fetchone()
    if not r:
        return None
    banco_desc = f"{r[0]} - {r[2]}" if r[2] else str(r[0])
    return {"descricao": f"{seqcobcab} - {r[1]}", "banco": banco_desc}


def _cobdet(cur, empresa, seqcobdet):
    if seqcobdet is None:
        return None
    cur.execute(
        """SELECT c.BANCO, c.DESCRICAO, b.DESCRICAO
           FROM VIASOFT.PCOBDET c
           LEFT JOIN VIASOFT.PCOBBANCO b ON b.BANCO = c.BANCO
           WHERE c.EMPRESA=:e AND c.SEQCOBDET=:s AND ROWNUM=1""",
        e=empresa, s=seqcobdet,
    )
    r = cur.fetchone()
    if not r:
        return None
    banco_desc = f"{r[0]} - {r[2]}" if r[2] else str(r[0])
    return {"descricao": f"{seqcobdet} - {r[1]}", "banco": banco_desc}


def _recibo(cur, estab, nrorecibo):
    if nrorecibo is None:
        return None
    cur.execute(
        """SELECT NUMERO, NUMEROESP, VALOR, DATA, NOMEDEVEDOR,
                  REFERENTE, USUARIO,
                  NOMEEMITENTE, ENDEMITENTE, COMPEMITENTE, CNPJF
           FROM VIASOFT.RECIBO
           WHERE ESTAB=:e AND NUMERO=:n""",
        e=estab, n=nrorecibo,
    )
    r = cur.fetchone()
    if not r:
        return None
    numero, numeroesp, valor, data, nomedevedor, referente, usuario, \
        nomeemitente, endemitente, compemitente, cnpjf = r
    if hasattr(referente, 'read'):
        referente = referente.read()
    if isinstance(referente, bytes):
        referente = referente.decode("latin-1")
    return {
        "numero":       numero,
        "numero_esp":   numeroesp,
        "valor":        float(valor) if valor else 0,
        "data":         data.strftime("%d/%m/%Y") if data else None,
        "nomedevedor":  nomedevedor,
        "referente":    referente,
        "usuario":      usuario,
        "nomeemitente": nomeemitente,
        "endemitente":  endemitente,
        "compemitente": compemitente,
        "cnpjf":        cnpjf,
    }


def _portador(cur, empresa, portador):
    cur.execute(
        "SELECT DESCRICAO, BANCO FROM VIASOFT.PPORTADO WHERE EMPRESA=:e AND PORTADOR=:p",
        e=empresa, p=portador,
    )
    r = cur.fetchone()
    if not r:
        return {}
    desc = f"{portador} - {r[0]}" if r[0] else str(portador)
    return {"descricao": desc, "banco": r[1]}


def _build_contamovlan_node(cur, numerocm, seqcm, estab_cm, val_fallback):
    cur.execute(
        """SELECT cml.DTMOVTO, cml.TIPO, cml.VALOR, cml.HISTORICO, cml.USERID, cml.NRORECIBO,
                  cml.VENCIMENTO, cml.SITUACAO, cml.HISTORICO2,
                  tp.DESCRICAO
           FROM VIASOFT.CONTAMOVLAN cml
           LEFT JOIN VIASOFT.CONTAMOVTP tp ON tp.TIPO = cml.TIPO
           WHERE cml.NUMEROCM=:numerocm AND cml.SEQCM=:seqcm
             AND (:estab IS NULL OR cml.ESTAB=:estab)
             AND ROWNUM <= 1""",
        numerocm=numerocm, seqcm=seqcm, estab=estab_cm,
    )
    cml = cur.fetchone()
    cliente_info = _pessoa(cur, numerocm)
    cliente_nome = cliente_info.get("nome", str(numerocm))
    cml_id = f"CONTAMOVLAN-{numerocm}-{estab_cm or 0}-{seqcm}"

    if cml:
        dtmovto, tipo, valor, hist1, userid, nrorecibo, vencimento, situacao, hist2, tipo_desc_raw = cml
        tipo_desc = f"{tipo} - {tipo_desc_raw}" if tipo_desc_raw else (tipo or "")
        sit_desc  = resolve(cur, "CONTAMOVLAN", "SITUACAO", situacao)
        valor_real = float(valor) if valor else (float(val_fallback) if val_fallback else 0)
        node_type = "CONTAMOVLANAC" if tipo in ("ACDB", "ACCR") else "CONTAMOVLAN"
        return {
            "id":   cml_id,
            "type": node_type,
            "label": (
                f"<b>Conta Movimento</b>\n{_trunc(cliente_nome, 24)}  Seq: {seqcm}"
                + f"\nTipo: {_trunc(tipo_desc or tipo or '', 22)}"
                + (f"\nVencto: {vencimento.strftime('%d/%m/%Y')}" if vencimento else "")
                + f"\nValor: {_fmtval(valor_real)}"
            ),
            "data": {
                "numerocm":  numerocm,
                "cliente":   cliente_nome,
                "seqcm":     seqcm,
                "data":      dtmovto.strftime("%d/%m/%Y") if dtmovto else None,
                "vencimento": vencimento.strftime("%d/%m/%Y") if vencimento else None,
                "tipo":      tipo_desc or tipo,
                "situacao":  sit_desc or situacao,
                "valor":     valor_real,
                "historico": hist1,
                "historico2": hist2,
                "userid":    userid,
                "nrorecibo": nrorecibo,
            },
        }
    return {
        "id":   cml_id,
        "type": "CONTAMOVLAN",
        "label": (
            f"<b>Conta Movimento</b>\n{_trunc(cliente_nome, 24)}  Seq: {seqcm}"
            + f"\nValor: {_fmtval(val_fallback)}"
        ),
        "data": {
            "numerocm": numerocm,
            "cliente":  cliente_nome,
            "seqcm":    seqcm,
            "valor":    float(val_fallback) if val_fallback else 0,
        },
    }


def _empresa_desc(cur, empresa):
    cur.execute(
        "SELECT REDUZIDO FROM VIASOFT.EMPRESA WHERE EMPRESA=:e",
        e=empresa,
    )
    r = cur.fetchone()
    return f"{empresa} - {r[0]}" if r and r[0] else str(empresa)


def _build_planca_node(cur, emp, dtlanca, seqlanca):
    """Busca PLANCA e retorna o dict do nó pronto, ou None se não encontrado."""
    cur.execute(
        """SELECT pl.PORTADOR, pl.VALOR, pl.HISTORICO, pl.USERID,
                  pl.NRORECIBO, pl.NRODOC,
                  pl.ANALITICA, pl.ESTABANALITICA,
                  pl.HISTORICO2, pl.HISTORICO3, pl.HISTORICO4,
                  pl.ESTABRECIBO
           FROM VIASOFT.PLANCA pl
           WHERE pl.EMPRESA=:e AND pl.DTLANCA=:dt AND pl.SEQLANCA=:s""",
        e=emp, dt=dtlanca, s=seqlanca,
    )
    pl = cur.fetchone()
    if not pl:
        return None
    portador, valor, hist1, userid, nrorecibo, nrodoc, ana, estab_ana, hist2, hist3, hist4, estabrecibo = pl
    port_info      = _portador(cur, emp, portador) if portador else {}
    analitica_desc = _analitica(cur, estab_ana or emp, ana) if ana else None
    recibo_data    = _recibo(cur, estabrecibo or emp, nrorecibo) if nrorecibo else None
    empresa_desc   = _empresa_desc(cur, emp)
    return {
        "id":    f"PLANCA-{emp}-{dtlanca.strftime('%Y%m%d')}-{seqlanca}",
        "type":  "PLANCA",
        "label": (
            f"<b>Lançamento Financeiro</b>\nPortador: {_trunc(port_info.get('descricao', 'Dinheiro'), 20)}"
            f"\nData: {dtlanca.strftime('%d/%m/%Y')}"
            f"\nValor: {_fmtval(valor)}"
        ),
        "data": {
            "empresa":      empresa_desc,
            "portador_desc": port_info.get("descricao"),
            "valor":        float(valor) if valor else 0,
            "analitica":    analitica_desc,
            "historico":    hist1,
            "historico2":   hist2,
            "historico3":   hist3,
            "historico4":   hist4,
            "userid":       userid,
            "nrorecibo":    nrorecibo,
            "nrodoc":       nrodoc,
            "data":         dtlanca.strftime("%d/%m/%Y"),
            "recibo_data":  recibo_data,
        },
    }


def _pessoa_detail(cur, numerocm):
    cur.execute(
        """SELECT NOME, CNPJF, TIPOPESSOA, ENDERECO, NUMEROEND,
                  COMPLEMENTO, BAIRRO, CIDADE, CEP, TELEFONE, CELULAR
           FROM VIASOFT.CONTAMOV WHERE NUMEROCM = :n""",
        n=numerocm,
    )
    r = cur.fetchone()
    if not r:
        return {}
    nome, cnpjf, tipopessoa, endereco, numeroend, complemento, bairro, cidade_cod, cep, telefone, celular = r

    cidade_nome = uf = None
    if cidade_cod:
        cur.execute("SELECT NOME, UF FROM VIASOFT.CIDADE WHERE CIDADE = :c", c=cidade_cod)
        cr = cur.fetchone()
        if cr:
            cidade_nome, uf = cr

    cnpjf_fmt = None
    if cnpjf:
        digits = "".join(c for c in str(cnpjf) if c.isdigit())
        if len(digits) <= 11:
            d = digits.zfill(11)
            cnpjf_fmt = f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
        else:
            d = digits.zfill(14)
            cnpjf_fmt = f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"

    return {
        "numerocm": numerocm,
        "nome": nome,
        "cnpjf": cnpjf_fmt or (str(cnpjf) if cnpjf else None),
        "tipopessoa": tipopessoa,
        "endereco": endereco,
        "numeroend": str(numeroend) if numeroend else None,
        "complemento": complemento,
        "bairro": bairro,
        "cidade": cidade_nome,
        "uf": uf,
        "cep": cep,
        "telefone": str(telefone) if telefone else None,
        "celular": str(celular) if celular else None,
    }


def _pessoa_label(d):
    lines = ["<b>Pessoa</b>"]
    if d.get("cnpjf"):
        lines.append(f"CPF/CNPJ: {d['cnpjf']}")
    if d.get("nome"):
        lines.append(_trunc(d["nome"], 26))
    if d.get("endereco"):
        end = d["endereco"]
        if d.get("numeroend"):
            end += f", {d['numeroend']}"
        lines.append(end)
    loc_parts = []
    if d.get("bairro"):
        loc_parts.append(d["bairro"])
    if d.get("cidade"):
        loc_parts.append(f"{d['cidade']}/{d['uf']}" if d.get("uf") else d["cidade"])
    if loc_parts:
        lines.append(" - ".join(loc_parts))
    return "\n".join(lines)


# ─── trace por PDUPREC ───────────────────────────────────────────────────────

def _trace_pduprec(cur, empresa, duprec_raw, skip_pessoa=False, skip_upstream=False):
    nodes = []
    edges = []
    duprec_norm = _norm_duprec(duprec_raw)

    # PDUPREC
    cur.execute(
        """SELECT d.EMPRESA, d.DUPREC, d.ESTABCLIENTE, d.CLIENTE,
                  d.VALOR, d.DTEMISSAO, d.DTVENCTO, d.QUITADA,
                  d.PORTADOR, d.USERID, d.HISTORICO,
                  d.REPRESENT, d.ESTABREPRESENT,
                  d.ANALITICA, d.ESTABANALITICA,
                  d.SITUACAO, d.SEQCOBCAB, d.SEQCOBDET, d.BANCO
           FROM VIASOFT.PDUPREC d
           WHERE d.EMPRESA = :emp
             AND REPLACE(d.DUPREC,' ','') = :dup""",
        emp=empresa, dup=duprec_norm,
    )
    dup = cur.fetchone()
    if not dup:
        return None, None, "Duplicata não encontrada"

    (emp, duprec, estab_cli, cliente, valor, dtemissao, dtvencto, quitada,
     portador, userid, historico,
     represent, estab_represent,
     analitica, estab_analitica,
     situacao, seqcobcab, seqcobdet, banco_dup) = dup
    duprec_real = duprec
    pessoa_numerocm = cliente  # atualizado para PEDCAB.PESSOA se encontrado

    filial_info   = _filial(cur, emp)
    cliente_info  = _pessoa(cur, cliente)
    port_info     = _portador(cur, emp, portador) if portador else {}
    cobcab_info   = _cobcab(cur, emp, seqcobcab)
    cobdet_info   = _cobdet(cur, emp, seqcobdet)

    banco_desc = _banco(cur, banco_dup)

    dup_id = f"PDUPREC-{emp}-{duprec_norm}"
    nodes.append({
        "id": dup_id,
        "type": "PDUPREC",
        "label": (
            f"<b>Duplicata a Receber</b>\nDup: {duprec_real}  Emp: {emp}"
            + (f"\nEmissão: {dtemissao.strftime('%d/%m/%Y')}" if dtemissao else "")
            + (f"\nVencto: {dtvencto.strftime('%d/%m/%Y')}" if dtvencto else "")
            + f"\nValor: {_fmtval(valor)}"
        ),
        "data": {
            "empresa": emp,
            "duprec": duprec_real,
            "filial": filial_info.get("reduzido", str(emp)),
            "cliente": cliente_info.get("nome", str(cliente)),
            "valor": float(valor) if valor else 0,
            "emissao": dtemissao.strftime("%d/%m/%Y") if dtemissao else None,
            "vencto": dtvencto.strftime("%d/%m/%Y") if dtvencto else None,
            "quitada": quitada,
            "situacao": _situacao(cur, situacao),
            "portador_desc": port_info.get("descricao"),
            "banco": banco_desc,
            "representante": _representante(cur, estab_represent or emp, represent),
            "analitica": _analitica(cur, estab_analitica or emp, analitica),
            "cobcab": cobcab_info.get("descricao") if cobcab_info else None,
            "cobdet": cobdet_info.get("descricao") if cobdet_info else None,
            "userid": userid,
            "historico": historico,
        },
    })

    # ── UPSTREAM: NF → AGRFINDUPREC → NFCABAGRFIN → NFCAB → PEDITEMNFITEM → PEDCAB
    cur.execute(
        """SELECT afd.SEQPAGAMENTO
           FROM VIASOFT.AGRFINDUPREC afd
           WHERE REPLACE(afd.DUPREC,' ','') = :dup""",
        dup=duprec_norm,
    )
    seqs = [r[0] for r in cur.fetchall()]

    nf_seqnotas_seen = set()
    for seq_pag in seqs:
        cur.execute(
            "SELECT ESTAB, SEQNOTA FROM VIASOFT.NFCABAGRFIN WHERE SEQPAGAMENTO=:s",
            s=seq_pag,
        )
        for estab_nf, seqnota in cur.fetchall():
            if (estab_nf, seqnota) in nf_seqnotas_seen:
                continue
            nf_seqnotas_seen.add((estab_nf, seqnota))

            cur.execute(
                """SELECT NOTA, SERIE, DTEMISSAO, VALOR, TIPODCTOORIG
                   FROM VIASOFT.NFCAB WHERE ESTAB=:e AND SEQNOTA=:s""",
                e=estab_nf, s=seqnota,
            )
            nf = cur.fetchone()
            if not nf:
                continue
            nota, serie, dt_nf, valor_nf, tipoorig = nf
            nf_id = f"NFCAB-{estab_nf}-{seqnota}"
            filial_nf = _filial(cur, estab_nf)
            agrfin = _nfcab_agrfin(cur, estab_nf, seqnota)
            nodes.append({
                "id": nf_id,
                "type": "NFCAB",
                "label": (
                    f"<b>Nota Fiscal</b>\nNota: {nota}  Seq.: {seqnota}"
                    f"\nSérie: {serie}  Estab: {estab_nf}"
                    + (f"\nEmissão: {dt_nf.strftime('%d/%m/%Y')}" if dt_nf else "")
                    + f"\nValor: {_fmtval(valor_nf)}"
                ),
                "data": {
                    "estab": estab_nf,
                    "nota": nota,
                    "serie": serie,
                    "seqnota": seqnota,
                    "filial": filial_nf.get("reduzido", str(estab_nf)),
                    "emissao": dt_nf.strftime("%d/%m/%Y") if dt_nf else None,
                    "valor": float(valor_nf) if valor_nf else 0,
                    "agrfin": agrfin,
                },
            })
            edges.append({"from": nf_id, "to": dup_id, "label": "gera duplicata"})

            # Itens da NF
            cur.execute(
                """SELECT ni.ITEM, ni.QUANTIDADE, ni.VALORTOTAL, ia.DESCRICAO, ia.UNIDADE
                   FROM VIASOFT.NFITEM ni
                   LEFT JOIN VIASOFT.ITEMAGRO ia ON ia.ITEM = ni.ITEM
                   WHERE ni.ESTAB=:e AND ni.SEQNOTA=:s""",
                e=estab_nf, s=seqnota,
            )
            itens = []
            for row in cur.fetchall():
                desc = f"{row[0]} - {row[3]}" if row[3] else str(row[0])
                itens.append({
                    "item": row[0],
                    "quantidade": float(row[1]) if row[1] else 0,
                    "valor": float(row[2]) if row[2] else 0,
                    "descricao": desc,
                    "unidade": row[4],
                })
            nodes[-1]["data"]["itens"] = itens

            # PEDCAB via PEDITEMNFITEM
            cur.execute(
                """SELECT DISTINCT p.ESTAB, p.SERIE, p.NUMERO
                   FROM VIASOFT.PEDITEMNFITEM p
                   WHERE p.ESTABNOTA=:en AND p.SEQNOTA=:sn""",
                en=estab_nf, sn=seqnota,
            )
            for estab_p, serie_p, num_p in cur.fetchall():
                ped_id = f"PEDCAB-{estab_p}-{serie_p}-{num_p}"
                cur.execute(
                    """SELECT PESSOA, DTEMISSAO, STATUS, USERID
                       FROM VIASOFT.PEDCAB
                       WHERE ESTAB=:e AND SERIE=:s AND NUMERO=:n""",
                    e=estab_p, s=serie_p, n=num_p,
                )
                ped = cur.fetchone()
                if not ped:
                    continue
                if ped[0]:
                    pessoa_numerocm = ped[0]
                pessoa_info = _pessoa(cur, ped[0]) if ped[0] else {}
                filial_ped = _filial(cur, estab_p)
                if not any(n["id"] == ped_id for n in nodes):
                    pgto = _pedcab_pgto(cur, estab_p, serie_p, num_p)
                    nodes.append({
                        "id": ped_id,
                        "type": "PEDCAB",
                        "label": (
                            f"<b>Pedido de Venda</b>\nPedido: {serie_p}/{num_p}  Estab: {estab_p}"
                            + (f"\nEmissão: {ped[1].strftime('%d/%m/%Y')}" if ped[1] else "")
                        ),
                        "data": {
                            "estab": estab_p,
                            "serie": serie_p,
                            "numero": num_p,
                            "filial": filial_ped.get("reduzido", str(estab_p)),
                            "pessoa": pessoa_info.get("nome", str(ped[0])),
                            "emissao": ped[1].strftime("%d/%m/%Y") if ped[1] else None,
                            "status": resolve(cur, "PEDCAB", "STATUS", ped[2]),
                            "userid": ped[3],
                            "pgto": pgto,
                        },
                    })
                edges.append({"from": ped_id, "to": nf_id, "label": "fatura em"})

    # ── UPSTREAM: documentos de origem alternativos (CTRC / CONHE / CONTRATO / RPA)
    _add_doc_origem_nodes(cur, seqs, dup_id, "gera duplicata", nodes, edges)

    # ── UPSTREAM via cartão: dup. administrativa → PACECARTAO → PRVDACAR → NF-e
    #    Omitido em dups administratoras (upstream já está no grafo principal)
    if not skip_upstream and not nf_seqnotas_seen:
        cur.execute(
            """SELECT p.SEQPRVDACAR, p.DUPREC as DUPREC_ORIG, p.NROVDA
               FROM VIASOFT.PACECARTAO p
               WHERE p.EMPRESA=:e AND REPLACE(p.DUPRECADM,' ','')=:dup
               AND ROWNUM=1""",
            e=emp, dup=duprec_norm,
        )
        pac = cur.fetchone()
        if pac:
            seqprvdacar, duprec_orig, nrovda_pac = pac

            if seqprvdacar:
                # Origem: venda em cartão na NF-e
                cur.execute(
                    """SELECT pv.NROVDA, pv.VALOR, pv.NROPARCELAS, pv.CARTAO, pv.AUTORIZACA,
                              pv.NSU, pv.NROCARTAO, pv.NOMEREDE,
                              pn.DESCRICAO as CARTAO_DESC,
                              b.DESCRICAO as BANDEIRA_DESC,
                              n.ESTAB, n.SEQNOTA
                       FROM VIASOFT.PRVDACAR pv
                       JOIN VIASOFT.AGRFINCARTAO ac ON ac.SEQPRVDACAR=pv.SEQPRVDACAR
                       JOIN VIASOFT.NFCABAGRFIN n ON n.SEQPAGAMENTO=ac.SEQPAGAMENTO
                       LEFT JOIN VIASOFT.PNOMECAR pn ON pn.CARTAO = pv.CARTAO
                       LEFT JOIN VIASOFT.PCONFCAR pc ON pc.EMPRESA=pv.EMPRESA AND pc.CARTAO=pv.CARTAO
                       LEFT JOIN VIASOFT.BANDEIRACARTAO b ON b.IDBANDEIRACARTAO=pc.ID_CARTAO
                       WHERE pv.SEQPRVDACAR=:seq""",
                    seq=seqprvdacar,
                )
                for nrovda_pv, valor_pv, nparcelas, cartao_pv, autorizaca, nsu_pv, nrocartao_pv, nomerede_pv, cartao_desc_pv, bandeira_pv, estab_nf, seqnota_nf in cur.fetchall():
                    prvdacar_id = f"PRVDACAR-{emp}-{seqprvdacar}"
                    if not any(n["id"] == prvdacar_id for n in nodes):
                        parc = int(nparcelas) if nparcelas else 1
                        cartao_label_pv = f"{cartao_pv} - {_trunc(cartao_desc_pv, 22)}" if cartao_desc_pv else str(cartao_pv)
                        nodes.append({
                            "id":   prvdacar_id,
                            "type": "PRVDACAR",
                            "label": (
                                f"<b>Venda em Cartão</b>"
                                + f"\n{cartao_label_pv}"
                                + f"\nNº Venda: {nrovda_pv}" + (f"  {parc}x" if parc > 1 else "")
                                + (f"\nNº Cartão: {nrocartao_pv}" if nrocartao_pv else "")
                                + f"\nValor: {_fmtval(valor_pv)}"
                            ),
                            "data": {
                                "empresa":     emp,
                                "nrovda":      nrovda_pv,
                                "valor":       float(valor_pv) if valor_pv else 0,
                                "nroparcelas": parc,
                                "cartao":      cartao_label_pv,
                                "bandeira":    bandeira_pv,
                                "autorizacao": autorizaca,
                                "nsu":         nsu_pv,
                                "nrocartao":   nrocartao_pv,
                                "nomerede":    nomerede_pv,
                            },
                        })
                    edges.append({"from": prvdacar_id, "to": dup_id, "label": "dup. adm."})

                    if (estab_nf, seqnota_nf) not in nf_seqnotas_seen:
                        nf_seqnotas_seen.add((estab_nf, seqnota_nf))
                        cur.execute(
                            """SELECT NOTA, SERIE, DTEMISSAO, VALOR
                               FROM VIASOFT.NFCAB WHERE ESTAB=:e AND SEQNOTA=:s""",
                            e=estab_nf, s=seqnota_nf,
                        )
                        nf = cur.fetchone()
                        if nf:
                            nota, serie, dt_nf, valor_nf = nf
                            nf_id = f"NFCAB-{estab_nf}-{seqnota_nf}"
                            filial_nf = _filial(cur, estab_nf)
                            agrfin = _nfcab_agrfin(cur, estab_nf, seqnota_nf)
                            cur.execute(
                                """SELECT ni.ITEM, ni.QUANTIDADE, ni.VALORTOTAL, ia.DESCRICAO, ia.UNIDADE
                                   FROM VIASOFT.NFITEM ni
                                   LEFT JOIN VIASOFT.ITEMAGRO ia ON ia.ITEM = ni.ITEM
                                   WHERE ni.ESTAB=:e AND ni.SEQNOTA=:s""",
                                e=estab_nf, s=seqnota_nf,
                            )
                            itens = []
                            for row in cur.fetchall():
                                desc = f"{row[0]} - {row[3]}" if row[3] else str(row[0])
                                itens.append({
                                    "item": row[0],
                                    "quantidade": float(row[1]) if row[1] else 0,
                                    "valor": float(row[2]) if row[2] else 0,
                                    "descricao": desc,
                                    "unidade": row[4],
                                })
                            if not any(n["id"] == nf_id for n in nodes):
                                nodes.append({
                                    "id": nf_id,
                                    "type": "NFCAB",
                                    "label": (
                                        f"<b>Nota Fiscal</b>\nNota: {nota}  Seq.: {seqnota_nf}"
                                        f"\nSérie: {serie}  Estab: {estab_nf}"
                                        + (f"\nEmissão: {dt_nf.strftime('%d/%m/%Y')}" if dt_nf else "")
                                        + f"\nValor: {_fmtval(valor_nf)}"
                                    ),
                                    "data": {
                                        "estab": estab_nf, "nota": nota, "serie": serie,
                                        "seqnota": seqnota_nf,
                                        "filial": filial_nf.get("reduzido", str(estab_nf)),
                                        "emissao": dt_nf.strftime("%d/%m/%Y") if dt_nf else None,
                                        "valor": float(valor_nf) if valor_nf else 0,
                                        "agrfin": agrfin,
                                        "itens": itens,
                                    },
                                })
                            edges.append({"from": nf_id, "to": prvdacar_id, "label": "cartão"})

                            cur.execute(
                                """SELECT DISTINCT p.ESTAB, p.SERIE, p.NUMERO
                                   FROM VIASOFT.PEDITEMNFITEM p
                                   WHERE p.ESTABNOTA=:en AND p.SEQNOTA=:sn""",
                                en=estab_nf, sn=seqnota_nf,
                            )
                            for estab_p, serie_p, num_p in cur.fetchall():
                                ped_id = f"PEDCAB-{estab_p}-{serie_p}-{num_p}"
                                cur.execute(
                                    """SELECT PESSOA, DTEMISSAO, STATUS, USERID
                                       FROM VIASOFT.PEDCAB
                                       WHERE ESTAB=:e AND SERIE=:s AND NUMERO=:n""",
                                    e=estab_p, s=serie_p, n=num_p,
                                )
                                ped = cur.fetchone()
                                if not ped:
                                    continue
                                if ped[0]:
                                    pessoa_numerocm = ped[0]
                                pessoa_info = _pessoa(cur, ped[0]) if ped[0] else {}
                                filial_ped = _filial(cur, estab_p)
                                if not any(n["id"] == ped_id for n in nodes):
                                    pgto = _pedcab_pgto(cur, estab_p, serie_p, num_p)
                                    nodes.append({
                                        "id": ped_id,
                                        "type": "PEDCAB",
                                        "label": (
                                            f"<b>Pedido de Venda</b>\nPedido: {serie_p}/{num_p}  Estab: {estab_p}"
                                            + (f"\nEmissão: {ped[1].strftime('%d/%m/%Y')}" if ped[1] else "")
                                        ),
                                        "data": {
                                            "estab": estab_p, "serie": serie_p, "numero": num_p,
                                            "filial": filial_ped.get("reduzido", str(estab_p)),
                                            "pessoa": pessoa_info.get("nome", str(ped[0])),
                                            "emissao": ped[1].strftime("%d/%m/%Y") if ped[1] else None,
                                            "status": resolve(cur, "PEDCAB", "STATUS", ped[2]),
                                            "userid": ped[3],
                                            "pgto": pgto,
                                        },
                                    })
                                edges.append({"from": ped_id, "to": nf_id, "label": "fatura em"})

            elif duprec_orig:
                # Origem: baixa de PDUPREC via cartão — mostra dup. original upstream
                duprec_orig_norm = _norm_duprec(duprec_orig)
                orig_id = f"PDUPREC-{emp}-{duprec_orig_norm}"
                if not any(n["id"] == orig_id for n in nodes):
                    cur.execute(
                        """SELECT VALOR, DTEMISSAO, DTVENCTO
                           FROM VIASOFT.PDUPREC
                           WHERE EMPRESA=:e AND REPLACE(DUPREC,' ','')=:d""",
                        e=emp, d=duprec_orig_norm,
                    )
                    orig_dup = cur.fetchone()
                    if orig_dup:
                        vlr_o, em_o, venc_o = orig_dup
                        nodes.append({
                            "id":   orig_id,
                            "type": "PDUPREC",
                            "label": (
                                f"<b>Duplicata a Receber</b>\nDup: {duprec_orig_norm}"
                                + (f"\nVencto: {venc_o.strftime('%d/%m/%Y')}" if venc_o else "")
                                + f"\nValor: {_fmtval(vlr_o)}"
                            ),
                            "data": {
                                "empresa": emp, "duprec": duprec_orig_norm,
                                "emissao": em_o.strftime("%d/%m/%Y") if em_o else None,
                                "vencto":  venc_o.strftime("%d/%m/%Y") if venc_o else None,
                                "valor":   float(vlr_o) if vlr_o else 0,
                            },
                        })
                cur.execute(
                    """SELECT r.SEQRECBTO, r.CARTAO, r.VALOR, r.AUTORIZACAO, r.NSU, r.NROCARTAO,
                              pn.DESCRICAO as CARTAO_DESC,
                              b.DESCRICAO as BANDEIRA_DESC
                       FROM VIASOFT.PRDURECAR r
                       LEFT JOIN VIASOFT.PNOMECAR pn ON pn.CARTAO = r.CARTAO
                       LEFT JOIN VIASOFT.PCONFCAR pc ON pc.EMPRESA=r.EMPRESA AND pc.CARTAO=r.CARTAO
                       LEFT JOIN VIASOFT.BANDEIRACARTAO b ON b.IDBANDEIRACARTAO=pc.ID_CARTAO
                       WHERE r.EMPRESA=:e AND REPLACE(r.DUPRECADM,' ','')=:d AND ROWNUM=1""",
                    e=emp, d=duprec_norm,
                )
                prd = cur.fetchone()
                if prd:
                    seqrec_prd, cartao_prd, valor_prd, autorizacao_prd, nsu_prd, nrocartao_prd, cartao_desc_prd, bandeira_prd = prd
                    car_id = f"PRDURECAR-{emp}-{duprec_orig_norm}-{seqrec_prd}-{cartao_prd}"
                    if not any(n["id"] == car_id for n in nodes):
                        cartao_label_prd = f"{cartao_prd} - {_trunc(cartao_desc_prd, 22)}" if cartao_desc_prd else str(cartao_prd)
                        nodes.append({
                            "id":   car_id,
                            "type": "PRDURECAR",
                            "label": (
                                f"<b>Cartão de Crédito</b>"
                                + f"\n{cartao_label_prd}"
                                + (f"\nNº Cartão: {nrocartao_prd}" if nrocartao_prd else "")
                                + f"\nValor: {_fmtval(valor_prd)}"
                            ),
                            "data": {
                                "cartao":      cartao_label_prd,
                                "bandeira":    bandeira_prd,
                                "valor":       float(valor_prd) if valor_prd else 0,
                                "autorizacao": autorizacao_prd,
                                "nsu":         nsu_prd,
                                "nrocartao":   nrocartao_prd,
                                "duprecadm":   duprec_norm,
                            },
                        })
                    edges.append({"from": orig_id, "to": car_id, "label": "cartão"})
                    edges.append({"from": car_id, "to": dup_id, "label": "dup. adm."})

    # ── DOWNSTREAM: baixas da duplicata
    cur.execute(
        """SELECT SEQRECBTO, DTRECBTO, USERID, VALOR, TIPOREC, TIPOACERTO,
                  RECIBO, ESTABBAIXA, NRORECIBO, ROTINA, ESTABRECIBO
           FROM VIASOFT.PRDUPREC
           WHERE EMPRESA=:emp AND REPLACE(DUPREC,' ','')=:dup
           ORDER BY SEQRECBTO""",
        emp=emp, dup=duprec_norm,
    )
    baixas = cur.fetchall()

    for bx in baixas:
        seqrec, dtrecbto, userid_bx, valor_bx, tiporec, tipoacerto, recibo, estabbaixa, nrorecibo, rotina_id, estabrecibo = bx
        tipoacerto_desc = resolve(cur, "PRDUPREC", "TIPOACERTO", tipoacerto)
        tiporec_desc = _TIPOREC.get(tiporec, tiporec) if tiporec else None
        rotina_desc = _rotina(cur, rotina_id)
        filial_baixa  = _filial(cur, estabbaixa)  if estabbaixa  else {}
        filial_recibo = _filial(cur, estabrecibo) if estabrecibo else {}
        recibo_data   = _recibo(cur, estabrecibo or emp, nrorecibo)
        bx_id = f"PRDUPREC-{emp}-{duprec_norm}-{seqrec}"
        nodes.append({
            "id": bx_id,
            "type": "PRDUPREC",
            "label": (
                f"<b>Baixa de Duplicata</b>\nBaixa: #{seqrec}  Forma: {tipoacerto_desc or ''}"
                + (f"  · {tiporec_desc}" if tiporec_desc else "")
                + (f"\nData: {dtrecbto.strftime('%d/%m/%Y')}" if dtrecbto else "")
                + f"\nValor: {_fmtval(valor_bx)}"
            ),
            "data": {
                "seqrecbto": seqrec,
                "data": dtrecbto.strftime("%d/%m/%Y") if dtrecbto else None,
                "userid": userid_bx,
                "valor": float(valor_bx) if valor_bx else 0,
                "tiporec": tiporec_desc,
                "forma": tipoacerto_desc,
                "rotina": rotina_desc,
                "estab_baixa": filial_baixa.get("reduzido") or str(estabbaixa) if estabbaixa else None,
                "nrorecibo": nrorecibo,
                "estab_recibo": filial_recibo.get("reduzido") or str(estabrecibo) if estabrecibo else None,
                "recibo": recibo,
                "recibo_data": recibo_data,
            },
        })
        edges.append({"from": dup_id, "to": bx_id, "label": tipoacerto_desc or "baixa"})

        # PRDUPRED → PLANCA → PPORTADO
        cur.execute(
            """SELECT pd.DTLANCA, pd.SEQLANCA, pd.VALOR
               FROM VIASOFT.PRDUPRED pd
               WHERE pd.EMPRESA=:emp AND REPLACE(pd.DUPREC,' ','')=:dup AND pd.SEQRECBTO=:seq""",
            emp=emp, dup=duprec_norm, seq=seqrec,
        )
        for dtlanca, seqlanca, val_pd in cur.fetchall():
            lanca_node = _build_planca_node(cur, emp, dtlanca, seqlanca)
            if lanca_node:
                nodes.append(lanca_node)
                edges.append({"from": bx_id, "to": lanca_node["id"], "label": "dinheiro/PIX/TED"})

        # PRDURECM → CONTAMOVLAN (PRDURECM não tem ESTAB direto; usa ESTABBAIXA)
        cur.execute(
            """SELECT NUMEROCM, SEQCM, ESTABBAIXA, VALOR
               FROM VIASOFT.PRDURECM
               WHERE EMPRESA=:emp AND REPLACE(DUPREC,' ','')=:dup AND SEQRECBTO=:seq""",
            emp=emp, dup=duprec_norm, seq=seqrec,
        )
        for numerocm, seqcm, estab_cm, val_cm in cur.fetchall():
            cml_node = _build_contamovlan_node(cur, numerocm, seqcm, estab_cm, val_cm)
            if not any(n["id"] == cml_node["id"] for n in nodes):
                nodes.append(cml_node)
            edges.append({"from": bx_id, "to": cml_node["id"], "label": "conta movimento"})

        # PRDURECH → PCHEQREC
        cur.execute(
            """SELECT ch.BANCO, ch.NROCHEQUE, ch.VLRCHEQREC,
                      pcr.ESTABCLIENTE, pcr.CLIENTE, pcr.EMITENTE
               FROM VIASOFT.PRDURECH ch
               LEFT JOIN VIASOFT.PCHEQREC pcr
                 ON pcr.EMPRESA = ch.EMPRESA
                AND pcr.BANCO = ch.BANCO
                AND pcr.NROCHEQUE = ch.NROCHEQUE
                AND ROWNUM = 1
               WHERE ch.EMPRESA=:emp AND REPLACE(ch.DUPREC,' ','')=:dup AND ch.SEQRECBTO=:seq""",
            emp=emp, dup=duprec_norm, seq=seqrec,
        )
        for banco_ch, nrocheque, vlr_ch, estab_cli, cliente_ch, emitente_ch in cur.fetchall():
            ch_node, lanca_node = _cheqrec_node(cur, emp, banco_ch, estab_cli, cliente_ch, emitente_ch, nrocheque, vlr_ch)
            ch_id = ch_node["id"]
            if not any(n["id"] == ch_id for n in nodes):
                nodes.append(ch_node)
            edges.append({"from": bx_id, "to": ch_id, "label": "cheque"})
            if lanca_node:
                if not any(n["id"] == lanca_node["id"] for n in nodes):
                    nodes.append(lanca_node)
                edges.append({"from": ch_id, "to": lanca_node["id"], "label": "compensação"})

        # PRDUREDUP → PDUPREC (baixa em duplicata)
        cur.execute(
            """SELECT DUPRECGER, VALOR
               FROM VIASOFT.PRDUREDUP
               WHERE EMPRESA=:emp AND REPLACE(DUPREC,' ','')=:dup AND SEQRECBTO=:seq""",
            emp=emp, dup=duprec_norm, seq=seqrec,
        )
        for duprecger, val_dd in cur.fetchall():
            dd_id = f"PDUPREC-{emp}-{_norm_duprec(duprecger)}"
            if not any(n["id"] == dd_id for n in nodes):
                nodes.append({
                    "id": dd_id,
                    "type": "PDUPREC",
                    "label": f"Duplicata\n{duprecger}",
                    "data": {"empresa": emp, "duprec": duprecger,
                              "valor": float(val_dd) if val_dd else 0},
                })
            edges.append({"from": bx_id, "to": dd_id, "label": "baixa em dup"})

        # PRDURECAR (cartão)
        cur.execute(
            """SELECT r.CARTAO, r.VALOR, r.AUTORIZACAO, r.NSU, r.NROCARTAO,
                      pn.DESCRICAO as CARTAO_DESC,
                      b.DESCRICAO as BANDEIRA_DESC
               FROM VIASOFT.PRDURECAR r
               LEFT JOIN VIASOFT.PNOMECAR pn ON pn.CARTAO = r.CARTAO
               LEFT JOIN VIASOFT.PCONFCAR pc ON pc.EMPRESA=r.EMPRESA AND pc.CARTAO=r.CARTAO
               LEFT JOIN VIASOFT.BANDEIRACARTAO b ON b.IDBANDEIRACARTAO=pc.ID_CARTAO
               WHERE r.EMPRESA=:emp AND REPLACE(r.DUPREC,' ','')=:dup AND r.SEQRECBTO=:seq""",
            emp=emp, dup=duprec_norm, seq=seqrec,
        )
        for cartao, val_car, autorizacao, nsu, nrocartao, cartao_desc, bandeira_desc in cur.fetchall():
            # conta parcelas via PACECARTAO antes de montar o nó
            cur.execute(
                """SELECT COUNT(*) FROM VIASOFT.PACECARTAO
                   WHERE EMPRESA=:emp AND REPLACE(DUPREC,' ','')=:dup""",
                emp=emp, dup=duprec_norm,
            )
            nroparcelas_car = cur.fetchone()[0] or 1
            car_id = f"PRDURECAR-{emp}-{duprec_norm}-{seqrec}-{cartao}"
            cartao_label_car = f"{cartao} - {_trunc(cartao_desc, 22)}" if cartao_desc else str(cartao)
            nodes.append({
                "id": car_id,
                "type": "PRDURECAR",
                "label": (
                    f"<b>Cartão de Crédito</b>"
                    + f"\n{cartao_label_car}"
                    + (f"  {nroparcelas_car}x" if nroparcelas_car > 1 else "")
                    + (f"\nNº Cartão: {nrocartao}" if nrocartao else "")
                    + f"\nValor: {_fmtval(val_car)}"
                ),
                "data": {
                    "cartao":      cartao_label_car,
                    "bandeira":    bandeira_desc,
                    "nroparcelas": nroparcelas_car,
                    "valor":       float(val_car) if val_car else 0,
                    "autorizacao": autorizacao,
                    "nsu":         nsu,
                    "nrocartao":   nrocartao,
                },
            })
            edges.append({"from": bx_id, "to": car_id, "label": "cartão"})

            # Dups administratoras: PACECARTAO.DUPREC = dup original → DUPRECADM por parcela
            cur.execute(
                """SELECT DUPRECADM, SEQUENCIA, PARCELA, VALOR
                   FROM VIASOFT.PACECARTAO
                   WHERE EMPRESA=:emp AND REPLACE(DUPREC,' ','')=:dup
                   ORDER BY SEQUENCIA""",
                emp=emp, dup=duprec_norm,
            )
            pac_rows = cur.fetchall()
            parc_total = len(pac_rows)
            existing_ids = {n["id"] for n in nodes}
            for duprecadm, seq_pac, parcela, vlr_p in pac_rows:
                if not duprecadm:
                    continue
                admin_dup_id = f"PDUPREC-{emp}-{_norm_duprec(duprecadm)}"
                if admin_dup_id not in existing_ids:
                    adm_nodes, adm_edges, _ = _trace_pduprec(cur, emp, duprecadm, skip_pessoa=True, skip_upstream=True)
                    for n in adm_nodes:
                        if n["id"] not in existing_ids:
                            nodes.append(n)
                            existing_ids.add(n["id"])
                    edges.extend(adm_edges)
                edge_label = f"parcela {parcela}" if parc_total > 1 else "dup. adm."
                edges.append({"from": car_id, "to": admin_dup_id, "label": edge_label})

    # ── PESSOA: nó inicial (leftmost) — omitido em dups administratoras
    if not skip_pessoa:
        pessoa_det = _pessoa_detail(cur, pessoa_numerocm)
        if pessoa_det:
            pes_id = f"PESSOA-{pessoa_numerocm}"
            if not any(n["id"] == pes_id for n in nodes):
                nodes.append({
                    "id": pes_id,
                    "type": "PESSOA",
                    "label": _pessoa_label(pessoa_det),
                    "data": pessoa_det,
                })
            pedcab_ids  = [n["id"] for n in nodes if n["type"] == "PEDCAB"]
            origem_ids  = [n["id"] for n in nodes if n["type"] in ("CTRC", "CONHE", "CONTRATO", "RPA")]
            if pedcab_ids:
                for pid in pedcab_ids:
                    edges.append({"from": pes_id, "to": pid, "label": "cliente"})
            elif origem_ids:
                for oid in origem_ids:
                    edges.append({"from": pes_id, "to": oid, "label": "cliente"})
            else:
                edges.append({"from": pes_id, "to": dup_id, "label": "cliente"})

    return nodes, edges, None


# ─── trace por PDUPPAGA ──────────────────────────────────────────────────────

def _trace_pduppaga(cur, empresa, duppag_raw):
    nodes = []
    edges = []
    duppag_norm = _norm_duprec(duppag_raw)

    cur.execute(
        """SELECT d.EMPRESA, d.ESTABFORNECEDOR, d.FORNECEDOR, d.DUPPAG,
                  d.VALOR, d.DTEMISSAO, d.DTVENCTO, d.QUITADA,
                  d.SITUACAO, d.HISTORICO,
                  d.ANALITICA, d.ESTABANALITICA,
                  d.USERID, d.BANCO
           FROM VIASOFT.PDUPPAGA d
           WHERE d.EMPRESA = :emp
             AND REPLACE(d.DUPPAG,' ','') = :dup""",
        emp=empresa, dup=duppag_norm,
    )
    dup = cur.fetchone()
    if not dup:
        return None, None, "Duplicata a Pagar não encontrada"

    (emp, estab_forn, fornecedor, duppag, valor, dtemissao, dtvencto, quitada,
     situacao, historico, analitica, estab_analitica, userid, banco_dup) = dup
    duppag_real = duppag

    banco_desc = _banco(cur, banco_dup)
    forn_info  = _pessoa(cur, fornecedor)

    dup_id = f"PDUPPAGA-{emp}-{duppag_norm}"
    nodes.append({
        "id": dup_id,
        "type": "PDUPPAGA",
        "label": (
            f"<b>Duplicata a Pagar</b>\nDup: {duppag_real}  Emp: {emp}"
            + (f"\nEmissão: {dtemissao.strftime('%d/%m/%Y')}" if dtemissao else "")
            + (f"\nVencto: {dtvencto.strftime('%d/%m/%Y')}" if dtvencto else "")
            + f"\nValor: {_fmtval(valor)}"
        ),
        "data": {
            "empresa": emp,
            "duppag": duppag_real,
            "fornecedor": forn_info.get("nome", str(fornecedor)),
            "valor": float(valor) if valor else 0,
            "emissao": dtemissao.strftime("%d/%m/%Y") if dtemissao else None,
            "vencto": dtvencto.strftime("%d/%m/%Y") if dtvencto else None,
            "quitada": quitada,
            "situacao": _situacao(cur, situacao),
            "banco": banco_desc,
            "analitica": _analitica(cur, estab_analitica or emp, analitica),
            "userid": userid,
            "historico": historico,
        },
    })

    # ── UPSTREAM: NF → NFCABAGRFIN → AGRFINDUPPAG → PDUPPAGA
    cur.execute(
        """SELECT afd.SEQPAGAMENTO
           FROM VIASOFT.AGRFINDUPPAG afd
           WHERE afd.ESTABFORNECEDOR = :ef AND afd.FORNECEDOR = :f
             AND REPLACE(afd.DUPPAG,' ','') = :dup""",
        ef=estab_forn, f=fornecedor, dup=duppag_norm,
    )
    seqs = [r[0] for r in cur.fetchall()]

    nf_seen = set()
    for seq_pag in seqs:
        cur.execute(
            "SELECT ESTAB, SEQNOTA FROM VIASOFT.NFCABAGRFIN WHERE SEQPAGAMENTO=:s",
            s=seq_pag,
        )
        for estab_nf, seqnota in cur.fetchall():
            if (estab_nf, seqnota) in nf_seen:
                continue
            nf_seen.add((estab_nf, seqnota))
            cur.execute(
                """SELECT NOTA, SERIE, DTEMISSAO, VALOR
                   FROM VIASOFT.NFCAB WHERE ESTAB=:e AND SEQNOTA=:s""",
                e=estab_nf, s=seqnota,
            )
            nf = cur.fetchone()
            if not nf:
                continue
            nota, serie, dt_nf, valor_nf = nf
            nf_id = f"NFCAB-{estab_nf}-{seqnota}"
            filial_nf = _filial(cur, estab_nf)
            nodes.append({
                "id": nf_id,
                "type": "NFCAB",
                "label": (
                    f"<b>Nota Fiscal</b>\nNota: {nota}  Seq.: {seqnota}"
                    f"\nSérie: {serie}  Estab: {estab_nf}"
                    + (f"\nEmissão: {dt_nf.strftime('%d/%m/%Y')}" if dt_nf else "")
                    + f"\nValor: {_fmtval(valor_nf)}"
                ),
                "data": {
                    "estab": estab_nf,
                    "nota": nota,
                    "serie": serie,
                    "seqnota": seqnota,
                    "filial": filial_nf.get("reduzido", str(estab_nf)),
                    "emissao": dt_nf.strftime("%d/%m/%Y") if dt_nf else None,
                    "valor": float(valor_nf) if valor_nf else 0,
                },
            })
            edges.append({"from": nf_id, "to": dup_id, "label": "gera dup. pagar"})

    # ── UPSTREAM: documentos de origem alternativos (CTRC / CONHE / CONTRATO / RPA)
    _add_doc_origem_nodes(cur, seqs, dup_id, "gera dup. pagar", nodes, edges)

    # ── DOWNSTREAM: baixas da duplicata a pagar
    cur.execute(
        """SELECT SEQPAGTODU, DTPAGTO, USERID, VALOR, TIPOACERTO, TIPOPAG, ESTABBAIXA,
                  NRORECIBO, ESTABRECIBO
           FROM VIASOFT.PPDUPPAG
           WHERE EMPRESA=:emp AND ESTABFORNECEDOR=:ef AND FORNECEDOR=:f
             AND REPLACE(DUPPAG,' ','')=:dup
           ORDER BY SEQPAGTODU""",
        emp=emp, ef=estab_forn, f=fornecedor, dup=duppag_norm,
    )
    baixas = cur.fetchall()

    for bx in baixas:
        seqpag, dtpagto, userid_bx, valor_bx, tipoacerto, tipopag, estabbaixa, nrorecibo_bx, estabrecibo_bx = bx
        tipoacerto_desc = resolve(cur, "PPDUPPAG", "TIPOACERTO", tipoacerto)
        tipopag_desc = _TIPOPAG.get(tipopag, tipopag) if tipopag else None
        filial_bx  = _filial(cur, estabbaixa) if estabbaixa else {}
        recibo_bx  = _recibo(cur, estabrecibo_bx or emp, nrorecibo_bx) if nrorecibo_bx else None
        bx_id = f"PPDUPPAG-{emp}-{duppag_norm}-{seqpag}"
        nodes.append({
            "id": bx_id,
            "type": "PPDUPPAG",
            "label": (
                f"<b>Baixa Dup. Pagar</b>\nBaixa: #{seqpag}  Forma: {tipoacerto_desc or tipoacerto}"
                + (f"  · {tipopag_desc}" if tipopag_desc else "")
                + (f"\nData: {dtpagto.strftime('%d/%m/%Y')}" if dtpagto else "")
                + f"\nValor: {_fmtval(valor_bx)}"
            ),
            "data": {
                "seqpagtodu": seqpag,
                "data": dtpagto.strftime("%d/%m/%Y") if dtpagto else None,
                "userid": userid_bx,
                "valor": float(valor_bx) if valor_bx else 0,
                "tipopag": tipopag_desc,
                "forma": tipoacerto_desc or tipoacerto,
                "estab_baixa": filial_bx.get("reduzido") or str(estabbaixa) if estabbaixa else None,
                "nrorecibo": nrorecibo_bx,
                "recibo_data": recibo_bx,
            },
        })
        edges.append({"from": dup_id, "to": bx_id, "label": tipoacerto_desc or tipoacerto or "baixa"})

        # DI → PPDUPPAD → PLANCA
        cur.execute(
            """SELECT DTLANCA, SEQLANCA
               FROM VIASOFT.PPDUPPAD
               WHERE EMPRESA=:emp AND ESTABFORNECEDOR=:ef AND FORNECEDOR=:f
                 AND REPLACE(DUPPAG,' ','')=:dup AND SEQPAGTODU=:seq""",
            emp=emp, ef=estab_forn, f=fornecedor, dup=duppag_norm, seq=seqpag,
        )
        for dtlanca, seqlanca in cur.fetchall():
            lanca_node = _build_planca_node(cur, emp, dtlanca, seqlanca)
            if lanca_node and not any(n["id"] == lanca_node["id"] for n in nodes):
                nodes.append(lanca_node)
            if lanca_node:
                edges.append({"from": bx_id, "to": lanca_node["id"], "label": "dinheiro/PIX/TED"})

        # CE → PPADUCHE → PCHEQEMI
        cur.execute(
            """SELECT PORTADOR, NROCHEQUE, SERIE, VLRCHEQUEP
               FROM VIASOFT.PPADUCHE
               WHERE EMPRESA=:emp AND ESTABFORNECEDOR=:ef AND FORNECEDOR=:f
                 AND REPLACE(DUPPAG,' ','')=:dup AND SEQPAGTODU=:seq""",
            emp=emp, ef=estab_forn, f=fornecedor, dup=duppag_norm, seq=seqpag,
        )
        for portador_ch, nrocheque, serie_ch, vlr_ch in cur.fetchall():
            ch_node = _cheqemi_node(cur, emp, portador_ch, nrocheque, serie_ch, vlr_ch)
            if not any(n["id"] == ch_node["id"] for n in nodes):
                nodes.append(ch_node)
            edges.append({"from": bx_id, "to": ch_node["id"], "label": "cheque emitido"})

        # CT → PPADUCHR → PCHEQREC (cheque de terceiro usado como pagamento)
        cur.execute(
            """SELECT ESTABCLIENTE, BANCO, EMITENTE, NROCHEQUE, CLIENTE, VLRCHEQUE
               FROM VIASOFT.PPADUCHR
               WHERE EMPRESA=:emp AND ESTABFORNECEDOR=:ef AND FORNECEDOR=:f
                 AND REPLACE(DUPPAG,' ','')=:dup AND SEQPAGTODU=:seq""",
            emp=emp, ef=estab_forn, f=fornecedor, dup=duppag_norm, seq=seqpag,
        )
        for estab_cli, banco_ch, emitente, nrocheque, cliente, vlr_ch in cur.fetchall():
            ch_node, lanca_node = _cheqrec_node(cur, emp, banco_ch, estab_cli, cliente, emitente, nrocheque, vlr_ch)
            ch_id = ch_node["id"]
            if not any(n["id"] == ch_id for n in nodes):
                nodes.append(ch_node)
            edges.append({"from": bx_id, "to": ch_id, "label": "cheque terceiro"})
            if lanca_node:
                if not any(n["id"] == lanca_node["id"] for n in nodes):
                    nodes.append(lanca_node)
                edges.append({"from": ch_id, "to": lanca_node["id"], "label": "compensação"})

        # CM → PPADUCM → CONTAMOVLAN
        cur.execute(
            """SELECT NUMEROCM, SEQCM, VALOR
               FROM VIASOFT.PPADUCM
               WHERE EMPRESA=:emp AND ESTABFORNECEDOR=:ef AND FORNECEDOR=:f
                 AND REPLACE(DUPPAG,' ','')=:dup AND SEQPAGTODU=:seq""",
            emp=emp, ef=estab_forn, f=fornecedor, dup=duppag_norm, seq=seqpag,
        )
        for numerocm, seqcm, val_cm in cur.fetchall():
            cml_node = _build_contamovlan_node(cur, numerocm, seqcm, None, val_cm)
            if not any(n["id"] == cml_node["id"] for n in nodes):
                nodes.append(cml_node)
            edges.append({"from": bx_id, "to": cml_node["id"], "label": "conta movimento"})

        # TROCO → PLANCA (dinheiro) ou PCHEQREC (cheque)
        cur.execute(
            """SELECT t.SEQLANCA, t.DTLANCA, t.BANCO, t.ESTABCLIENTE,
                      t.CLIENTE, t.EMITENTE, t.NROCHEQUE
               FROM VIASOFT.PPDUPTROCO t
               WHERE t.EMPRESA=:emp AND t.ESTABFORNECEDOR=:ef AND t.FORNECEDOR=:f
                 AND REPLACE(t.DUPPAG,' ','')=:dup AND t.SEQPAGTODU=:seq""",
            emp=emp, ef=estab_forn, f=fornecedor, dup=duppag_norm, seq=seqpag,
        )
        for seqlanca_t, dtlanca_t, banco_t, estab_cli_t, cliente_t, emitente_t, nrocheque_t in cur.fetchall():
            if dtlanca_t and seqlanca_t:
                lanca_node = _build_planca_node(cur, emp, dtlanca_t, seqlanca_t)
                if lanca_node and not any(n["id"] == lanca_node["id"] for n in nodes):
                    nodes.append(lanca_node)
                if lanca_node:
                    edges.append({"from": bx_id, "to": lanca_node["id"], "label": "troco"})
            if nrocheque_t:
                ch_node, lanca_node = _cheqrec_node(cur, emp, banco_t, estab_cli_t, cliente_t, emitente_t, nrocheque_t, None)
                ch_id = ch_node["id"]
                if not any(n["id"] == ch_id for n in nodes):
                    nodes.append(ch_node)
                edges.append({"from": bx_id, "to": ch_id, "label": "troco cheque"})
                if lanca_node:
                    if not any(n["id"] == lanca_node["id"] for n in nodes):
                        nodes.append(lanca_node)
                    edges.append({"from": ch_id, "to": lanca_node["id"], "label": "compensação"})

        # PPDUPPADUP → PDUPPAGA agrupadora
        cur.execute(
            """SELECT EMPRESAGER, ESTABFORNGER, FORNECEDORGER, DUPPAGGER, VALOR
               FROM VIASOFT.PPDUPPADUP
               WHERE EMPRESA=:emp AND ESTABFORNECEDOR=:ef AND FORNECEDOR=:f
                 AND REPLACE(DUPPAG,' ','')=:dup AND SEQPAGTODU=:seq""",
            emp=emp, ef=estab_forn, f=fornecedor, dup=duppag_norm, seq=seqpag,
        )
        for emp_ger, estab_forn_ger, forn_ger, duppag_ger, val_dd in cur.fetchall():
            dd_id = f"PDUPPAGA-{emp_ger}-{_norm_duprec(duppag_ger)}"
            if not any(n["id"] == dd_id for n in nodes):
                nodes.append({
                    "id": dd_id,
                    "type": "PDUPPAGA",
                    "label": f"<b>Duplicata a Pagar</b>\nDup: {duppag_ger}\nValor: {_fmtval(val_dd)}",
                    "data": {"empresa": emp_ger, "duppag": duppag_ger,
                             "valor": float(val_dd) if val_dd else 0},
                })
            edges.append({"from": bx_id, "to": dd_id, "label": "agrupada em"})

    # ── PESSOA: nó inicial (fornecedor)
    pessoa_det = _pessoa_detail(cur, fornecedor)
    if pessoa_det:
        pes_id = f"PESSOA-{fornecedor}"
        if not any(n["id"] == pes_id for n in nodes):
            nodes.append({
                "id": pes_id,
                "type": "PESSOA",
                "label": _pessoa_label(pessoa_det),
                "data": pessoa_det,
            })
        nf_ids      = [n["id"] for n in nodes if n["type"] == "NFCAB"]
        origem_ids  = [n["id"] for n in nodes if n["type"] in ("CTRC", "CONHE", "CONTRATO", "RPA")]
        if nf_ids:
            for nid in nf_ids:
                edges.append({"from": pes_id, "to": nid, "label": "fornecedor"})
        elif origem_ids:
            for oid in origem_ids:
                edges.append({"from": pes_id, "to": oid, "label": "fornecedor"})
        else:
            edges.append({"from": pes_id, "to": dup_id, "label": "fornecedor"})

    return nodes, edges, None


# ─── helpers NF-e: cartão e PIX ──────────────────────────────────────────────

def _nfcab_cartao(cur, nodes, edges, seen_ids, estab, seqnota, nf_id):
    """NF-e → Cartão: AGRFINCARTAO → PRVDACAR → PACECARTAO → dup. administradora."""
    cur.execute(
        """SELECT ac.SEQPRVDACAR, p.EMPRESA, p.NROVDA, p.VALOR, p.NROPARCELAS, p.CARTAO,
                  p.AUTORIZACA, p.NSU, p.NROCARTAO, p.NOMEREDE,
                  pn.DESCRICAO as CARTAO_DESC,
                  b.DESCRICAO as BANDEIRA_DESC
           FROM VIASOFT.NFCABAGRFIN n
           JOIN VIASOFT.AGRFINCARTAO ac ON ac.SEQPAGAMENTO = n.SEQPAGAMENTO
           JOIN VIASOFT.PRVDACAR p ON p.SEQPRVDACAR = ac.SEQPRVDACAR
           LEFT JOIN VIASOFT.PNOMECAR pn ON pn.CARTAO = p.CARTAO
           LEFT JOIN VIASOFT.PCONFCAR pc ON pc.EMPRESA=p.EMPRESA AND pc.CARTAO=p.CARTAO
           LEFT JOIN VIASOFT.BANDEIRACARTAO b ON b.IDBANDEIRACARTAO=pc.ID_CARTAO
           WHERE n.ESTAB=:e AND n.SEQNOTA=:s""",
        e=estab, s=seqnota,
    )
    prvdacars = cur.fetchall()
    for seqprvdacar, empresa, nrovda, valor, nparcelas, cartao, autorizaca, nsu, nrocartao, nomerede, cartao_desc, bandeira_desc in prvdacars:
        prvdacar_id = f"PRVDACAR-{empresa}-{seqprvdacar}"
        if prvdacar_id not in seen_ids:
            parc = int(nparcelas) if nparcelas else 1
            cartao_label = f"{cartao} - {_trunc(cartao_desc, 22)}" if cartao_desc else str(cartao)
            nodes.append({
                "id":   prvdacar_id,
                "type": "PRVDACAR",
                "label": (
                    f"<b>Venda em Cartão</b>"
                    + f"\n{cartao_label}"
                    + f"\nNº Venda: {nrovda}" + (f"  {parc}x" if parc > 1 else "")
                    + (f"\nNº Cartão: {nrocartao}" if nrocartao else "")
                    + f"\nValor: {_fmtval(valor)}"
                ),
                "data": {
                    "empresa":     empresa,
                    "nrovda":      nrovda,
                    "valor":       float(valor) if valor else 0,
                    "nroparcelas": parc,
                    "cartao":      cartao_label,
                    "bandeira":    bandeira_desc,
                    "autorizacao": autorizaca,
                    "nsu":         nsu,
                    "nrocartao":   nrocartao,
                    "nomerede":    nomerede,
                },
            })
            seen_ids.add(prvdacar_id)
        edges.append({"from": nf_id, "to": prvdacar_id, "label": "cartão"})

        cur.execute(
            """SELECT DUPRECADM, SEQUENCIA, PARCELA, VALOR
               FROM VIASOFT.PACECARTAO
               WHERE EMPRESA=:emp AND SEQPRVDACAR=:seq
               ORDER BY SEQUENCIA""",
            emp=empresa, seq=seqprvdacar,
        )
        parcelas = cur.fetchall()
        parc_total = int(nparcelas) if nparcelas else 1
        for duprecadm, seq, parcela, vlr_p in parcelas:
            admin_dup_id = f"PDUPREC-{empresa}-{_norm_duprec(duprecadm)}"
            if admin_dup_id not in seen_ids:
                adm_nodes, adm_edges, _ = _trace_pduprec(cur, empresa, duprecadm, skip_pessoa=True, skip_upstream=True)
                for n in adm_nodes:
                    if n["id"] not in seen_ids:
                        nodes.append(n)
                        seen_ids.add(n["id"])
                edges.extend(adm_edges)
            edge_label = f"parcela {parcela}" if parc_total > 1 else "dup. adm."
            edges.append({"from": prvdacar_id, "to": admin_dup_id, "label": edge_label})


def _nfcab_pix(cur, nodes, edges, seen_ids, estab, seqnota, nf_id):
    """NF-e → PIX: AGRFINCARTDIG → ACERCARTDIG → PLANCA."""
    cur.execute(
        """SELECT ac.IDACERCARTDIG, ac.CODCARTEIRADIGITAL, ac.NOMECARTEIRADIGITAL,
                  ac.EMPRESA, ac.DTLANCA, ac.SEQLANCA, ac.MODOPAGAMENTO
           FROM VIASOFT.NFCABAGRFIN n
           JOIN VIASOFT.AGRFINCARTDIG ad ON ad.SEQPAGAMENTO = n.SEQPAGAMENTO
           JOIN VIASOFT.ACERCARTDIG ac ON ac.IDACERCARTDIG = ad.IDACERCARTDIG
           WHERE n.ESTAB=:e AND n.SEQNOTA=:s""",
        e=estab, s=seqnota,
    )
    pix_rows = cur.fetchall()
    for idacer, codcart, nomecart, empresa, dtlanca, seqlanca, modo in pix_rows:
        pix_id = f"ACERCARTDIG-{idacer}"
        carteira = nomecart or codcart or "PIX"
        if pix_id not in seen_ids:
            nodes.append({
                "id":   pix_id,
                "type": "ACERCARTDIG",
                "label": (
                    f"<b>Pagamento PIX</b>\n{_trunc(carteira, 22)}"
                    + (f"\n{_trunc(modo, 22)}" if modo else "")
                ),
                "data": {
                    "codcarteiradigital":  codcart,
                    "nomecarteiradigital": nomecart,
                    "modopagamento":       modo,
                    "empresa":             empresa,
                },
            })
            seen_ids.add(pix_id)
        edges.append({"from": nf_id, "to": pix_id, "label": "PIX"})

        if dtlanca and seqlanca and empresa:
            lanca_node = _build_planca_node(cur, empresa, dtlanca, seqlanca)
            if lanca_node:
                if lanca_node["id"] not in seen_ids:
                    nodes.append(lanca_node)
                    seen_ids.add(lanca_node["id"])
                edges.append({"from": pix_id, "to": lanca_node["id"], "label": "lançamento"})


# ─── trace por NFCAB ─────────────────────────────────────────────────────────

def _trace_nfcab(cur, estab, seqnota):
    cur.execute(
        """SELECT NOTA, SERIE, DTEMISSAO, VALOR FROM VIASOFT.NFCAB
           WHERE ESTAB=:e AND SEQNOTA=:s""",
        e=estab, s=seqnota,
    )
    nf = cur.fetchone()
    if not nf:
        return None, None, "NF não encontrada"

    nota, serie, dt_nf, valor_nf = nf
    nf_id = f"NFCAB-{estab}-{seqnota}"
    filial_nf = _filial(cur, estab)
    agrfin = _nfcab_agrfin(cur, estab, seqnota)

    cur.execute(
        """SELECT ni.ITEM, ni.QUANTIDADE, ni.VALORTOTAL, ia.DESCRICAO, ia.UNIDADE
           FROM VIASOFT.NFITEM ni
           LEFT JOIN VIASOFT.ITEMAGRO ia ON ia.ITEM = ni.ITEM
           WHERE ni.ESTAB=:e AND ni.SEQNOTA=:s""",
        e=estab, s=seqnota,
    )
    itens = []
    for row in cur.fetchall():
        desc = f"{row[0]} - {row[3]}" if row[3] else str(row[0])
        itens.append({
            "item": row[0], "quantidade": float(row[1]) if row[1] else 0,
            "valor": float(row[2]) if row[2] else 0,
            "descricao": desc, "unidade": row[4],
        })

    nf_node = {
        "id": nf_id,
        "type": "NFCAB",
        "label": (
            f"<b>Nota Fiscal</b>\nNota: {nota}  Seq.: {seqnota}"
            f"\nSérie: {serie}  Estab: {estab}"
            + (f"\nEmissão: {dt_nf.strftime('%d/%m/%Y')}" if dt_nf else "")
            + f"\nValor: {_fmtval(valor_nf)}"
        ),
        "data": {
            "estab": estab, "nota": nota, "serie": serie, "seqnota": seqnota,
            "filial": filial_nf.get("reduzido", str(estab)),
            "emissao": dt_nf.strftime("%d/%m/%Y") if dt_nf else None,
            "valor": float(valor_nf) if valor_nf else 0,
            "agrfin": agrfin,
            "itens": itens,
        },
    }

    all_nodes = [nf_node]
    all_edges = []
    seen_ids = {nf_id}

    def _merge(sub_nodes, sub_edges):
        for n in sub_nodes:
            if n["id"] not in seen_ids:
                all_nodes.append(n)
                seen_ids.add(n["id"])
        all_edges.extend(sub_edges)

    # Caminho AR (duplicata a receber)
    cur.execute(
        """SELECT DISTINCT afd.ESTAB, afd.DUPREC
           FROM VIASOFT.NFCABAGRFIN nag
           JOIN VIASOFT.AGRFINDUPREC afd ON afd.SEQPAGAMENTO = nag.SEQPAGAMENTO
           WHERE nag.ESTAB=:e AND nag.SEQNOTA=:s""",
        e=estab, s=seqnota,
    )
    for estab_d, duprec in cur.fetchall():
        sub_nodes, sub_edges, err = _trace_pduprec(cur, estab_d, duprec)
        if not err:
            _merge(sub_nodes, sub_edges)

    # Caminho AP (duplicata a pagar)
    cur.execute(
        """SELECT DISTINCT afd.ESTABFORNECEDOR, afd.FORNECEDOR, afd.DUPPAG
           FROM VIASOFT.NFCABAGRFIN nag
           JOIN VIASOFT.AGRFINDUPPAG afd ON afd.SEQPAGAMENTO = nag.SEQPAGAMENTO
           WHERE nag.ESTAB=:e AND nag.SEQNOTA=:s""",
        e=estab, s=seqnota,
    )
    for estab_forn, forn, duppag in cur.fetchall():
        sub_nodes, sub_edges, err = _trace_pduppaga(cur, estab_forn, duppag)
        if not err:
            _merge(sub_nodes, sub_edges)

    # Caminho Cartão
    _nfcab_cartao(cur, all_nodes, all_edges, seen_ids, estab, seqnota, nf_id)

    # Caminho PIX
    _nfcab_pix(cur, all_nodes, all_edges, seen_ids, estab, seqnota, nf_id)

    if len(all_nodes) <= 1:
        return None, None, "Nenhum dado encontrado para esta NF"

    return all_nodes, all_edges, None


# ─── trace por PEDCAB ────────────────────────────────────────────────────────

def _trace_pedcab(cur, estab, serie, numero):
    cur.execute(
        "SELECT ESTAB FROM VIASOFT.PEDCAB WHERE ESTAB=:e AND SERIE=:s AND NUMERO=:n",
        e=estab, s=serie, n=numero,
    )
    if not cur.fetchone():
        return None, None, "Pedido não encontrado"

    cur.execute(
        """SELECT DISTINCT ESTABNOTA, SEQNOTA
           FROM VIASOFT.PEDITEMNFITEM
           WHERE ESTAB=:e AND SERIE=:s AND NUMERO=:n""",
        e=estab, s=serie, n=numero,
    )
    nfs = cur.fetchall()
    if not nfs:
        return None, None, "Nenhuma NF encontrada para este pedido"

    all_nodes, all_edges = [], []
    seen_ids = set()

    for estab_nf, seqnota in nfs:
        nodes, edges, err = _trace_nfcab(cur, estab_nf, seqnota)
        if err:
            continue
        for n in nodes:
            if n["id"] not in seen_ids:
                all_nodes.append(n)
                seen_ids.add(n["id"])
        all_edges.extend(edges)

    return all_nodes, all_edges, None


# ─── trace por CONTAMOVLAN ───────────────────────────────────────────────────

def _cheqemi_node(cur, empresa, portador, nrocheque, serie, vlr_fallback):
    cur.execute(
        """SELECT VALOR, DTEMISSAO, DTBOMPARA, FAVORECIDO, HISTORICO, HISTORICO2,
                  SITUACAO, DTLANCA, SEQLANCA, DTLANCATRANSF, SEQLANCATRANSF,
                  ESTABRECIBO, NRORECIBO
           FROM VIASOFT.PCHEQEMI
           WHERE EMPRESA=:e AND PORTADOR=:p AND NROCHEQUE=:n AND SERIE=:s""",
        e=empresa, p=portador, n=nrocheque, s=serie,
    )
    chq = cur.fetchone()
    port_info   = _portador(cur, empresa, portador) if portador else {}
    recibo_data = None
    if chq:
        (valor, dtemissao, dtbompara, favorecido, historico, historico2,
         situacao, dtlanca, seqlanca, dtlancatransf, seqlancatransf,
         estabrecibo, nrorecibo) = chq
        recibo_data = _recibo(cur, estabrecibo or empresa, nrorecibo) if nrorecibo else None
    else:
        valor = vlr_fallback
        dtemissao = dtbompara = favorecido = historico = historico2 = situacao = None
        dtlanca = seqlanca = dtlancatransf = seqlancatransf = None
    return {
        "id":   f"PCHEQEMI-{empresa}-{portador}-{nrocheque}-{serie}",
        "type": "PCHEQEMI",
        "label": (
            f"<b>Cheque Emitido</b>\nCheque: #{nrocheque}"
            + (f"\nSérie: {serie}" if serie else "")
            + (f"\nEmissão: {dtemissao.strftime('%d/%m/%Y')}" if dtemissao else "")
            + f"\nValor: {_fmtval(valor)}"
        ),
        "data": {
            "nrocheque":     nrocheque,
            "serie":         serie,
            "portador_desc": port_info.get("descricao"),
            "favorecido":    favorecido,
            "valor":         float(valor) if valor else 0,
            "emissao":       dtemissao.strftime("%d/%m/%Y") if dtemissao else None,
            "bom_para":      dtbompara.strftime("%d/%m/%Y") if dtbompara else None,
            "historico":     historico,
            "historico2":    historico2,
            "situacao":      situacao,
            "recibo_data":   recibo_data,
        },
    }


def _cheqrec_node(cur, empresa, banco, estab_cli, cliente, emitente, nrocheque, vlr_fallback):
    cur.execute(
        """SELECT VALOR, DTEMISSAO, DTBOMPARA, HISTORICO, PORTADOR,
                  DTLANCA, SEQLANCA, DTLANCATRAN, SEQLANCATRAN,
                  DTESTORNODEP, SEQESTORNODEP, ESTABRECIBO, NRORECIBO
           FROM VIASOFT.PCHEQREC
           WHERE EMPRESA=:e AND ESTABCLIENTE=:ec AND BANCO=:b
             AND EMITENTE=:em AND NROCHEQUE=:n AND CLIENTE=:c AND ROWNUM=1""",
        e=empresa, ec=estab_cli, b=banco, em=emitente, n=nrocheque, c=cliente,
    )
    chq = cur.fetchone()
    port_info   = {}
    recibo_data = None
    if chq:
        (valor, dtemissao, dtbompara, historico, portador,
         dtlanca, seqlanca, dtlancatran, seqlancatran,
         dtestornodep, seqestornodep, estabrecibo, nrorecibo) = chq
        port_info   = _portador(cur, empresa, portador) if portador else {}
        recibo_data = _recibo(cur, estabrecibo or empresa, nrorecibo) if nrorecibo else None
    else:
        valor = vlr_fallback
        dtemissao = dtbompara = historico = portador = None
        dtlanca = seqlanca = dtlancatran = seqlancatran = None
        dtestornodep = seqestornodep = None
    ch_node = {
        "id":   f"PCHEQREC-{empresa}-{banco}-{nrocheque}",
        "type": "PCHEQREC",
        "label": (
            f"<b>Cheque Recebido</b>\nCheque: #{nrocheque}"
            + (f"\nBanco: {_trunc(banco, 22)}" if banco else "")
            + (f"\nEmissão: {dtemissao.strftime('%d/%m/%Y')}" if dtemissao else "")
            + f"\nValor: {_fmtval(valor)}"
        ),
        "data": {
            "banco":         banco,
            "nrocheque":     nrocheque,
            "emitente":      emitente,
            "valor":         float(valor) if valor else 0,
            "emissao":       dtemissao.strftime("%d/%m/%Y") if dtemissao else None,
            "bom_para":      dtbompara.strftime("%d/%m/%Y") if dtbompara else None,
            "historico":     historico,
            "portador_desc": port_info.get("descricao"),
            "recibo_data":   recibo_data,
        },
    }
    lanca_node = None
    if dtlanca and seqlanca:
        lanca_node = _build_planca_node(cur, empresa, dtlanca, seqlanca)
    return ch_node, lanca_node


def _build_adiantamento_nodes(cur, nodes, edges, cml_id, numerocm, estab, seqcm):
    """Cria nós intermediários ADIANTAMENTO entre CONTAMOVLAN e os nós financeiros."""
    # DIN → ADIANTAMENTO → PLANCA
    cur.execute(
        "SELECT DTLANCA, SEQLANCA, SEQDIN FROM VIASOFT.CONTAMOVDIN WHERE NUMEROCM=:n AND ESTAB=:e AND SEQCM=:s",
        n=numerocm, e=estab, s=seqcm,
    )
    for dtlanca, seqlanca, seqdin in cur.fetchall():
        if not (dtlanca and seqlanca):
            continue
        lanca_node = _build_planca_node(cur, estab, dtlanca, seqlanca)
        if not lanca_node:
            continue
        valor_adt = lanca_node["data"].get("valor", 0)
        adt_id = f"ADIANTAMENTO-DIN-{numerocm}-{estab}-{seqcm}-{seqdin}"
        if not any(n["id"] == adt_id for n in nodes):
            nodes.append({
                "id":   adt_id,
                "type": "ADIANTAMENTO",
                "label": (
                    f"<b>Adiantamento</b>\nDinheiro / PIX"
                    + (f"\nData: {dtlanca.strftime('%d/%m/%Y')}" if dtlanca else "")
                    + f"\nValor: {_fmtval(valor_adt)}"
                ),
                "data": {
                    "forma": "Dinheiro / PIX",
                    "data":  dtlanca.strftime("%d/%m/%Y") if dtlanca else None,
                    "valor": valor_adt,
                },
            })
        edges.append({"from": cml_id,  "to": adt_id,            "label": "adiantamento"})
        if not any(n["id"] == lanca_node["id"] for n in nodes):
            nodes.append(lanca_node)
        edges.append({"from": adt_id, "to": lanca_node["id"],  "label": "lançamento"})

    # CHEM → ADIANTAMENTO → PCHEQEMI
    cur.execute(
        "SELECT PORTADOR, NROCHEQUE, SERIE, VALOR, SEQCHE FROM VIASOFT.CONTAMOVCHEM WHERE NUMEROCM=:n AND ESTAB=:e AND SEQCM=:s",
        n=numerocm, e=estab, s=seqcm,
    )
    for portador, nrocheque, serie, vlr, seqche in cur.fetchall():
        ch_node = _cheqemi_node(cur, estab, portador, nrocheque, serie, vlr)
        adt_id = f"ADIANTAMENTO-CHEM-{numerocm}-{estab}-{seqcm}-{seqche}"
        if not any(n["id"] == adt_id for n in nodes):
            nodes.append({
                "id":   adt_id,
                "type": "ADIANTAMENTO",
                "label": (
                    f"<b>Adiantamento</b>\nCheque Emitido"
                    f"\nCheque: #{nrocheque}"
                    f"\nValor: {_fmtval(vlr)}"
                ),
                "data": {
                    "forma":     "Cheque Emitido",
                    "nrocheque": nrocheque,
                    "valor":     float(vlr) if vlr else 0,
                },
            })
        edges.append({"from": cml_id, "to": adt_id,          "label": "adiantamento"})
        if not any(n["id"] == ch_node["id"] for n in nodes):
            nodes.append(ch_node)
        edges.append({"from": adt_id, "to": ch_node["id"],   "label": "cheque emitido"})

    # CHRE → ADIANTAMENTO → PCHEQREC
    cur.execute(
        """SELECT BANCO, ESTABCLIENTE, CLIENTE, EMITENTE, NROCHEQUE, VALOR, SEQCHE
           FROM VIASOFT.CONTAMOVCHRE WHERE NUMEROCM=:n AND ESTAB=:e AND SEQCM=:s""",
        n=numerocm, e=estab, s=seqcm,
    )
    for banco, estab_cli, cliente, emitente, nrocheque, vlr, seqche in cur.fetchall():
        ch_node, lanca_node = _cheqrec_node(cur, estab, banco, estab_cli, cliente, emitente, nrocheque, vlr)
        adt_id = f"ADIANTAMENTO-CHRE-{numerocm}-{estab}-{seqcm}-{seqche}"
        if not any(n["id"] == adt_id for n in nodes):
            nodes.append({
                "id":   adt_id,
                "type": "ADIANTAMENTO",
                "label": (
                    f"<b>Adiantamento</b>\nCheque Recebido"
                    f"\nCheque: #{nrocheque}"
                    f"\nValor: {_fmtval(vlr)}"
                ),
                "data": {
                    "forma":     "Cheque Recebido",
                    "banco":     banco,
                    "nrocheque": nrocheque,
                    "valor":     float(vlr) if vlr else 0,
                },
            })
        edges.append({"from": cml_id, "to": adt_id,         "label": "adiantamento"})
        if not any(n["id"] == ch_node["id"] for n in nodes):
            nodes.append(ch_node)
        edges.append({"from": adt_id, "to": ch_node["id"],  "label": "cheque recebido"})
        if lanca_node:
            if not any(n["id"] == lanca_node["id"] for n in nodes):
                nodes.append(lanca_node)
            edges.append({"from": ch_node["id"], "to": lanca_node["id"], "label": "compensação"})


def _contamov_pagamentos(cur, nodes, edges, from_id, numerocm, estab, seqcm):
    """Formas de pagamento de um acerto de CM (ACDB/ACCR) — sem nó intermediário."""
    # DIN → PLANCA
    cur.execute(
        "SELECT DTLANCA, SEQLANCA FROM VIASOFT.CONTAMOVDIN WHERE NUMEROCM=:n AND ESTAB=:e AND SEQCM=:s",
        n=numerocm, e=estab, s=seqcm,
    )
    for dtlanca, seqlanca in cur.fetchall():
        if not (dtlanca and seqlanca):
            continue
        lanca_node = _build_planca_node(cur, estab, dtlanca, seqlanca)
        if lanca_node and not any(n["id"] == lanca_node["id"] for n in nodes):
            nodes.append(lanca_node)
        if lanca_node:
            edges.append({"from": from_id, "to": lanca_node["id"], "label": "dinheiro/PIX"})

    # CHEM → PCHEQEMI
    cur.execute(
        "SELECT PORTADOR, NROCHEQUE, SERIE, VALOR FROM VIASOFT.CONTAMOVCHEM WHERE NUMEROCM=:n AND ESTAB=:e AND SEQCM=:s",
        n=numerocm, e=estab, s=seqcm,
    )
    for portador, nrocheque, serie, vlr in cur.fetchall():
        ch_node = _cheqemi_node(cur, estab, portador, nrocheque, serie, vlr)
        if not any(n["id"] == ch_node["id"] for n in nodes):
            nodes.append(ch_node)
        edges.append({"from": from_id, "to": ch_node["id"], "label": "cheque emitido"})

    # CHRE → PCHEQREC
    cur.execute(
        """SELECT BANCO, ESTABCLIENTE, CLIENTE, EMITENTE, NROCHEQUE, VALOR
           FROM VIASOFT.CONTAMOVCHRE WHERE NUMEROCM=:n AND ESTAB=:e AND SEQCM=:s""",
        n=numerocm, e=estab, s=seqcm,
    )
    for banco, estab_cli, cliente, emitente, nrocheque, vlr in cur.fetchall():
        ch_node, lanca_node = _cheqrec_node(cur, estab, banco, estab_cli, cliente, emitente, nrocheque, vlr)
        if not any(n["id"] == ch_node["id"] for n in nodes):
            nodes.append(ch_node)
        edges.append({"from": from_id, "to": ch_node["id"], "label": "cheque recebido"})
        if lanca_node:
            if not any(n["id"] == lanca_node["id"] for n in nodes):
                nodes.append(lanca_node)
            edges.append({"from": ch_node["id"], "to": lanca_node["id"], "label": "compensação"})

    # DUPP → trace completo da PDUPPAGA (NF upstream + baixas)
    cur.execute(
        "SELECT ESTABFORNECEDOR, FORNECEDOR, DUPPAG FROM VIASOFT.CONTAMOVDUPP WHERE NUMEROCM=:n AND ESTAB=:e AND SEQCM=:s",
        n=numerocm, e=estab, s=seqcm,
    )
    for estab_forn, forn, duppag in cur.fetchall():
        cur.execute(
            """SELECT EMPRESA FROM VIASOFT.PDUPPAGA
               WHERE ESTABFORNECEDOR=:ef AND FORNECEDOR=:f
                 AND REPLACE(DUPPAG,' ','')=:d AND ROWNUM=1""",
            ef=estab_forn, f=forn, d=_norm_duprec(duppag),
        )
        row = cur.fetchone()
        if not row:
            continue
        empresa_dp = row[0]
        sub_nodes, sub_edges, sub_err = _trace_pduppaga(cur, empresa_dp, duppag)
        if sub_err:
            continue
        dd_id = f"PDUPPAGA-{empresa_dp}-{_norm_duprec(duppag)}"
        seen = {n["id"] for n in nodes}
        for sn in sub_nodes:
            if sn["id"] not in seen:
                nodes.append(sn)
                seen.add(sn["id"])
        edges.extend(e for e in sub_edges if not e["from"].startswith("PESSOA-"))
        edges.append({"from": from_id, "to": dd_id, "label": "acerto dup. pagar"})

    # DUPR → trace completo da PDUPREC (NF upstream + baixas)
    cur.execute(
        "SELECT DUPREC FROM VIASOFT.CONTAMOVDUPR WHERE NUMEROCM=:n AND ESTAB=:e AND SEQCM=:s",
        n=numerocm, e=estab, s=seqcm,
    )
    for (duprec,) in cur.fetchall():
        cur.execute(
            "SELECT EMPRESA FROM VIASOFT.PDUPREC WHERE REPLACE(DUPREC,' ','')=:d AND ROWNUM=1",
            d=_norm_duprec(duprec),
        )
        row = cur.fetchone()
        if not row:
            continue
        empresa_dr = row[0]
        sub_nodes, sub_edges, sub_err = _trace_pduprec(cur, empresa_dr, duprec)
        if sub_err:
            continue
        dr_id = f"PDUPREC-{empresa_dr}-{_norm_duprec(duprec)}"
        seen = {n["id"] for n in nodes}
        for sn in sub_nodes:
            if sn["id"] not in seen:
                nodes.append(sn)
                seen.add(sn["id"])
        edges.extend(e for e in sub_edges if not e["from"].startswith("PESSOA-"))
        edges.append({"from": from_id, "to": dr_id, "label": "acerto dup. receber"})


def _trace_contamovlan(cur, numerocm, estab, seqcm):
    nodes = []
    edges = []

    # Nó principal
    cml_node = _build_contamovlan_node(cur, numerocm, seqcm, estab, None)
    if not cml_node or not cml_node["data"].get("valor") and not cml_node["data"].get("data"):
        # Verifica existência direta
        cur.execute(
            "SELECT COUNT(*) FROM VIASOFT.CONTAMOVLAN WHERE NUMEROCM=:n AND ESTAB=:e AND SEQCM=:s",
            n=numerocm, e=estab, s=seqcm,
        )
        if cur.fetchone()[0] == 0:
            return None, None, "Conta Movimento não encontrada"
    nodes.append(cml_node)
    cml_id = cml_node["id"]

    # Verifica se o tipo gera lançamento financeiro (adiantamento direto)
    cur.execute(
        """SELECT tp.GERARLANFIN FROM VIASOFT.CONTAMOVLAN cml
           JOIN VIASOFT.CONTAMOVTP tp ON tp.TIPO = cml.TIPO
           WHERE cml.NUMEROCM=:n AND cml.ESTAB=:e AND cml.SEQCM=:s""",
        n=numerocm, e=estab, s=seqcm,
    )
    row = cur.fetchone()
    gerarlanfin = row[0] if row else "N"

    if gerarlanfin == "S":
        _build_adiantamento_nodes(cur, nodes, edges, cml_id, numerocm, estab, seqcm)

    # Acertos via CONTAMOVLANAC
    cur.execute(
        """SELECT ac.SEQBAIXA, ac.SEQCM AS SEQCM_AC, ac.ESTAB AS ESTAB_AC,
                  ac.DTACERTO, ac.VALOR
           FROM VIASOFT.CONTAMOVLANAC ac
           WHERE ac.NUMEROCM=:n AND ac.ESTABACERTADO=:e AND ac.SEQACERTADA=:s
           ORDER BY ac.SEQBAIXA""",
        n=numerocm, e=estab, s=seqcm,
    )
    acertos = cur.fetchall()

    for seqbaixa, seqcm_ac, estab_ac, dtacerto, valor_ac in acertos:
        acerto_node = _build_contamovlan_node(cur, numerocm, seqcm_ac, estab_ac, valor_ac)
        if acerto_node and not any(n["id"] == acerto_node["id"] for n in nodes):
            nodes.append(acerto_node)
        acerto_id = acerto_node["id"] if acerto_node else f"CONTAMOVLANAC-{numerocm}-{estab}-{seqcm}-{seqbaixa}"
        edges.append({"from": cml_id, "to": acerto_id, "label": f"acerto #{seqbaixa}"})

        if acerto_node:
            _contamov_pagamentos(cur, nodes, edges, acerto_id, numerocm, estab_ac, seqcm_ac)

    # Upstream: NF via AGRFINCTAMOV
    cur.execute(
        "SELECT SEQPAGAMENTO FROM VIASOFT.AGRFINCTAMOV WHERE NUMEROCM=:n AND ESTAB=:e AND SEQCM=:s",
        n=numerocm, e=estab, s=seqcm,
    )
    seqs = [r[0] for r in cur.fetchall()]
    nf_seen = set()
    for seq_pag in seqs:
        cur.execute(
            "SELECT ESTAB, SEQNOTA FROM VIASOFT.NFCABAGRFIN WHERE SEQPAGAMENTO=:s",
            s=seq_pag,
        )
        for estab_nf, seqnota in cur.fetchall():
            if (estab_nf, seqnota) in nf_seen:
                continue
            nf_seen.add((estab_nf, seqnota))
            cur.execute(
                "SELECT NOTA, SERIE, DTEMISSAO, VALOR FROM VIASOFT.NFCAB WHERE ESTAB=:e AND SEQNOTA=:s",
                e=estab_nf, s=seqnota,
            )
            nf = cur.fetchone()
            if not nf:
                continue
            nota, serie, dt_nf, valor_nf = nf
            nf_id = f"NFCAB-{estab_nf}-{seqnota}"
            filial_nf = _filial(cur, estab_nf)
            if not any(n["id"] == nf_id for n in nodes):
                nodes.append({
                    "id": nf_id, "type": "NFCAB",
                    "label": (
                        f"<b>Nota Fiscal</b>\nNota: {nota}  Seq.: {seqnota}"
                        f"\nSérie: {serie}  Estab: {estab_nf}"
                        + (f"\nEmissão: {dt_nf.strftime('%d/%m/%Y')}" if dt_nf else "")
                        + f"\nValor: {_fmtval(valor_nf)}"
                    ),
                    "data": {
                        "estab": estab_nf, "nota": nota, "serie": serie, "seqnota": seqnota,
                        "filial": filial_nf.get("reduzido", str(estab_nf)),
                        "emissao": dt_nf.strftime("%d/%m/%Y") if dt_nf else None,
                        "valor": float(valor_nf) if valor_nf else 0,
                    },
                })
            edges.append({"from": nf_id, "to": cml_id, "label": "gera CM"})

    # PESSOA
    pessoa_det = _pessoa_detail(cur, numerocm)
    if pessoa_det:
        pes_id = f"PESSOA-{numerocm}"
        if not any(n["id"] == pes_id for n in nodes):
            nodes.append({"id": pes_id, "type": "PESSOA",
                          "label": _pessoa_label(pessoa_det), "data": pessoa_det})
        nf_ids = [n["id"] for n in nodes if n["type"] == "NFCAB"]
        if nf_ids:
            for nid in nf_ids:
                edges.append({"from": pes_id, "to": nid, "label": "pessoa"})
        else:
            edges.append({"from": pes_id, "to": cml_id, "label": "pessoa"})

    return nodes, edges, None


# ─── helpers: nós de origem (CTRC / CONHE / CONTRATO / RPA) ─────────────────

def _build_ctrc_node(cur, seqctrc):
    cur.execute(
        "SELECT NROCTRC, SERIE, DTEMISSAO, TOTAL FROM VIASOFT.CTRC WHERE SEQCTRC=:s",
        s=seqctrc,
    )
    row = cur.fetchone()
    if not row:
        return None
    nroctrc, serie, dtemissao, total = row
    return {
        "id":   f"CTRC-{seqctrc}",
        "type": "CTRC",
        "label": (
            f"<b>Conhec. Transp. Entrada</b>\nNº: {nroctrc}  Série: {serie}"
            + (f"\nEmissão: {dtemissao.strftime('%d/%m/%Y')}" if dtemissao else "")
            + f"\nValor: {_fmtval(total)}"
        ),
        "data": {
            "nroctrc": nroctrc,
            "serie":   serie,
            "emissao": dtemissao.strftime("%d/%m/%Y") if dtemissao else None,
            "valor":   float(total) if total else 0,
        },
    }


def _build_conhe_node(cur, estab, seqconhe):
    cur.execute(
        "SELECT NUMERO, SERIE, DTEMISSAO, TOTALFRETE FROM VIASOFT.CONHE WHERE ESTAB=:e AND SEQCONHE=:s",
        e=estab, s=seqconhe,
    )
    row = cur.fetchone()
    if not row:
        return None
    numero, serie, dtemissao, totalfrete = row
    return {
        "id":   f"CONHE-{estab}-{seqconhe}",
        "type": "CONHE",
        "label": (
            f"<b>CT-e (Transp. Saída)</b>\nNº: {numero}  Série: {serie}"
            + (f"\nEmissão: {dtemissao.strftime('%d/%m/%Y')}" if dtemissao else "")
            + f"\nFrete: {_fmtval(totalfrete)}"
        ),
        "data": {
            "numero":  numero,
            "serie":   serie,
            "emissao": dtemissao.strftime("%d/%m/%Y") if dtemissao else None,
            "valor":   float(totalfrete) if totalfrete else 0,
        },
    }


def _build_contrato_node(cur, estab, contrato):
    cur.execute(
        "SELECT DTEMISSAO, DTVENCTO, VALOR FROM VIASOFT.CONTRATO WHERE ESTAB=:e AND CONTRATO=:c",
        e=estab, c=contrato,
    )
    row = cur.fetchone()
    if not row:
        return None
    dtemissao, dtvencto, valor = row
    return {
        "id":   f"CONTRATO-{estab}-{contrato}",
        "type": "CONTRATO",
        "label": (
            f"<b>Contrato</b>\nNº: {contrato}"
            + (f"\nEmissão: {dtemissao.strftime('%d/%m/%Y')}" if dtemissao else "")
            + (f"\nVencto: {dtvencto.strftime('%d/%m/%Y')}" if dtvencto else "")
            + f"\nValor: {_fmtval(valor)}"
        ),
        "data": {
            "contrato": contrato,
            "emissao":  dtemissao.strftime("%d/%m/%Y") if dtemissao else None,
            "vencto":   dtvencto.strftime("%d/%m/%Y") if dtvencto else None,
            "valor":    float(valor) if valor else 0,
        },
    }


def _build_rpa_node(cur, estab, codigo):
    cur.execute(
        "SELECT MES, ANO, VALOR, DESCRICAO FROM VIASOFT.RPA WHERE ESTAB=:e AND CODIGO=:c",
        e=estab, c=codigo,
    )
    row = cur.fetchone()
    if not row:
        return None
    mes, ano, valor, descricao = row
    return {
        "id":   f"RPA-{estab}-{codigo}",
        "type": "RPA",
        "label": (
            f"<b>RPA</b>\nCódigo: {codigo}"
            + (f"\nPeríodo: {mes:02d}/{ano}" if mes and ano else "")
            + f"\nValor: {_fmtval(valor)}"
        ),
        "data": {
            "codigo":    codigo,
            "periodo":   f"{mes:02d}/{ano}" if mes and ano else None,
            "valor":     float(valor) if valor else 0,
            "descricao": descricao,
        },
    }


def _add_doc_origem_nodes(cur, seqs, target_id, edge_label, nodes, edges):
    """Detecta documentos de origem (CTRC/CONHE/CONTRATO/RPA) via SEQPAGAMENTO."""
    ctrc_seen     = set()
    conhe_seen    = set()
    contrato_seen = set()
    rpa_seen      = set()

    for seq in seqs:
        cur.execute("SELECT SEQCTRC FROM VIASOFT.AGRFINCTRC WHERE SEQPAGAMENTO=:s", s=seq)
        for (seqctrc,) in cur.fetchall():
            if seqctrc in ctrc_seen:
                continue
            ctrc_seen.add(seqctrc)
            n = _build_ctrc_node(cur, seqctrc)
            if n and not any(x["id"] == n["id"] for x in nodes):
                nodes.append(n)
                edges.append({"from": n["id"], "to": target_id, "label": edge_label})

        cur.execute(
            "SELECT ESTAB, SEQCONHE FROM VIASOFT.CONHEAGRFIN WHERE SEQPAGAMENTO=:s", s=seq
        )
        for estab_c, seqconhe in cur.fetchall():
            if (estab_c, seqconhe) in conhe_seen:
                continue
            conhe_seen.add((estab_c, seqconhe))
            n = _build_conhe_node(cur, estab_c, seqconhe)
            if n and not any(x["id"] == n["id"] for x in nodes):
                nodes.append(n)
                edges.append({"from": n["id"], "to": target_id, "label": edge_label})

        cur.execute(
            "SELECT ESTAB, CONTRATO FROM VIASOFT.CONTRATOAGRFIN WHERE SEQPAGAMENTO=:s", s=seq
        )
        for estab_c, contrato in cur.fetchall():
            if (estab_c, contrato) in contrato_seen:
                continue
            contrato_seen.add((estab_c, contrato))
            n = _build_contrato_node(cur, estab_c, contrato)
            if n and not any(x["id"] == n["id"] for x in nodes):
                nodes.append(n)
                edges.append({"from": n["id"], "to": target_id, "label": edge_label})

        cur.execute(
            "SELECT ESTAB, CODIGO FROM VIASOFT.RPAAGRFIN WHERE SEQPAGAMENTO=:s", s=seq
        )
        for estab_r, codigo in cur.fetchall():
            if (estab_r, codigo) in rpa_seen:
                continue
            rpa_seen.add((estab_r, codigo))
            n = _build_rpa_node(cur, estab_r, codigo)
            if n and not any(x["id"] == n["id"] for x in nodes):
                nodes.append(n)
                edges.append({"from": n["id"], "to": target_id, "label": edge_label})


# ─── trace por PCHEQEMI ──────────────────────────────────────────────────────

def _trace_pcheqemi(cur, empresa, portador, nrocheque, serie):
    nodes = []
    edges = []

    cur.execute(
        """SELECT EMPRESA, PORTADOR, NROCHEQUE, SERIE,
                  VALOR, DTEMISSAO, DTBOMPARA, FAVORECIDO, HISTORICO, HISTORICO2,
                  SITUACAO, DTLANCA, SEQLANCA, DTLANCATRANSF, SEQLANCATRANSF,
                  ESTABFORNECEDOR, FORNECEDOR, ESTABRECIBO, NRORECIBO
           FROM VIASOFT.PCHEQEMI
           WHERE EMPRESA=:e AND PORTADOR=:p AND NROCHEQUE=:n AND SERIE=:s""",
        e=empresa, p=portador, n=nrocheque, s=serie,
    )
    chq = cur.fetchone()
    if not chq:
        return None, None, "Cheque emitido não encontrado"

    (emp, port_real, nroch_real, serie_real,
     valor, dtemissao, dtbompara, favorecido, historico, historico2,
     situacao, dtlanca, seqlanca, dtlancatransf, seqlancatransf,
     estab_forn, fornecedor, estabrecibo, nrorecibo) = chq

    port_info   = _portador(cur, emp, port_real) if port_real else {}
    recibo_data = _recibo(cur, estabrecibo or emp, nrorecibo) if nrorecibo else None

    ch_id = f"PCHEQEMI-{emp}-{port_real}-{nroch_real}-{serie_real}"
    nodes.append({
        "id":     ch_id,
        "type":   "PCHEQEMI",
        "isRoot": True,
        "label": (
            f"<b>Cheque Emitido</b>\nCheque: #{nroch_real}"
            + (f"\nSérie: {serie_real}" if serie_real else "")
            + (f"\nEmissão: {dtemissao.strftime('%d/%m/%Y')}" if dtemissao else "")
            + f"\nValor: {_fmtval(valor)}"
        ),
        "data": {
            "nrocheque":     nroch_real,
            "serie":         serie_real,
            "portador_desc": port_info.get("descricao"),
            "favorecido":    favorecido,
            "valor":         float(valor) if valor else 0,
            "emissao":       dtemissao.strftime("%d/%m/%Y") if dtemissao else None,
            "bom_para":      dtbompara.strftime("%d/%m/%Y") if dtbompara else None,
            "historico":     historico,
            "historico2":    historico2,
            "situacao":      situacao,
            "recibo_data":   recibo_data,
        },
    })

    # ── Downstream: lançamentos de compensação e transferência de portador ────
    if dtlanca and seqlanca:
        n = _build_planca_node(cur, emp, dtlanca, seqlanca)
        if n:
            nodes.append(n)
            edges.append({"from": ch_id, "to": n["id"], "label": "compensação"})

    if dtlancatransf and seqlancatransf:
        n = _build_planca_node(cur, emp, dtlancatransf, seqlancatransf)
        if n and not any(x["id"] == n["id"] for x in nodes):
            nodes.append(n)
            edges.append({"from": ch_id, "to": n["id"], "label": "transf. portador"})

    # ── Upstream: DUPPAG via PPADUCHE ─────────────────────────────────────────
    cur.execute(
        """SELECT EMPRESA, DUPPAG
           FROM VIASOFT.PPADUCHE
           WHERE ESTABBAIXA=:e AND PORTADOR=:p AND NROCHEQUE=:n AND SERIE=:s""",
        e=emp, p=port_real, n=nroch_real, s=serie_real,
    )
    for ppa_emp, ppa_duppag in cur.fetchall():
        sub_nodes, sub_edges, _ = _trace_pduppaga(cur, ppa_emp, ppa_duppag)
        if sub_nodes:
            dup_id = f"PDUPPAGA-{ppa_emp}-{_norm_duprec(ppa_duppag)}"
            existing = {x["id"] for x in nodes}
            for x in sub_nodes:
                if x["id"] not in existing:
                    nodes.append(x)
            edges.extend(sub_edges)
            edges.append({"from": dup_id, "to": ch_id, "label": "cheque emitido"})

    # ── Upstream: CONTAMOV via CONTAMOVCHEM → CONTAMOVLAN ─────────────────────
    cur.execute(
        """SELECT NUMEROCM, ESTAB, SEQCM
           FROM VIASOFT.CONTAMOVCHEM
           WHERE ESTAB=:e AND PORTADOR=:p AND NROCHEQUE=:n AND SERIE=:s""",
        e=emp, p=port_real, n=nroch_real, s=serie_real,
    )
    for numerocm, estab_cm, seqcm in cur.fetchall():
        sub_nodes, sub_edges, _ = _trace_contamovlan(cur, numerocm, estab_cm, seqcm)
        if sub_nodes:
            cml_id = f"CONTAMOVLAN-{numerocm}-{estab_cm or 0}-{seqcm}"
            existing = {x["id"] for x in nodes}
            for x in sub_nodes:
                if x["id"] not in existing:
                    nodes.append(x)
            edges.extend(sub_edges)
            edges.append({"from": cml_id, "to": ch_id, "label": "cheque emitido"})

    # ── Upstream: NF via AGRFINCHEEMI → NFCABAGRFIN ───────────────────────────
    cur.execute(
        """SELECT SEQPAGAMENTO
           FROM VIASOFT.AGRFINCHEEMI
           WHERE ESTAB=:e AND PORTADOR=:p AND NROCHEQUE=:n AND SERIE=:s""",
        e=emp, p=port_real, n=nroch_real, s=serie_real,
    )
    nf_seen = set()
    for (seq_pag,) in cur.fetchall():
        cur.execute(
            "SELECT ESTAB, SEQNOTA FROM VIASOFT.NFCABAGRFIN WHERE SEQPAGAMENTO=:s",
            s=seq_pag,
        )
        for estab_nf, seqnota in cur.fetchall():
            if (estab_nf, seqnota) in nf_seen:
                continue
            nf_seen.add((estab_nf, seqnota))
            sub_nodes, sub_edges, _ = _trace_nfcab(cur, estab_nf, seqnota)
            if sub_nodes:
                nf_id = f"NFCAB-{estab_nf}-{seqnota}"
                existing = {x["id"] for x in nodes}
                for x in sub_nodes:
                    if x["id"] not in existing:
                        nodes.append(x)
                edges.extend(sub_edges)
                edges.append({"from": nf_id, "to": ch_id, "label": "cheque emitido"})

    # ── Fornecedor (Pessoa) ────────────────────────────────────────────────────
    if fornecedor:
        pessoa_det = _pessoa_detail(cur, fornecedor)
        if pessoa_det:
            pes_id = f"PESSOA-{fornecedor}"
            if not any(x["id"] == pes_id for x in nodes):
                nodes.append({"id": pes_id, "type": "PESSOA",
                              "label": _pessoa_label(pessoa_det), "data": pessoa_det})
            edges.append({"from": pes_id, "to": ch_id, "label": "fornecedor"})

    return nodes, edges, None


# ─── trace por PCHEQREC ──────────────────────────────────────────────────────

def _trace_pcheqrec(cur, empresa, nrocheque, cliente=None, banco=None, estabcliente=None, emitente=None, _seen=None):
    if _seen is None:
        _seen = set()

    nodes = []
    edges = []

    # Monta WHERE com todos os campos da PK disponíveis para evitar ambiguidade
    where  = "EMPRESA=:e AND NROCHEQUE=:n"
    params = dict(e=empresa, n=nrocheque)
    if cliente:
        where += " AND CLIENTE=:c";       params['c']  = cliente
    if banco:
        where += " AND BANCO=:b";         params['b']  = banco
    if estabcliente:
        where += " AND ESTABCLIENTE=:ec"; params['ec'] = estabcliente
    if emitente:
        where += " AND EMITENTE=:em";     params['em'] = emitente

    cur.execute(
        f"""SELECT EMPRESA, BANCO, ESTABCLIENTE, CLIENTE, EMITENTE, NROCHEQUE,
                  VALOR, DTEMISSAO, DTBOMPARA, HISTORICO, PORTADOR,
                  DTLANCA,      SEQLANCA,
                  DTLANCATRAN,  SEQLANCATRAN,
                  DTESTORNODEP, SEQESTORNODEP,
                  ESTABRECIBO,  NRORECIBO
           FROM VIASOFT.PCHEQREC
           WHERE {where} AND ROWNUM=1""",
        **params,
    )

    chq = cur.fetchone()
    if not chq:
        return None, None, "Cheque recebido não encontrado"

    (emp, banco, estab_cli, cliente_num, emitente, nrocheque_real,
     valor, dtemissao, dtbompara, historico, portador,
     dtlanca,      seqlanca,
     dtlancatran,  seqlancatran,
     dtestornodep, seqestornodep,
     estabrecibo,  nrorecibo) = chq

    ch_id = f"PCHEQREC-{emp}-{banco}-{nrocheque_real}"

    # Evita ciclo em cadeia de transferências
    if ch_id in _seen:
        return [], [], None
    _seen.add(ch_id)

    port_info   = _portador(cur, emp, portador) if portador else {}
    recibo_data = _recibo(cur, estabrecibo or emp, nrorecibo) if nrorecibo else None

    is_root = len(_seen) == 1  # só o primeiro nó da cadeia é raiz
    nodes.append({
        "id":     ch_id,
        "type":   "PCHEQREC",
        "isRoot": is_root,
        "label": (
            f"<b>Cheque Recebido</b>\nCheque: #{nrocheque_real}"
            + (f"\nBanco: {_trunc(banco, 22)}" if banco else "")
            + (f"\nEmissão: {dtemissao.strftime('%d/%m/%Y')}" if dtemissao else "")
            + f"\nValor: {_fmtval(valor)}"
        ),
        "data": {
            "banco":         banco,
            "nrocheque":     nrocheque_real,
            "emitente":      emitente,
            "valor":         float(valor) if valor else 0,
            "emissao":       dtemissao.strftime("%d/%m/%Y") if dtemissao else None,
            "bom_para":      dtbompara.strftime("%d/%m/%Y") if dtbompara else None,
            "historico":     historico,
            "portador_desc": port_info.get("descricao"),
            "recibo_data":   recibo_data,
        },
    })

    # ── Downstream: lançamentos financeiros vinculados ────────────────────────

    if dtlanca and seqlanca:
        n = _build_planca_node(cur, emp, dtlanca, seqlanca)
        if n:
            nodes.append(n)
            edges.append({"from": ch_id, "to": n["id"], "label": "compensação"})

    if dtlancatran and seqlancatran:
        n = _build_planca_node(cur, emp, dtlancatran, seqlancatran)
        if n and not any(x["id"] == n["id"] for x in nodes):
            nodes.append(n)
            edges.append({"from": ch_id, "to": n["id"], "label": "saída transferência"})

    if dtestornodep and seqestornodep:
        n = _build_planca_node(cur, emp, dtestornodep, seqestornodep)
        if n and not any(x["id"] == n["id"] for x in nodes):
            nodes.append(n)
            edges.append({"from": ch_id, "to": n["id"], "label": "estorno depósito"})

    # ── Cadeia de transferências via TRANSFCHE ────────────────────────────────

    # Este cheque foi transferido → encontrar cheque destino (:T)
    cur.execute(
        """SELECT ESTAB_TRAN, BANCO_TRAN, ESTABCLIENTE_TRAN, CLIENTE_TRAN,
                  EMITENTE_TRAN, NROCHEQUE_TRAN, DTTRANSF
           FROM VIASOFT.TRANSFCHE
           WHERE ESTAB=:e AND BANCO=:b AND ESTABCLIENTE=:ec
             AND CLIENTE=:c AND EMITENTE=:em AND NROCHEQUE=:n""",
        e=emp, b=banco, ec=estab_cli, c=cliente_num, em=emitente, n=nrocheque_real,
    )
    for estab_t, banco_t, estabcli_t, cli_t, emit_t, nroch_t, dtransf in cur.fetchall():
        sub_nodes, sub_edges, _ = _trace_pcheqrec(
            cur, estab_t, nroch_t, cli_t, banco_t, estabcli_t, emit_t, _seen=_seen
        )
        if sub_nodes:
            dest_id = f"PCHEQREC-{estab_t}-{banco_t}-{nroch_t}"
            for x in sub_nodes:
                if x["id"] == dest_id:
                    x["data"]["transferido_de_estab"] = emp
                    x["data"]["dt_transferencia"] = dtransf.strftime("%d/%m/%Y") if dtransf else None
                    break
            existing = {x["id"] for x in nodes}
            for x in sub_nodes:
                if x["id"] not in existing:
                    nodes.append(x)
            edges.extend(sub_edges)
            label = f"transferido {dtransf.strftime('%d/%m/%Y')}" if dtransf else "transferido"
            edges.append({"from": ch_id, "to": dest_id, "label": label})

    # Este cheque é destino de transferência → encontrar cheque origem
    cur.execute(
        """SELECT ESTAB, BANCO, ESTABCLIENTE, CLIENTE, EMITENTE, NROCHEQUE, DTTRANSF
           FROM VIASOFT.TRANSFCHE
           WHERE ESTAB_TRAN=:e AND BANCO_TRAN=:b AND ESTABCLIENTE_TRAN=:ec
             AND CLIENTE_TRAN=:c AND EMITENTE_TRAN=:em AND NROCHEQUE_TRAN=:n""",
        e=emp, b=banco, ec=estab_cli, c=cliente_num, em=emitente, n=nrocheque_real,
    )
    for estab_o, banco_o, estabcli_o, cli_o, emit_o, nroch_o, dtransf in cur.fetchall():
        sub_nodes, sub_edges, _ = _trace_pcheqrec(
            cur, estab_o, nroch_o, cli_o, banco_o, estabcli_o, emit_o, _seen=_seen
        )
        if sub_nodes:
            existing = {x["id"] for x in nodes}
            for x in sub_nodes:
                if x["id"] not in existing:
                    nodes.append(x)
            edges.extend(sub_edges)
            orig_id = f"PCHEQREC-{estab_o}-{banco_o}-{nroch_o}"
            label = f"transferido {dtransf.strftime('%d/%m/%Y')}" if dtransf else "transferido"
            edges.append({"from": orig_id, "to": ch_id, "label": label})

    # ── Upstream: quem originou este cheque ───────────────────────────────────

    cur.execute(
        """SELECT DISTINCT REPLACE(DUPREC,' ','')
           FROM VIASOFT.PRDURECH
           WHERE EMPRESA=:e AND BANCO=:b AND NROCHEQUE=:n""",
        e=emp, b=banco, n=nrocheque_real,
    )
    for (duprec_norm,) in cur.fetchall():
        sub_nodes, sub_edges, _ = _trace_pduprec(cur, emp, duprec_norm, skip_pessoa=True)
        if sub_nodes:
            existing = {x["id"] for x in nodes}
            for x in sub_nodes:
                if x["id"] not in existing:
                    nodes.append(x)
            edges.extend(sub_edges)

    cur.execute(
        """SELECT DISTINCT NUMEROCM, ESTAB, SEQCM
           FROM VIASOFT.CONTAMOVCHRE
           WHERE BANCO=:b AND NROCHEQUE=:n AND CLIENTE=:c AND EMITENTE=:em""",
        b=banco, n=nrocheque_real, c=cliente_num, em=emitente,
    )
    for numerocm_cm, estab_cm, seqcm in cur.fetchall():
        sub_nodes, sub_edges, _ = _trace_contamovlan(cur, numerocm_cm, estab_cm, seqcm)
        if sub_nodes:
            existing = {x["id"] for x in nodes}
            for x in sub_nodes:
                if x["id"] not in existing:
                    nodes.append(x)
            edges.extend(sub_edges)

    cur.execute(
        """SELECT DISTINCT EMPRESA, ESTABFORNECEDOR, FORNECEDOR, REPLACE(DUPPAG,' ','')
           FROM VIASOFT.PPADUCHR
           WHERE BANCO=:b AND NROCHEQUE=:n AND CLIENTE=:c AND EMITENTE=:em""",
        b=banco, n=nrocheque_real, c=cliente_num, em=emitente,
    )
    for emp_dp, estab_forn, forn, duppag_norm in cur.fetchall():
        sub_nodes, sub_edges, _ = _trace_pduppaga(cur, emp_dp, duppag_norm)
        if sub_nodes:
            existing = {x["id"] for x in nodes}
            for x in sub_nodes:
                if x["id"] not in existing:
                    nodes.append(x)
            edges.extend(sub_edges)

    cur.execute(
        """SELECT DISTINCT nf.ESTAB, nf.SEQNOTA
           FROM VIASOFT.AGRFINCHEREC ac
           JOIN VIASOFT.NFCABAGRFIN nf ON nf.SEQPAGAMENTO = ac.SEQPAGAMENTO
           WHERE ac.ESTAB=:emp AND ac.BANCO=:b AND ac.ESTABCLIENTE=:ec
             AND ac.CLIENTE=:c AND ac.EMITENTE=:em AND ac.NROCHEQUE=:n""",
        emp=emp, b=banco, ec=estab_cli, c=cliente_num, em=emitente, n=nrocheque_real,
    )
    for estab_nf, seqnota in cur.fetchall():
        sub_nodes, sub_edges, _ = _trace_nfcab(cur, estab_nf, seqnota)
        if sub_nodes:
            existing = {x["id"] for x in nodes}
            for x in sub_nodes:
                if x["id"] not in existing:
                    nodes.append(x)
            edges.extend(sub_edges)

    # ── PESSOA (apenas na chamada raiz) ───────────────────────────────────────
    if is_root and cliente_num:
        pessoa_det = _pessoa_detail(cur, cliente_num)
        if pessoa_det:
            pes_id = f"PESSOA-{cliente_num}"
            if not any(x["id"] == pes_id for x in nodes):
                nodes.append({
                    "id": pes_id, "type": "PESSOA",
                    "label": _pessoa_label(pessoa_det), "data": pessoa_det,
                })
            pedcab_ids  = [x["id"] for x in nodes if x["type"] == "PEDCAB"]
            pduprec_ids = [x["id"] for x in nodes if x["type"] == "PDUPREC"]
            cml_ids     = [x["id"] for x in nodes if x["type"] == "CONTAMOVLAN"]
            if pedcab_ids:
                for pid in pedcab_ids:
                    edges.append({"from": pes_id, "to": pid, "label": "cliente"})
            elif pduprec_ids:
                edges.append({"from": pes_id, "to": pduprec_ids[0], "label": "cliente"})
            elif cml_ids:
                edges.append({"from": pes_id, "to": cml_ids[0], "label": "cliente"})
            else:
                edges.append({"from": pes_id, "to": ch_id, "label": "cliente"})

    return nodes, edges, None


# ─── endpoint principal ───────────────────────────────────────────────────────

@bp.route("")
def trace():
    tela = request.args.get("tela", "").upper()
    empresa = request.args.get("empresa", type=int)
    estab = request.args.get("estab", type=int)
    doc = request.args.get("doc", "").strip()
    serie = request.args.get("serie", "").strip()

    numerocm = request.args.get("numerocm", type=int)
    cliente  = request.args.get("cliente",  type=int)

    if not tela or not doc:
        return jsonify({"erro": "Parâmetros obrigatórios: tela, doc"}), 400

    try:
        conn = get_connection()
        cur = conn.cursor()

        if tela == "DUPREC":
            emp = empresa or estab or 1
            nodes, edges, err = _trace_pduprec(cur, emp, doc)
        elif tela == "DUPPAG":
            emp = empresa or estab or 1
            nodes, edges, err = _trace_pduppaga(cur, emp, doc)
        elif tela == "NFCAB":
            nodes, edges, err = _trace_nfcab(cur, estab or 1, int(doc))
        elif tela == "PEDCAB":
            nodes, edges, err = _trace_pedcab(cur, estab or 1, serie, int(doc))
        elif tela == "CONTAMOV":
            if not numerocm:
                return jsonify({"erro": "Parâmetro obrigatório: numerocm"}), 400
            nodes, edges, err = _trace_contamovlan(cur, numerocm, estab or 1, int(doc))
        elif tela == "CHEQREC":
            emp     = empresa or 1
            banco   = request.args.get("banco",        "").strip() or None
            estab_c = request.args.get("estabcliente", type=int)
            emitente= request.args.get("emitente",     "").strip() or None
            nodes, edges, err = _trace_pcheqrec(cur, emp, int(doc), cliente, banco, estab_c, emitente)
        elif tela == "CHEQEMI":
            emp      = empresa or 1
            portador = request.args.get("portador", type=int)
            serie_c  = request.args.get("serie", "").strip() or "1"
            if not portador:
                return jsonify({"erro": "Parâmetro obrigatório: portador"}), 400
            nodes, edges, err = _trace_pcheqemi(cur, emp, portador, int(doc), serie_c)
        else:
            return jsonify({"erro": f"Tipo '{tela}' não suportado"}), 400

        cur.close()
        conn.close()

        if err:
            return jsonify({"erro": err}), 404

        # Marca o nó de entrada como ponto de partida
        if tela == "DUPREC":
            root_id = f"PDUPREC-{emp}-{_norm_duprec(doc)}"
        elif tela == "DUPPAG":
            root_id = f"PDUPPAGA-{emp}-{_norm_duprec(doc)}"
        elif tela == "NFCAB":
            root_id = f"NFCAB-{estab or 1}-{int(doc)}"
        elif tela == "PEDCAB":
            root_id = f"PEDCAB-{estab or 1}-{serie}-{int(doc)}"
        elif tela == "CONTAMOV":
            root_id = f"CONTAMOVLAN-{numerocm}-{estab or 1}-{int(doc)}"
        elif tela in ("CHEQREC", "CHEQEMI"):
            root_id = None  # isRoot marcado dentro do _trace_* pelo primeiro nó
        else:
            root_id = None
        if root_id:
            for n in nodes:
                if n["id"] == root_id:
                    n["isRoot"] = True
                    break

        return jsonify({"nodes": nodes, "edges": edges})

    except Exception as e:
        return jsonify({"erro": str(e)}), 500

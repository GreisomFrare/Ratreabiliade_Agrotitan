import re
from flask import Blueprint, jsonify
from db_oracle import get_connection

bp = Blueprint("descduprec", __name__, url_prefix="/api/descduprec")

_BEFORE_DDL = """
CREATE OR REPLACE TRIGGER VIASOFT.TRG_PDUPREC_RENEG_BFR
BEFORE INSERT OR UPDATE ON VIASOFT.PDUPREC
FOR EACH ROW
DECLARE
    v_existe NUMBER;
BEGIN
    IF :NEW.BANCO     IS NOT NULL
       AND :NEW.SEQCOBCAB IS NOT NULL
       AND :NEW.SEQCOBDET IS NOT NULL
       AND NVL(:NEW.SITUACAO, 0) != 3
       AND (INSERTING
            OR NVL(:NEW.BANCO,     -1) != NVL(:OLD.BANCO,     -1)
            OR NVL(:NEW.SEQCOBCAB, -1) != NVL(:OLD.SEQCOBCAB, -1)
            OR NVL(:NEW.SEQCOBDET, -1) != NVL(:OLD.SEQCOBDET, -1))
    THEN
        BEGIN
            SELECT 1 INTO v_existe
              FROM VIASOFT.PRDUREDUP
             WHERE DUPRECGER  = :NEW.DUPREC
               AND ESTABBAIXA = :NEW.EMPRESA
               AND ROWNUM     = 1;
            :NEW.SITUACAO := 3;
        EXCEPTION
            WHEN NO_DATA_FOUND THEN NULL;
        END;
    END IF;
END TRG_PDUPREC_RENEG_BFR
"""

_AFTER_DDL = """
CREATE OR REPLACE TRIGGER VIASOFT.TRG_PDUPREC_DESCDUPREC
AFTER INSERT OR UPDATE ON VIASOFT.PDUPREC
FOR EACH ROW
DECLARE
    v_tipojuros VARCHAR2(4000);
BEGIN
    IF :NEW.SITUACAO    = 3
       AND NVL(:OLD.SITUACAO, -1) != 3
       AND :NEW.BANCO     IS NOT NULL
       AND :NEW.SEQCOBCAB IS NOT NULL
       AND :NEW.SEQCOBDET IS NOT NULL
    THEN
        INSERT INTO VIASOFT.DESCDUPREC_BKP
            (ESTAB, DUPREC, IDDESCONTO, SEQUENCIA, PERCENTUAL,
             DTVALINI, DTVALFIM, APLICOU, TIPODESCONTO,
             DT_BKP, SITUACAO_ANT, SITUACAO_NOV)
        SELECT ESTAB, DUPREC, IDDESCONTO, SEQUENCIA, PERCENTUAL,
               DTVALINI, DTVALFIM, APLICOU, TIPODESCONTO,
               SYSTIMESTAMP, :OLD.SITUACAO, :NEW.SITUACAO
          FROM VIASOFT.DESCDUPREC
         WHERE ESTAB  = :NEW.EMPRESA
           AND DUPREC = :NEW.DUPREC;

        DELETE FROM VIASOFT.DESCDUPREC
         WHERE ESTAB  = :NEW.EMPRESA
           AND DUPREC = :NEW.DUPREC;

        BEGIN
            SELECT TIPOJUROS
              INTO v_tipojuros
              FROM VIASOFT.PSITUACA
             WHERE SITUACAO = :NEW.SITUACAO;
        EXCEPTION
            WHEN NO_DATA_FOUND THEN v_tipojuros := NULL;
        END;

        IF v_tipojuros IS NOT NULL THEN
            FOR r IN (
                SELECT dt.IDDESCONTO,
                       dcp.SEQUENCIA,
                       dcp.PERCENTUAL
                  FROM VIASOFT.DESCTITULO   dt
                  JOIN VIASOFT.DESCPCONFPAD dcp
                    ON dcp.IDDESCONTO = dt.IDDESCONTO
                   AND dcp.ESTAB      = :NEW.EMPRESA
                 WHERE INSTR(',' || v_tipojuros || ',',
                             ',' || TO_CHAR(dt.IDDESCONTO) || ',') > 0
                   AND INSTR(',' || dt.SITUACAO || ',',
                             ',' || TO_CHAR(:NEW.SITUACAO) || ',') > 0
            ) LOOP
                INSERT INTO VIASOFT.DESCDUPREC
                    (ESTAB, DUPREC, IDDESCONTO, SEQUENCIA, PERCENTUAL, TIPODESCONTO)
                VALUES
                    (:NEW.EMPRESA, :NEW.DUPREC, r.IDDESCONTO, r.SEQUENCIA, r.PERCENTUAL, 1);
            END LOOP;
        END IF;
    END IF;
END TRG_PDUPREC_DESCDUPREC
"""


def _trigger_status_row(cur, name):
    cur.execute(
        """SELECT STATUS, LAST_DDL_TIME FROM ALL_OBJECTS
           WHERE OBJECT_TYPE = 'TRIGGER' AND OBJECT_NAME = :1 AND OWNER = 'VIASOFT'""",
        [name],
    )
    return cur.fetchone()


@bp.get("/trigger/status")
def trigger_status():
    try:
        conn = get_connection()
        cur = conn.cursor()
        bfr = _trigger_status_row(cur, "TRG_PDUPREC_RENEG_BFR")
        aft = _trigger_status_row(cur, "TRG_PDUPREC_DESCDUPREC")
        conn.close()
        return jsonify({
            "before": {
                "existe": bfr is not None,
                "status": bfr[0] if bfr else None,
                "ultima_alteracao": bfr[1].strftime("%d/%m/%Y %H:%M") if bfr and bfr[1] else None,
            },
            "after": {
                "existe": aft is not None,
                "status": aft[0] if aft else None,
                "ultima_alteracao": aft[1].strftime("%d/%m/%Y %H:%M") if aft and aft[1] else None,
            },
        })
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@bp.post("/trigger/deploy")
def trigger_deploy():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(_BEFORE_DDL)
        cur.execute(_AFTER_DDL)
        conn.close()
        return jsonify({"ok": True, "mensagem": "Triggers criadas/atualizadas com sucesso."})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

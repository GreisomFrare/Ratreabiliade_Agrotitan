import json
import os
import oracledb

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

_thick_initialized = False


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_connection():
    global _thick_initialized
    cfg = load_config()["oracle"]
    modo = cfg.get("modo_conexao", "DIRETO")

    if modo == "TNS":
        if not _thick_initialized:
            oracledb.init_oracle_client(lib_dir=cfg["tns"]["oracle_client_bin"])
            _thick_initialized = True
        conn = oracledb.connect(
            user=cfg["usuario"],
            password=cfg["senha"],
            dsn=cfg["tns"]["alias"],
        )
    else:
        d = cfg["direto"]
        dsn_kwargs = {}
        if d.get("service_name"):
            dsn_kwargs["service_name"] = d["service_name"]
        else:
            dsn_kwargs["sid"] = d["sid"]
        conn = oracledb.connect(
            user=cfg["usuario"],
            password=cfg["senha"],
            host=d["host"],
            port=d["porta"],
            **dsn_kwargs,
        )

    conn.outputtypehandler = _str_output_handler
    return conn


def _str_output_handler(cursor, name, default_type, size, precision, scale):
    if default_type == oracledb.DB_TYPE_CLOB:
        return cursor.var(oracledb.DB_TYPE_LONG, arraysize=cursor.arraysize)

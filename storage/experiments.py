"""Experiment registry."""
from __future__ import annotations
import time, json
from storage.database import get_db, init_db

def ensure_exp_tables():
    db=get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS experiments(
        id TEXT PRIMARY KEY,
        ts INTEGER,
        model_version TEXT, strategy_version TEXT, feature_version TEXT,
        config TEXT, dataset TEXT,
        train_start INTEGER, train_end INTEGER,
        val_start INTEGER, val_end INTEGER,
        test_start INTEGER, test_end INTEGER,
        metrics TEXT, conclusion TEXT, status TEXT
    );
    CREATE TABLE IF NOT EXISTS model_versions2(
        version TEXT PRIMARY KEY, component TEXT, created_at INTEGER, meta TEXT
    );
    """)
    return db

def create_experiment(exp_id:str, config:dict, dataset:dict, metrics:dict, conclusion:str="", status:str="EXPERIMENTAL", versions:dict|None=None):
    ensure_exp_tables(); db=get_db()
    versions=versions or {}
    db.execute("INSERT OR REPLACE INTO experiments(id,ts,model_version,strategy_version,feature_version,config,dataset,train_start,train_end,val_start,val_end,test_start,test_end,metrics,conclusion,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (exp_id,int(time.time()*1000),versions.get("model","0.1.0"),versions.get("strategy","0.1.0"),versions.get("feature","0.1.0"),
         json.dumps(config),json.dumps(dataset),dataset.get("train_start"),dataset.get("train_end"),dataset.get("val_start"),dataset.get("val_end"),dataset.get("test_start"),dataset.get("test_end"),
         json.dumps(metrics),conclusion,status))
    return exp_id

def list_experiments():
    ensure_exp_tables(); db=get_db()
    return [dict(r) for r in db.execute("SELECT * FROM experiments ORDER BY ts DESC").fetchall()]

def set_status(exp_id:str, status:str):
    db=get_db(); db.execute("UPDATE experiments SET status=? WHERE id=?", (status,exp_id))

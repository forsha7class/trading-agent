"""Researcher — external context as evidence (stub). News/sentiment never overrides risk."""
from __future__ import annotations
import time
def research(query:dict|None=None)->dict:
    # stub: architecture supports news/sentiment/on-chain injection
    # returns evidence with source/timestamp/relevance/uncertainty
    now=int(time.time()*1000)
    return {"source":"stub","timestamp":now,"evidence":[],"relevance":0.0,"uncertainty":"no external feed configured — no impact","role":"researcher"}

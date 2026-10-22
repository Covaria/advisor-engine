"""Filesystem locations shared by the assistant modules."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"
DEFAULT_HOLDINGS = DATA_DIR / "sample" / "sample_holdings.csv"
AUDIT_PATH = DATA_DIR / "audit" / "audit.jsonl"

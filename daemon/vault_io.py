"""
daemon/vault_io.py - Single Source of Truth & Safe Disk I/O Gateway
SUBrain_98 Architecture Invariant: All vault filesystem mutations MUST pass through this module.
"""

import os
import re
import json
import hashlib
import logging
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from config import VAULT_DIR

logger = logging.getLogger(__name__)

HISTORY_DIR = VAULT_DIR / ".subrain_history"
INBOX_DIR = VAULT_DIR / "_inbox"
JOURNAL_FILE = Path(__file__).parent / "write_journal.jsonl"


class ConflictError(Exception):
    def __init__(self, message: str, current_hash: str):
        super().__init__(message)
        self.current_hash = current_hash


class PathSecurityError(Exception):
    pass


def resolve_in_vault(rel_path: str, allow_inbox: bool = True) -> Path:
    """
    Sanitize and resolve a relative path strictly within VAULT_DIR.
    Prevents path traversal (e.g. '../', absolute paths, illegal characters).
    """
    clean_path = rel_path.strip().replace("\\", "/")
    
    # Remove dangerous characters
    clean_path = re.sub(r'[\:*?"<>|]', '', clean_path)
    
    # Block parent navigation
    parts = [p for p in clean_path.split("/") if p and p != "."]
    if ".." in parts:
        raise PathSecurityError(f"경로 이탈(..) 시도가 감지되었습니다: {rel_path}")
    
    target = VAULT_DIR.joinpath(*parts).resolve()
    vault_resolved = VAULT_DIR.resolve()
    
    # Ensure resolved path is strictly within VAULT_DIR
    try:
        target.relative_to(vault_resolved)
    except ValueError:
        raise PathSecurityError(f"볼트 디렉토리 범위를 벗어난 접근입니다: {rel_path}")
    
    # Ensure .md extension
    if not target.name.endswith(".md"):
        target = target.with_suffix(".md")
        
    return target


def calculate_hash(content: str) -> str:
    """Return SHA-256 hex digest of string in utf-8."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def read_note(rel_path: str) -> Optional[Dict[str, Any]]:
    """
    Read note from disk with sha256 hash and mtime.
    Returns None if file does not exist.
    """
    target = resolve_in_vault(rel_path)
    if not target.exists() or not target.is_file():
        return None
    
    content = target.read_text(encoding="utf-8")
    content_hash = calculate_hash(content)
    stat = target.stat()
    
    return {
        "rel_path": str(target.relative_to(VAULT_DIR)),
        "filename": target.name,
        "content": content,
        "hash": content_hash,
        "mtime": stat.st_mtime,
        "mtime_iso": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "is_inbox": "_inbox" in target.parts
    }


def backup_note(target_path: Path, current_content: str, actor: str = "system") -> str:
    """
    Save backup of current_content to .subrain_history/<stem>/<ts>_<hash[:8]>.md.
    Returns backup_id.
    """
    stem = target_path.stem
    file_history_dir = HISTORY_DIR / stem
    file_history_dir.mkdir(parents=True, exist_ok=True)
    
    content_hash = calculate_hash(current_content)
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"{now_str}_{content_hash[:8]}.md"
    backup_path = file_history_dir / backup_filename
    
    backup_path.write_text(current_content, encoding="utf-8")
    
    # Prune old backups, keep last 30
    try:
        all_backups = sorted(file_history_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in all_backups[30:]:
            old.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"[vault_io] 백업 정리 중 오류 (무시됨): {e}")
        
    return f"{stem}/{backup_filename}"


def log_journal(entry: Dict[str, Any]):
    """Append entry to write_journal.jsonl."""
    try:
        entry["timestamp"] = datetime.datetime.now().isoformat()
        with JOURNAL_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"[vault_io] 저널 기록 실패: {e}")


def safe_write(
    rel_path: str,
    content: str,
    expected_hash: Optional[str] = None,
    reason: str = "일반 수정",
    actor: str = "user"
) -> Dict[str, Any]:
    """
    Safe, atomic file write with hash conflict detection, automatic backup, and journaling.
    """
    target = resolve_in_vault(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    
    backup_id = None
    old_hash = None
    
    if target.exists():
        existing_content = target.read_text(encoding="utf-8")
        old_hash = calculate_hash(existing_content)
        
        # Conflict detection
        if expected_hash and old_hash != expected_hash:
            logger.warning(f"[vault_io] 충돌 감지! {rel_path} (기대: {expected_hash[:8]}, 디스크: {old_hash[:8]})")
            raise ConflictError(
                f"파일이 외부(옵시디언 등)에서 변경되었습니다. 최신 내용을 확인하세요.",
                current_hash=old_hash
            )
            
        backup_id = backup_note(target, existing_content, actor=actor)
    
    # Atomic write via temp file
    new_hash = calculate_hash(content)
    tmp_path = target.with_suffix(".md.tmp")
    
    try:
        tmp_path.write_text(content, encoding="utf-8")
        # Ensure flush to physical disk
        with open(tmp_path, "a", encoding="utf-8") as f:
            f.flush()
            os.fsync(f.fileno())
            
        os.replace(tmp_path, target)
        logger.info(f"[vault_io] 💾 원자적 디스크 쓰기 성공: {target.name} (해시: {new_hash[:8]}, 백업: {backup_id})")
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        logger.error(f"[vault_io] 쓰기 실패: {e}", exc_info=True)
        raise
        
    log_journal({
        "rel_path": str(target.relative_to(VAULT_DIR)),
        "filename": target.name,
        "actor": actor,
        "reason": reason,
        "old_hash": old_hash,
        "new_hash": new_hash,
        "backup_id": backup_id,
        "bytes": len(content.encode("utf-8"))
    })
    
    return {
        "success": True,
        "rel_path": str(target.relative_to(VAULT_DIR)),
        "filename": target.name,
        "new_hash": new_hash,
        "backup_id": backup_id
    }


def resolve_unique_inbox_path(preferred_name: str) -> Tuple[Path, str]:
    """
    Generate unique filename inside _inbox/ directory.
    If name already exists, appends _2, _3 etc.
    Returns (resolved_Path, relative_string).
    """
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    
    clean_name = re.sub(r'[\:*?"<>|\\/]', '', preferred_name).strip()
    if not clean_name:
        clean_name = f"메모_{datetime.date.today().strftime('%m%d_%H%M%S')}"
    if not clean_name.endswith(".md"):
        clean_name += ".md"
        
    stem = clean_name[:-3]
    candidate = INBOX_DIR / f"{stem}.md"
    counter = 2
    while candidate.exists():
        candidate = INBOX_DIR / f"{stem}_{counter}.md"
        counter += 1
        
    rel = str(candidate.relative_to(VAULT_DIR))
    return candidate, rel


def move_from_inbox(filename: str, target_subfolder: str = "") -> Dict[str, Any]:
    """
    Move reviewed note from _inbox/ to main vault or designated subfolder.
    """
    src = INBOX_DIR / filename if not filename.startswith("_inbox") else VAULT_DIR / filename
    if not src.exists():
        return {"success": False, "error": f"_inbox 내에 {filename} 파일이 없습니다."}
        
    dest_dir = VAULT_DIR / target_subfolder if target_subfolder else VAULT_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    
    # Check collision at destination
    stem = src.stem
    counter = 2
    while dest.exists():
        dest = dest_dir / f"{stem}_{counter}.md"
        counter += 1
        
    os.replace(src, dest)
    logger.info(f"[vault_io] 📦 인박스에서 본 볼트로 승격 이동: {src.name} -> {dest.relative_to(VAULT_DIR)}")
    
    return {
        "success": True,
        "old_path": str(src.relative_to(VAULT_DIR)),
        "new_path": str(dest.relative_to(VAULT_DIR)),
        "new_filename": dest.name
    }


def list_backups(filename: str) -> List[Dict[str, Any]]:
    """List available backups for a note."""
    stem = Path(filename).stem
    file_history_dir = HISTORY_DIR / stem
    if not file_history_dir.exists():
        return []
        
    results = []
    for f in sorted(file_history_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = f.stat()
        results.append({
            "backup_id": f"{stem}/{f.name}",
            "filename": f.name,
            "size": stat.st_size,
            "created_at": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    return results


def restore_backup(rel_path: str, backup_id: str, actor: str = "user") -> Dict[str, Any]:
    """Restore file from a specified backup_id, safely backing up current version as well."""
    backup_path = HISTORY_DIR / backup_id
    if not backup_path.exists():
        raise FileNotFoundError(f"백업본을 찾을 수 없습니다: {backup_id}")
        
    backup_content = backup_path.read_text(encoding="utf-8")
    return safe_write(rel_path, backup_content, expected_hash=None, reason=f"백업본 복원: {backup_id}", actor=actor)

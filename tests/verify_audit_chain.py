import hashlib
from datetime import datetime, timezone
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base, AuditLog, User, Organisation, OrgMember
from app.services.audit_service import AuditService

# 1. Setup in-memory DB for pure cryptographic test
engine = create_engine("sqlite:///:memory:")
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)
db = Session()

def test_audit_chain():
    print("\n[Audit Chain Test]")
    org_id = str(uuid.uuid4())
    
    # Create 3 logs
    print("Creating 3 logs...")
    AuditService.log_action(db, org_id, None, "test@local", "action.1", "test", "1")
    AuditService.log_action(db, org_id, None, "test@local", "action.2", "test", "2")
    AuditService.log_action(db, org_id, None, "test@local", "action.3", "test", "3")
    db.commit()
    
    # Verify initial chain
    is_valid = AuditService.verify_chain(db, org_id)
    print(f"Initial Chain Valid: {is_valid}")
    assert is_valid == True
    
    # 2. Tamper: Delete the middle log
    print("\nTampering: Deleting middle log (action.2)...")
    mid_log = db.query(AuditLog).filter(AuditLog.action == "action.2").first()
    db.delete(mid_log)
    db.commit()
    
    # Verify tampering detected
    is_valid_after_del = AuditService.verify_chain(db, org_id)
    print(f"Chain Valid After Deletion: {is_valid_after_del}")
    assert is_valid_after_del == False
    
    # 3. Tamper: Mutate data in a log
    print("\nTampering: Mutating data in action.3...")
    # Re-create the chain first to reset
    db.query(AuditLog).delete()
    AuditService.log_action(db, org_id, None, "test@local", "a.1", "t", "1")
    AuditService.log_action(db, org_id, None, "test@local", "a.2", "t", "2")
    db.commit()
    
    log1 = db.query(AuditLog).filter(AuditLog.action == "a.1").first()
    log1.action = "MALICIOUS_MUTATION"
    db.commit()
    
    is_valid_after_mutation = AuditService.verify_chain(db, org_id)
    print(f"Chain Valid After Mutation: {is_valid_after_mutation}")
    assert is_valid_after_mutation == False
    
    print("\n[RESULT] AUDIT CHAIN VERIFIED: Cryptographic proof of governance is operational.")

if __name__ == "__main__":
    try:
        test_audit_chain()
    except Exception as e:
        print(f"Test Failed: {e}")

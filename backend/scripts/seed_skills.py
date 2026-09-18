"""Run from the backend container: python scripts/seed_skills.py."""

SKILLS = [
    {"code": "algebra.integer_operations", "name": "Phép tính số nguyên", "grade_min": 6, "grade_max": 8},
    {"code": "algebra.distributive_property", "name": "Tính chất phân phối", "grade_min": 6, "grade_max": 8},
    {"code": "algebra.linear_equation", "name": "Phương trình bậc nhất một ẩn", "grade_min": 8, "grade_max": 9},
    {"code": "algebra.factorization", "name": "Phân tích đa thức thành nhân tử", "grade_min": 8, "grade_max": 9},
    {"code": "algebra.rational_expression.domain", "name": "Điều kiện xác định phân thức", "grade_min": 8, "grade_max": 9},
    {"code": "algebra.rational_expression.operations", "name": "Phép toán phân thức", "grade_min": 8, "grade_max": 9},
]

if __name__ == "__main__":
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    from sqlalchemy import select
    from app.db.session import SessionLocal, Base, engine
    from app.models import Skill

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for item in SKILLS:
            if not db.scalar(select(Skill).where(Skill.code == item["code"])):
                db.add(Skill(subject="math", prerequisite_codes="", **item))
        db.commit()
    print(f"Seeded {len(SKILLS)} skill definitions")

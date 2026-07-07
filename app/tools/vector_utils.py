"""pgvector 리터럴 변환 — 인덱싱(upsert)과 검색(search_rules)이 공유."""


def to_vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"

"""골든 v2 픽스처 레지스트리 — org 9100번대·expense 91000번대 순차 할당.

eval/fixtures/mock_backend.json 구조(tests/test_mock_fixture.py 계약)를 그대로 따른다:
organizations[str(id)] = {label, team_type, auto_approve, auto_approve_limit,
budget:{total_budget, spent}, expense_history} — escalation_threshold 키는 절대 없음.
expenses[str(id)] = {title, amount, date, description} — category 없음(§4.2).
"""

ORG_BASE = 9100
# v1은 9001~9027만 쓰고 golden_rule_axis.json은 9001을 재사용한다 — 9100 이상은 전부
# 비어 있다. GOLDEN_TEAM_ID_RANGE(9000~9999, eval/run_eval_real.py)를 넘지 않는 선에서
# 상한을 넉넉히 잡는다(circumvention 유형만도 동시성 안전을 위해 케이스당 조직 1개 필요).
ORG_MAX = 9999
EXPENSE_BASE = 91000
EXPENSE_MAX = 91999


class FixtureRegistry:
    """유형별 생성기가 공유하는 ID 카운터 + 누적된 organizations/expenses/histories."""

    def __init__(self) -> None:
        self._next_org = ORG_BASE
        self._next_expense = EXPENSE_BASE
        self.organizations: dict[str, dict] = {}
        self.expenses: dict[str, dict] = {}
        self.expense_histories: dict[str, list[dict]] = {}
        self.policy_documents: dict[str, str] = {}

    def add_org(
        self,
        *,
        label: str,
        team_type: str,
        auto_approve: bool = True,
        auto_approve_limit: int = 50_000,
        total_budget: int,
        spent: int,
        expense_history: str = "default",
        policy_document: str | None = None,
    ) -> int:
        if self._next_org > ORG_MAX:
            raise RuntimeError(f"org id 대역(9100~9199) 소진 — 마지막 label: {label}")
        org_id = self._next_org
        self._next_org += 1
        self.organizations[str(org_id)] = {
            "label": label,
            "team_type": team_type,
            "auto_approve": auto_approve,
            "auto_approve_limit": auto_approve_limit,
            "budget": {"total_budget": total_budget, "spent": spent},
            "expense_history": expense_history,
        }
        if policy_document is not None:
            self.policy_documents[str(org_id)] = policy_document
        return org_id

    def add_expense(self, *, title: str, amount: int, date: str, description: str = "") -> int:
        if self._next_expense > EXPENSE_MAX:
            raise RuntimeError(f"expense id 대역(91000~91999) 소진 — 마지막 title: {title}")
        expense_id = self._next_expense
        self._next_expense += 1
        self.expenses[str(expense_id)] = {
            "title": title,
            "amount": amount,
            "date": date,
            "description": description,
        }
        return expense_id

    def ensure_history(self, name: str, rows: list[dict]) -> str:
        """expense_history 이름 등록 — org.expense_history가 참조 무결성을 지키게 한다
        (test_organization_expense_history_references_exist)."""
        self.expense_histories[name] = rows
        return name

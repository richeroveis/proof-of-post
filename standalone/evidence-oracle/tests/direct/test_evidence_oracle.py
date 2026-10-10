"""Direct-mode tests for the standalone EvidenceOracle contract.

Direct mode executes only the leader function of run_nondet (validators are
captured, not run), so these tests cover: URL/statement validation, the https /
SSRF guard, bond gating, the propose -> resolve state machine, the three verdict
branches and their slashing/refund accounting, the challenge outcome machine
(upheld slashes the challenger; a flip updates the verdict and only releases a
*held* bond), error classification ([EXTERNAL] 4xx, [TRANSIENT] 5xx, [LLM_ERROR]
bad verdict), access control, pagination, and the comparative validator (via
direct_vm.run_validator).

Native GEN transfers (emit_transfer) are a no-op in direct mode, so we assert
the contract's internal accounting rather than recipient wallet balances.
"""

import json

MIN_BOND = 10 ** 18  # 1 GEN, atto-scale u256
URL = "https://example.com/receipt"
STATEMENT = "The total shown is 42 dollars"
PAGE = "Invoice total: 42 dollars. Thank you for your business."


def _hex(addr) -> str:
    """Normalize a fixture address to a comparable 0x-hex string."""
    if isinstance(addr, (bytes, bytearray)):
        return "0x" + bytes(addr).hex()
    return str(addr)


def _deploy(direct_deploy):
    return direct_deploy("standalone/evidence-oracle/contract.py", MIN_BOND)


def _mock_page(direct_vm, status=200, body=PAGE):
    direct_vm.mock_web(r"example\.com", {"method": "GET", "status": status, "body": body})


def _mock_verdict(direct_vm, verdict, value="42"):
    direct_vm.mock_llm(
        r"evidence adjudicator",
        json.dumps({"verdict": verdict, "value": value, "quote": "total: 42", "reason": "fixture"}),
    )


def _propose(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    claim_id = contract.propose(URL, STATEMENT)
    direct_vm.value = 0
    return contract, claim_id


# ------------------------------------------------------------------ deployment
def test_deploy_initial_state(direct_vm, direct_deploy, direct_owner):
    contract = _deploy(direct_deploy)
    stats = contract.get_stats()
    assert int(stats["total"]) == 0
    assert int(stats["min_bond"]) == MIN_BOND
    assert int(stats["slashed_total"]) == 0
    assert stats["owner"].lower() == _hex(direct_owner).lower()


# -------------------------------------------------------------------- validation
def test_propose_empty_url_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("Empty url"):
        contract.propose("   ", STATEMENT)


def test_propose_non_https_url_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("Url must be https"):
        contract.propose("http://example.com/x", STATEMENT)


def test_propose_loopback_url_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("Url host is not allowed"):
        contract.propose("https://localhost/admin", STATEMENT)


def test_propose_private_range_url_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("Url host is not allowed"):
        contract.propose("https://169.254.169.254/meta", STATEMENT)


def test_propose_credentials_url_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("credentials"):
        contract.propose("https://user:pass@example.com/x", STATEMENT)


def test_propose_empty_statement_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("Empty statement"):
        contract.propose(URL, "   ")


def test_propose_below_min_bond_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND - 1
    with direct_vm.expect_revert("Bond below minimum"):
        contract.propose(URL, STATEMENT)


def test_propose_creates_pending_claim(direct_vm, direct_deploy, direct_alice):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    claim = contract.get_claim(claim_id)
    assert claim["status"] == "PENDING"
    assert claim["proposer"].lower() == _hex(direct_alice).lower()
    assert int(claim["bond"]) == MIN_BOND
    assert claim["url"] == URL
    assert contract.get_stats()["total"] == "1"


def test_view_missing_claim_returns_empty(direct_vm, direct_deploy):
    contract = _deploy(direct_deploy)
    assert contract.get_claim(999) == {}


# ---------------------------------------------------------------------- resolve
def test_resolve_supported_refunds(direct_vm, direct_deploy, direct_alice):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "SUPPORTED")
    status = contract.resolve(claim_id)
    assert status == "SUPPORTED"
    assert contract.get_stats()["supported"] == "1"
    assert contract.get_stats()["slashed_total"] == "0"
    assert contract.is_supported(claim_id) is True


def test_resolve_contradicted_slashes(direct_vm, direct_deploy, direct_alice):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "CONTRADICTED", value="40")
    status = contract.resolve(claim_id)
    assert status == "CONTRADICTED"
    assert contract.get_stats()["contradicted"] == "1"
    assert contract.get_stats()["slashed_total"] == str(MIN_BOND)
    assert contract.is_supported(claim_id) is False


def test_resolve_unverifiable_refunds(direct_vm, direct_deploy, direct_alice):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "UNVERIFIABLE", value="")
    status = contract.resolve(claim_id)
    assert status == "UNVERIFIABLE"
    assert contract.get_stats()["unverifiable"] == "1"
    assert contract.get_stats()["slashed_total"] == "0"


def test_resolve_external_error_reverts(direct_vm, direct_deploy, direct_alice):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm, status=404, body="not found")
    with direct_vm.expect_revert("EXTERNAL"):
        contract.resolve(claim_id)


def test_resolve_transient_error_reverts(direct_vm, direct_deploy, direct_alice):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm, status=503, body="temporarily unavailable")
    with direct_vm.expect_revert("TRANSIENT"):
        contract.resolve(claim_id)


def test_resolve_invalid_verdict_is_llm_error(direct_vm, direct_deploy, direct_alice):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "MAYBE")  # not in the allowed verdict set
    with direct_vm.expect_revert("LLM_ERROR"):
        contract.resolve(claim_id)


def test_resolve_unauthorized_reverts(direct_vm, direct_deploy, direct_alice, direct_charlie):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "SUPPORTED")
    with direct_vm.prank(direct_charlie):
        with direct_vm.expect_revert("Not authorized to resolve"):
            contract.resolve(claim_id)


def test_resolve_twice_reverts(direct_vm, direct_deploy, direct_alice):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "SUPPORTED")
    contract.resolve(claim_id)
    with direct_vm.expect_revert("Claim already settled"):
        contract.resolve(claim_id)


# -------------------------------------------------------------------- challenge
def test_challenge_by_proposer_reverts(direct_vm, direct_deploy, direct_alice):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "SUPPORTED")
    contract.resolve(claim_id)
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("Proposer cannot challenge"):
        contract.challenge(claim_id)


def test_challenge_before_settlement_reverts(direct_vm, direct_deploy, direct_alice, direct_charlie):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_charlie
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("Claim not settled yet"):
        contract.challenge(claim_id)


def test_challenge_upheld_slashes_challenger(direct_vm, direct_deploy, direct_alice, direct_charlie):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "SUPPORTED")
    contract.resolve(claim_id)

    direct_vm.sender = direct_charlie
    direct_vm.value = MIN_BOND
    status = contract.challenge(claim_id)  # same verdict -> upheld
    assert status == "SUPPORTED"
    claim = contract.get_claim(claim_id)
    assert int(claim["challenge_count"]) == 1
    # Challenger stake is slashed into the owner pool.
    assert contract.get_stats()["slashed_total"] == str(MIN_BOND)


def test_challenge_flip_releases_held_bond(direct_vm, direct_deploy, direct_alice, direct_charlie):
    # First settle as CONTRADICTED so the proposer bond is held in the pool.
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "CONTRADICTED", value="40")
    contract.resolve(claim_id)
    assert contract.get_stats()["slashed_total"] == str(MIN_BOND)

    # Challenge flips to SUPPORTED: counters move, held bond is released.
    direct_vm.clear_mocks()
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "SUPPORTED")
    direct_vm.sender = direct_charlie
    direct_vm.value = MIN_BOND
    status = contract.challenge(claim_id)
    assert status == "SUPPORTED"
    assert contract.get_stats()["supported"] == "1"
    assert contract.get_stats()["contradicted"] == "0"
    # Held bond released AND challenger stake returned -> pool back to zero.
    assert contract.get_stats()["slashed_total"] == "0"


def test_challenge_limit(direct_vm, direct_deploy, direct_alice, direct_charlie):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "SUPPORTED")
    contract.resolve(claim_id)

    direct_vm.sender = direct_charlie
    direct_vm.value = MIN_BOND
    contract.challenge(claim_id)  # 1
    contract.challenge(claim_id)  # 2
    with direct_vm.expect_revert("Challenge limit reached"):
        contract.challenge(claim_id)  # 3 -> capped at MAX_CHALLENGES(2)


# ----------------------------------------------------------------------- admin
def test_withdraw_slashed_owner_only(direct_vm, direct_deploy, direct_alice, direct_charlie):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "CONTRADICTED", value="40")
    contract.resolve(claim_id)

    with direct_vm.prank(direct_charlie):
        with direct_vm.expect_revert("Only owner"):
            contract.withdraw_slashed(_hex(direct_charlie), MIN_BOND)


def test_withdraw_slashed_insufficient_balance(direct_vm, direct_deploy, direct_alice, direct_owner, direct_charlie):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "CONTRADICTED", value="40")
    contract.resolve(claim_id)

    # Owner passes the availability check, but direct mode holds no native
    # balance for the contract, so the transfer guard fires.
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Insufficient contract balance"):
        contract.withdraw_slashed(_hex(direct_charlie), MIN_BOND)


def test_list_claims_pagination(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.propose("https://example.com/a", "first claim")
    contract.propose("https://example.com/b", "second claim")

    page = contract.list_claims(0, 1)
    assert len(page) == 1
    assert page[0]["url"] == "https://example.com/a"
    assert contract.list_claims(5, 5) == []


# -------------------------------------------------------------------- validator
def test_validator_agrees_on_independent_match(direct_vm, direct_deploy, direct_alice):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "SUPPORTED")
    contract.resolve(claim_id)
    # Validator re-derives from the same stable mocks -> agrees.
    assert direct_vm.run_validator() is True


def test_validator_disagrees_on_verdict_mismatch(direct_vm, direct_deploy, direct_alice):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "SUPPORTED")  # validator derives SUPPORTED
    contract.resolve(claim_id)

    mismatched = {"verdict": "CONTRADICTED", "value": "42", "quote": "x", "reason": "leader fixture"}
    assert direct_vm.run_validator(leader_result=mismatched) is False


def test_validator_accepts_value_within_tolerance(direct_vm, direct_deploy, direct_alice):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "SUPPORTED", value="100.00")  # validator derives 100.00
    contract.resolve(claim_id)

    # Leader reports 100.5 -> same verdict, value within 1% -> agree.
    leader = {"verdict": "SUPPORTED", "value": "100.5", "quote": "x", "reason": "within band"}
    assert direct_vm.run_validator(leader_result=leader) is True


def test_validator_disagrees_on_llm_error(direct_vm, direct_deploy, direct_alice):
    contract, claim_id = _propose(direct_vm, direct_deploy, direct_alice)
    _mock_page(direct_vm)
    _mock_verdict(direct_vm, "SUPPORTED")
    contract.resolve(claim_id)
    # A leader that hit an LLM error must be rejected to force rotation.
    assert direct_vm.run_validator(leader_error=Exception("[LLM_ERROR] bad")) is False

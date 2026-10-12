"""Integration tests for the standalone EvidenceOracle against a real network.

Under full leader+validator consensus these verify what direct mode cannot: that
the contract deploys on the actual GenVM and its deterministic surface agrees
across validators - input/URL validation, the SSRF guard, the bond gate, the
propose -> resolve state machine's *terminal* transitions, access control, and
the views.

The nondeterministic `resolve`/`challenge` verdict (validators fetch a live URL
and re-derive a natural-language decision) is deliberately NOT pinned to an
exact status here: a real verdict is not reproducible and must not be asserted.
The comparative-validator logic is covered by the direct-mode suite instead.

Run explicitly against a reachable, funded network, e.g.:
    $env:RUN_INTEGRATION='1'
    gltest standalone/evidence-oracle/tests/integration/ -v -s --network studio-dev
"""

import os

import pytest
from gltest import get_contract_factory
from gltest.assertions import tx_execution_succeeded

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="Set RUN_INTEGRATION=1 and target a real network to run integration tests",
)

MIN_BOND = 10 ** 18
URL = "https://example.com/receipt"
STATEMENT = "The total shown is 42 dollars"
TERMINAL = {"SUPPORTED", "CONTRADICTED", "UNVERIFIABLE"}


def _deploy():
    factory = get_contract_factory(contract_file_path="standalone/evidence-oracle/contract.py")
    return factory.deploy(args=[MIN_BOND])


def test_deploy_and_read_state():
    contract = _deploy()
    stats = contract.get_stats(args=[]).call()
    assert int(stats["total"]) == 0
    assert int(stats["min_bond"]) == MIN_BOND


def test_propose_records_pending_claim():
    contract = _deploy()
    tx = contract.propose(args=[URL, STATEMENT], value=MIN_BOND).transact()
    assert tx_execution_succeeded(tx)
    assert int(contract.get_stats(args=[]).call()["total"]) == 1
    claim = contract.get_claim(args=[0]).call()
    assert claim["status"] == "PENDING"


def test_propose_below_bond_reverts():
    contract = _deploy()
    tx = contract.propose(args=[URL, STATEMENT], value=MIN_BOND - 1).transact()
    assert not tx_execution_succeeded(tx)
    assert int(contract.get_stats(args=[]).call()["total"]) == 0


def test_propose_non_https_url_reverts():
    contract = _deploy()
    tx = contract.propose(args=["http://example.com/x", STATEMENT], value=MIN_BOND).transact()
    assert not tx_execution_succeeded(tx)


def test_propose_loopback_url_reverts():
    contract = _deploy()
    tx = contract.propose(args=["https://localhost/admin", STATEMENT], value=MIN_BOND).transact()
    assert not tx_execution_succeeded(tx)


def test_challenge_before_settlement_reverts():
    """Challenging a PENDING claim is a deterministic revert every validator
    reaches identically, independent of any LLM call."""
    contract = _deploy()
    sub = contract.propose(args=[URL, STATEMENT], value=MIN_BOND).transact()
    assert tx_execution_succeeded(sub)
    bad = contract.challenge(args=[0], value=MIN_BOND).transact()
    assert not tx_execution_succeeded(bad)

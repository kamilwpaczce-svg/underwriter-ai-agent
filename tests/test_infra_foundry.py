"""Etap 14: projekt Foundry w Terraform - nowe konto AIServices, nie hub classic."""

import re
from pathlib import Path

TF = (Path(__file__).resolve().parent.parent / "infra" / "terraform" / "foundry.tf").read_text(encoding="utf-8")


def _jest(wzorzec: str) -> bool:
    # terraform fmt wyrownuje "=" spacjami - literalne asserty pekaja po fmt (przeglad p. 3)
    return re.search(wzorzec, TF) is not None


def test_konto_aiservices_z_projektem():
    assert _jest(r'\bkind\s+=\s+"AIServices"')
    assert _jest(r"\bproject_management_enabled\s+=\s+true\b")
    assert 'resource "azurerm_cognitive_account_project"' in TF
    assert _jest(r"\blocal_auth_enabled\s+=\s+false\b")


def test_bez_huba_classic_i_bez_ruszania_konta_z_bicepa():
    assert "azurerm_ai_foundry" not in TF
    assert "uw-demo-aoai-xx1" not in TF


def test_sedzia_4o_mini_i_storage_tylko_warunkowo():
    assert len(re.findall(r"\bcount\s+=\s+var\.wdroz_sedziego_4o_mini\s+\?\s+1\s+:\s+0", TF)) == 1
    # polaczenie + data storage + 2 role Storage Blob Data Owner
    assert len(re.findall(r"\bcount\s+=\s+var\.polacz_storage\s+\?\s+1\s+:\s+0", TF)) == 4


def test_role_storage_dla_wlasciciela_i_projektu():
    assert _jest(r"principal_id\s+=\s+azurerm_cognitive_account_project\.ewaluacja\.identity\[0\]\.principal_id")
    assert len(re.findall(r'role_definition_name\s+=\s+"Storage Blob Data Owner"', TF)) == 2

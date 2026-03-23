#!/usr/bin/env python3
"""Simulate competition runs against our deployed service using sandbox credentials.

Sends one prompt per task type to verify all 30 handlers work.
Uses the sandbox (not competition proxy) so it's free and unlimited.

Usage:
    python scripts/sim_all_tasks.py [--service-url URL]
"""

from __future__ import annotations

import argparse
import time

import requests

# One test prompt per task type, in various languages
TASK_PROMPTS = {
    "create_employee": "Opprett en ansatt med navn Test Simsen, e-post sim@test.no. Han skal være administrator.",
    "update_employee": "Oppdater telefonnummeret til Test Simsen til 99887766.",
    "create_customer": "Create customer Sim Corp AS with org number 999888777 and email sim@corp.no.",
    "update_customer": "Actualice el correo electrónico del cliente Sim Corp AS a nuevo@corp.no.",
    "create_product": "Opprett produkt Simuleringstjeneste med produktnummer SIM001 og pris 1500 kr.",
    "create_department": "Erstellen Sie die Abteilung Simulation mit Abteilungsnummer 42.",
    "create_project": "Opprett prosjektet Sim-prosjekt knyttet til kunden Sim Corp AS. Prosjektleder er Test Simsen.",
    "assign_role": "Gi Test Simsen administratortilgang.",
    "enable_module": "Aktiver modulen moduleProject.",
    "create_order": "Opprett en ordre for kunden Sim Corp AS med 2 stk Simuleringstjeneste à 1500 kr.",
    "create_invoice": "Opprett en faktura til kunden Sim Corp AS for 3000 kr for Simuleringstjeneste.",
    "send_invoice": "Send faktura nummer 1 til kunden.",
    "register_payment": "Registrer full betaling på 3000 kr for fakturaen til Sim Corp AS for Simuleringstjeneste.",
    "create_credit_note": "Opprett kreditnota for fakturaen til Sim Corp AS.",
    "create_travel_expense": "Opprett reiseregning for Test Simsen. Reise til Oslo, 2 dager. Flybillett 3000 kr, hotell 1500 kr.",
    "deliver_travel_expense": "Lever reiseregning nummer 1.",
    "approve_travel_expense": "Godkjenn reiseregning nummer 1.",
    "delete_travel_expense": "Slett reiseregningen til Test Simsen.",
    "link_project_customer": "Knytt prosjektet Sim-prosjekt til kunden Sim Corp AS.",
    "create_activity": "Opprett aktiviteten Simuleringsaktivitet.",
    "update_project": "Oppdater prosjektet Sim-prosjekt med sluttdato 2026-12-31.",
    "create_asset": "Opprett eiendelen Simuleringsmaskin med anskaffelseskost 50000.",
    "update_asset": "Oppdater eiendelen Simuleringsmaskin med beskrivelse Testutstyr.",
    "create_voucher": "Opprett et bilag med dato 2026-03-20. Debet konto 5000 beløp 10000, kredit konto 2920 beløp 10000. Beskrivelse: Lønnsbilag sim.",
    "reverse_voucher": "Reverser bilag nummer 1.",
    "delete_voucher": "Slett bilag nummer 1.",
    "bank_reconciliation": "Utfør bankavstemming for konto 1920.",
    "ledger_correction": "Opprett korreksjon: debet konto 4000 beløp 5000, kredit konto 2400 beløp 5000.",
    "year_end_closing": "Utfør årsoppgjør for 2025.",
    "balance_sheet_report": "Hent balanserapport fra 2026-01-01 til 2026-03-20.",
    "create_supplier": "Registrer leverandøren Sim Leverandør AS med org.nr 998877666 og e-post sim@leverandor.no.",
    "create_dimension_voucher": "Opprett en fri regnskapsdimensjon Prosjekttype med verdiene Intern og Ekstern. Bokfør et bilag på konto 6340 for 15000 kr knyttet til Intern.",
    "log_timesheet": "Logg 8 timer for Test Simsen på aktiviteten Utvikling i prosjektet Sim-prosjekt. Timepris 950 kr.",
    "run_payroll": "Kjør lønn for Test Simsen for denne måneden. Grunnlønn er 40000 kr. Legg til bonus 5000 kr.",
    "delete_customer": "Slett kunden Sim Corp AS.",
    "delete_department": "Slett avdelingen Simulation.",
    "delete_order": "Slett ordre nummer 1.",
    "delete_product": "Slett produktet Simuleringstjeneste.",
    "delete_project": "Slett prosjektet Sim-prosjekt.",
    "delete_supplier": "Slett leverandøren Sim Leverandør AS.",
    "update_department": "Oppdater avdelingen Simulation med ny avdelingsleder Test Simsen.",
}

SANDBOX_CREDS = {
    "base_url": "https://kkpqfuj-amager.tripletex.dev/v2",
    "session_token": "eyJ0b2tlbklkIjoyMTQ3NjI5NjQ5LCJ0b2tlbiI6IjYzZWU1MTFlLTg2ZDAtNDk4Mi04NDY1LTFmZDIwNjBlNGE1ZSJ9",
}


def run_sim(service_url: str, task_type: str, prompt: str) -> dict:
    """Send a single simulation request."""
    payload = {
        "prompt": prompt,
        "files": [],
        "tripletex_credentials": SANDBOX_CREDS,
    }
    start = time.time()
    try:
        resp = requests.post(f"{service_url}/solve", json=payload, timeout=120)
        elapsed = time.time() - start
        return {
            "task_type": task_type,
            "status_code": resp.status_code,
            "response": resp.json(),
            "elapsed_s": round(elapsed, 1),
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "task_type": task_type,
            "status_code": 0,
            "error": str(e),
            "elapsed_s": round(elapsed, 1),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--service-url",
        default="https://tripletex-agent-2-1084086839157.europe-west1.run.app",
    )
    parser.add_argument("--tasks", nargs="*", help="Specific task types to test (default: all)")
    args = parser.parse_args()

    tasks = args.tasks or list(TASK_PROMPTS.keys())
    print(f"Simulating {len(tasks)} tasks against {args.service_url}")
    print(f"{'=' * 70}")

    results = []
    for task_type in tasks:
        prompt = TASK_PROMPTS.get(task_type)
        if not prompt:
            print(f"  SKIP {task_type} — no prompt defined")
            continue
        print(f"  Running {task_type}...", end=" ", flush=True)
        result = run_sim(args.service_url, task_type, prompt)
        status = "OK" if result["status_code"] == 200 else f"FAIL({result['status_code']})"
        print(f"{status} in {result['elapsed_s']}s")
        results.append(result)

    # Summary
    ok = sum(1 for r in results if r["status_code"] == 200)
    print(f"\n{'=' * 70}")
    print(f"Results: {ok}/{len(results)} succeeded")
    fails = [r for r in results if r["status_code"] != 200]
    if fails:
        print("Failures:")
        for f in fails:
            print(f"  {f['task_type']}: {f.get('error', f.get('status_code'))}")


if __name__ == "__main__":
    main()

"""Post-handler self-verification: GET back created entities and compare fields.

Runs after each handler, within the same request. Costs 1 GET + optional 1 PUT.
Logs PASS/FAIL per field so we can diagnose scoring gaps in Cloud Run logs.
"""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient

logger = logging.getLogger(__name__)


# Verification config: task_type -> (endpoint_template, fields_to_fetch, field_checks)
# field_checks maps: api_field -> (param_key, comparator)
# Comparators: "eq" (exact), "eq_ci" (case-insensitive), "ref_id" (nested .id),
#              "exists" (just must be non-null), "numeric" (within 1% tolerance)
VERIFY_CONFIG: dict[str, dict[str, Any]] = {
    "create_customer": {
        "endpoint": "/customer/{id}",
        "fields": "id,name,email,phoneNumber,organizationNumber,"
        "invoiceEmail,postalAddress(addressLine1,postalCode,city)",
        "checks": {
            "name": ("name", "eq_ci"),
            "email": ("email", "eq_ci"),
            "phoneNumber": ("phoneNumber", "eq"),
            "organizationNumber": ("organizationNumber", "eq"),
            "invoiceEmail": ("invoiceEmail", "eq_ci"),
        },
    },
    "create_invoice": {
        "endpoint": "/invoice/{id}",
        "fields": "id,invoiceNumber,amount,customer(id,name),"
        "invoiceDate,invoiceDueDate,isCreditNote",
        "checks": {
            "customer": ("customer", "ref_id"),
            "invoiceDate": ("invoiceDate", "eq"),
        },
    },
    "create_voucher": {
        "endpoint": "/ledger/voucher/{id}",
        "fields": "id,number,date,description,"
        "postings(account(number),amountGross,supplier(id),customer(id))",
        "checks": {
            "date": ("date", "eq"),
            "description": ("description", "eq_ci"),
        },
    },
    "create_employee": {
        "endpoint": "/employee/{id}",
        "fields": "id,firstName,lastName,email,dateOfBirth,"
        "nationalIdentityNumber,bankAccountNumber,"
        "phoneNumberMobile,department(id,name)",
        "checks": {
            "firstName": ("firstName", "eq_ci"),
            "lastName": ("lastName", "eq_ci"),
            "email": ("email", "eq_ci"),
            "dateOfBirth": ("dateOfBirth", "eq"),
            "nationalIdentityNumber": ("nationalIdentityNumber", "eq"),
            "bankAccountNumber": ("bankAccountNumber", "eq"),
            "phoneNumberMobile": ("phoneNumberMobile", "eq"),
        },
    },
    "create_product": {
        "endpoint": "/product/{id}",
        "fields": "id,name,number,priceExcludingVatCurrency,"
        "priceIncludingVatCurrency,vatType(id,percentage)",
        "checks": {
            "name": ("name", "eq_ci"),
            "number": ("number", "eq"),
            "priceExcludingVatCurrency": (
                "priceExcludingVatCurrency",
                "numeric",
            ),
        },
    },
    "create_department": {
        "endpoint": "/department/{id}",
        "fields": "id,name,departmentNumber,departmentManager(id)",
        "checks": {
            "name": ("name", "eq_ci"),
            "departmentNumber": ("departmentNumber", "eq"),
        },
    },
    "create_project": {
        "endpoint": "/project/{id}",
        "fields": "id,name,number,startDate,endDate,isInternal,"
        "isFixedPrice,fixedprice,customer(id,name),"
        "projectManager(id,firstName,lastName)",
        "checks": {
            "name": ("name", "eq_ci"),
            "startDate": ("startDate", "eq"),
            "isInternal": ("isInternal", "eq"),
            "customer": ("customer", "ref_id"),
        },
    },
    "register_payment": {
        "endpoint": "/invoice/{id}",
        "fields": "id,amount,amountOutstanding,customer(id,name)",
        "checks": {
            "amountOutstanding": (None, "zero_outstanding"),
        },
    },
    "create_supplier": {
        "endpoint": "/supplier/{id}",
        "fields": "id,name,email,phoneNumber,organizationNumber",
        "checks": {
            "name": ("name", "eq_ci"),
            "email": ("email", "eq_ci"),
            "organizationNumber": ("organizationNumber", "eq"),
        },
    },
    "create_travel_expense": {
        "endpoint": "/travelExpense/{id}",
        "fields": "id,title,employee(id),travelDetails(departureDate,returnDate)",
        "checks": {
            "title": ("title", "eq_ci"),
            "employee": ("employee", "ref_id"),
        },
    },
}


def _compare(
    api_val: Any,
    param_val: Any,
    comparator: str,
) -> tuple[bool, str]:
    """Compare an API field value against the expected param value.

    Returns (passed, detail_message).
    """
    if comparator == "zero_outstanding":
        # Special: amountOutstanding should be 0 after payment
        outstanding = api_val or 0
        passed = abs(float(outstanding)) < 0.01
        return passed, f"outstanding={outstanding}"

    if param_val is None:
        return True, "skipped(no_param)"

    if comparator == "eq":
        passed = str(api_val).strip() == str(param_val).strip()
        return passed, f"api={api_val} expected={param_val}"

    if comparator == "eq_ci":
        passed = str(api_val or "").strip().lower() == str(param_val).strip().lower()
        return passed, f"api={api_val} expected={param_val}"

    if comparator == "ref_id":
        # param_val could be {"id": N} or N
        expected_id = None
        if isinstance(param_val, dict):
            expected_id = param_val.get("id")
        elif isinstance(param_val, (int, float)):
            expected_id = int(param_val)
        if expected_id is None:
            return True, "skipped(no_id_in_param)"
        actual_id = None
        if isinstance(api_val, dict):
            actual_id = api_val.get("id")
        elif isinstance(api_val, (int, float)):
            actual_id = int(api_val)
        passed = actual_id == expected_id
        return passed, f"api_id={actual_id} expected_id={expected_id}"

    if comparator == "numeric":
        try:
            a = float(api_val or 0)
            e = float(param_val)
            passed = abs(a) < 0.01 if e == 0 else abs(a - e) / abs(e) < 0.01
            return passed, f"api={a} expected={e}"
        except (TypeError, ValueError):
            return False, f"api={api_val} expected={param_val} (parse_error)"

    if comparator == "exists":
        passed = api_val is not None and api_val != ""
        return passed, f"api={api_val}"

    return True, "unknown_comparator"


def verify_entity(
    api_client: TripletexClient,
    task_type: str,
    entity_id: int | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """GET back the created entity and compare key fields against params.

    Returns a verification report dict with pass/fail per field.
    """
    config = VERIFY_CONFIG.get(task_type)
    if not config or not entity_id:
        return {"verified": False, "reason": "no_config_or_id"}

    endpoint = config["endpoint"].format(id=entity_id)
    fields = config["fields"]
    checks = config["checks"]

    try:
        resp = api_client.get(endpoint, fields=fields)
        entity = resp.get("value", {})
    except Exception as e:
        logger.warning("VERIFY GET failed for %s/%s: %s", task_type, entity_id, e)
        return {"verified": False, "reason": f"get_failed: {e}"}

    results: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    fixable: dict[str, Any] = {}

    for api_field, (param_key, comparator) in checks.items():
        api_val = entity.get(api_field)
        param_val = params.get(param_key) if param_key else None

        passed, detail = _compare(api_val, param_val, comparator)
        status = "PASS" if passed else "FAIL"
        results[api_field] = {"status": status, "detail": detail}

        if passed:
            logger.info(
                "VERIFY %s %s.%s: PASS (%s)",
                task_type,
                entity_id,
                api_field,
                detail,
            )
        else:
            logger.warning(
                "VERIFY %s %s.%s: FAIL (%s)",
                task_type,
                entity_id,
                api_field,
                detail,
            )
            failures.append(api_field)
            # Track fixable fields (simple value fields, not nested)
            if param_val is not None and comparator in ("eq", "eq_ci", "numeric"):
                fixable[api_field] = param_val

    # Attempt fix via PUT if there are fixable failures
    fixed_fields: list[str] = []
    if fixable and _is_putable(task_type):
        try:
            fix_data = dict(entity)
            for field, value in fixable.items():
                fix_data[field] = value
            put_endpoint = endpoint
            api_client.put(put_endpoint, data=fix_data)
            fixed_fields = list(fixable.keys())
            logger.info(
                "VERIFY FIX %s %s: PUT updated fields %s",
                task_type,
                entity_id,
                fixed_fields,
            )
        except Exception as e:
            logger.warning(
                "VERIFY FIX %s %s failed: %s",
                task_type,
                entity_id,
                e,
            )

    all_passed = len(failures) == 0
    logger.info(
        "VERIFY SUMMARY %s %s: %s (%d/%d passed, fixed=%s)",
        task_type,
        entity_id,
        "ALL_PASS" if all_passed else "HAS_FAILURES",
        len(checks) - len(failures),
        len(checks),
        fixed_fields or "none",
    )

    return {
        "verified": True,
        "all_passed": all_passed,
        "results": results,
        "failures": failures,
        "fixed": fixed_fields,
    }


def _is_putable(task_type: str) -> bool:
    """Check if this entity type supports PUT for corrections."""
    # These entity types have PUT endpoints matching their GET
    return task_type in (
        "create_customer",
        "create_employee",
        "create_product",
        "create_department",
        "create_project",
        "create_supplier",
    )

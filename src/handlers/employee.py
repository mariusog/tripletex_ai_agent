"""Employee handlers: create and update employees via Tripletex API."""

from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, ParamSpec, register_handler

logger = logging.getLogger(__name__)


@register_handler
class CreateEmployeeHandler(BaseHandler):
    """POST /employee with extracted fields. Optimal: 1 API call."""

    tier = 1
    description = "Create a new employee in Tripletex"
    disambiguation = (
        "CRITICAL: Extract EVERY field from attached PDF/offer letter. "
        "Each missing field loses points. You MUST find ALL of these: "
        "1) email (e-post, look for @), "
        "2) nationalIdentityNumber (personnummer/fødselsnummer/identitetsnummer, "
        "11 digits like DDMMYYXXXXX — derive dateOfBirth from first 6 digits), "
        "3) bankAccountNumber (kontonummer/bankkonto, 11 digits like XXXX.XX.XXXXX), "
        "4) dateOfBirth (fødselsdato — OR derive from personnummer DDMMYY), "
        "5) startDate (tiltredelse/oppstart/ansettelsesdato), "
        "6) annualSalary (årslønn/grunnlønn/fastlønn, number only), "
        "7) employmentPercentage (stillingsprosent/stillingsdel, e.g. 100), "
        "8) hoursPerDay (arbeidstid per dag — if not stated: 7.5 for 100%, "
        "6.0 for 80%, scale proportionally), "
        "9) department (avdeling/seksjon/enhet), "
        "10) jobCode (stillingskode, 4-digit STYRK/occupation code), "
        "11) phoneNumberMobile (mobilnummer/telefon). "
        "SCAN THE ENTIRE PDF — fields may be in tables, headers, footers, "
        "or fine print. Check BOTH pages if multi-page."
    )
    param_schema = {
        "firstName": ParamSpec(description="Employee first name"),
        "lastName": ParamSpec(description="Employee last name"),
        "email": ParamSpec(required=False, description="Email address"),
        "phoneNumberMobile": ParamSpec(required=False, description="Mobile phone"),
        "userType": ParamSpec(required=False, description="STANDARD or ADMINISTRATOR"),
        "dateOfBirth": ParamSpec(required=False, type="date", description="Birth date yyyy-MM-dd"),
        "nationalIdentityNumber": ParamSpec(required=False, description="Personnummer/SSN"),
        "bankAccountNumber": ParamSpec(required=False, description="Bank account number"),
        "startDate": ParamSpec(required=False, type="date", description="Employment start date"),
        "annualSalary": ParamSpec(required=False, type="number", description="Annual salary"),
        "employmentPercentage": ParamSpec(required=False, type="number", description="Stilling %"),
        "hoursPerDay": ParamSpec(
            required=False, type="number", description="Working hours per day"
        ),
        "department": ParamSpec(required=False, description="Department name or ref"),
        "jobCode": ParamSpec(required=False, description="Stillingskode/occupation code"),
    }

    def get_task_type(self) -> str:
        return "create_employee"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        today = dt_date.today().isoformat()

        # Determine userType: STANDARD needs email, NO_ACCESS doesn't
        has_email = bool(params.get("email"))
        user_type = params.get("userType", "STANDARD" if has_email else "NO_ACCESS")

        # Derive dateOfBirth from personnummer if not explicitly provided
        dob = self.validate_date(params.get("dateOfBirth"), "dateOfBirth")
        nin = params.get("nationalIdentityNumber", "")
        if not dob and nin and len(str(nin)) >= 6:
            digits = str(nin).replace(" ", "")
            dd, mm, yy = digits[:2], digits[2:4], digits[4:6]
            try:
                # Century: individual digits (pos 6-8) determine century
                year = int(yy)
                if len(digits) >= 9:
                    individ = int(digits[6:9])
                    if individ < 500:
                        century = 1900
                    elif individ < 750 and year >= 54:
                        century = 1800
                    else:
                        century = 2000 if year < 40 else 1900
                else:
                    century = 1900 if year > 25 else 2000
                dob = f"{century + year}-{mm}-{dd}"
                logger.info("Derived dateOfBirth %s from personnummer", dob)
            except (ValueError, IndexError):
                pass

        body: dict[str, Any] = {
            "firstName": params["firstName"],
            "lastName": params["lastName"],
            "userType": user_type,
            "dateOfBirth": dob or "1990-01-01",
        }

        for field in (
            "email",
            "phoneNumberMobile",
            "nationalIdentityNumber",
            "address",
        ):
            if params.get(field):
                body[field] = params[field]
        # Clean bank account number (strip dots/spaces)
        bank_acct = params.get("bankAccountNumber")
        if bank_acct:
            body["bankAccountNumber"] = str(bank_acct).replace(".", "").replace(" ", "")

        if "department" in params:
            dept = params["department"]
            if isinstance(dept, str):
                # Search for department by name
                resp = api_client.get(
                    "/department", params={"name": dept, "count": 5}, fields="id,name"
                )
                found = None
                for v in resp.get("values", []):
                    if v.get("name", "").strip().lower() == dept.strip().lower():
                        found = {"id": v["id"]}
                        break
                if not found:
                    # Create the department if it doesn't exist
                    try:
                        dept_result = api_client.post("/department", data={"name": dept})
                        found = {"id": dept_result.get("value", {}).get("id")}
                    except TripletexApiError:
                        pass
                body["department"] = found or self.ensure_ref(dept, "department")
            else:
                body["department"] = self.ensure_ref(dept, "department")
        else:
            from src.handlers.entity_resolver import ensure_department_exists

            dept_ref = ensure_department_exists(api_client)
            if dept_ref:
                body["department"] = dept_ref

        # Map Norwegian/localized employment types to API enum values
        emp_type = params.get("employmentType", "ORDINARY")
        emp_type_map = {
            "fast stilling": "ORDINARY",
            "permanent": "ORDINARY",
            "vikariat": "TEMPORARY",
            "temporary": "TEMPORARY",
            "midlertidig": "TEMPORARY",
        }
        emp_type = emp_type_map.get(str(emp_type).lower(), emp_type)
        if emp_type not in ("ORDINARY", "MARITIME", "FREELANCE", "TEMPORARY"):
            emp_type = "ORDINARY"

        pct = params.get("employmentPercentage") or params.get(
            "percentageOfFullTimeEquivalent", 100
        )

        # Employment record
        start_date = self.validate_date(params.get("startDate"), "startDate") or today
        emp_detail: dict[str, Any] = {
            "date": start_date,
            "employmentType": emp_type,
            "employmentForm": "PERMANENT" if emp_type == "ORDINARY" else "TEMPORARY",
            "workingHoursScheme": "NOT_SHIFT",
            "percentageOfFullTimeEquivalent": pct,
        }

        # Annual salary
        annual_salary = params.get("annualSalary") or params.get("salary")
        if annual_salary:
            emp_detail["annualSalary"] = float(annual_salary)

        # Occupation code (stillingskode) — needs ID reference
        job_code = params.get("jobCode") or params.get("occupationCode")
        if job_code:
            code_str = str(job_code).strip()
            occ_id = self._resolve_occupation_code(api_client, code_str)
            if occ_id:
                emp_detail["occupationCode"] = {"id": occ_id}

        # Working hours per day → shiftDurationHours on employmentDetails
        hours_per_day = params.get("hoursPerDay")
        if not hours_per_day:
            # Default based on employment percentage (7.5h for 100%)
            hours_per_day = round(7.5 * pct / 100, 1) if pct else 7.5
        emp_detail["shiftDurationHours"] = float(hours_per_day)
        emp_detail["remunerationType"] = "MONTHLY_WAGE"

        employment: dict[str, Any] = {
            "startDate": start_date,
            "employmentDetails": [emp_detail],
        }
        # Link to company division (required for payroll)
        try:
            div_resp = api_client.get_cached(
                "company_division",
                "/company/divisions",
                params={"count": 1},
                fields="id",
            )
            div_vals = div_resp.get("values", [])
            if div_vals:
                div_ref = {"id": div_vals[0]["id"]}
                employment["division"] = div_ref
                logger.info("Division set to id=%s", div_vals[0]["id"])
            else:
                logger.warning("No company divisions found")
        except TripletexApiError:
            pass

        body["employments"] = [employment]

        body = self.strip_none_values(body)

        try:
            result = api_client.post("/employee", data=body)
        except TripletexApiError as e:
            err_msgs = [m.get("message", "") for m in e.error.validation_messages]
            # If email already exists, find the employee and return
            if any("e-post" in m.lower() or "email" in m.lower() for m in err_msgs):
                email = body.get("email")
                if email:
                    resp = api_client.get(
                        "/employee", params={"email": email, "count": 1}, fields="id"
                    )
                    vals = resp.get("values", [])
                    if vals:
                        logger.info("Employee with email %s exists id=%s", email, vals[0]["id"])
                        return {"id": vals[0]["id"], "action": "already_exists"}
            raise

        value = result.get("value", {})
        logger.info("Created employee id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}

    @staticmethod
    def _resolve_occupation_code(api_client: TripletexClient, code_str: str) -> int | None:
        """Resolve occupation code to ID. Tries exact match, prefix, then broader search."""
        # Strategy 1: search by code
        try:
            resp = api_client.get(
                "/employee/employment/occupationCode",
                params={"code": code_str, "count": 20},
                fields="id,code",
            )
            best = None
            for occ in resp.get("values", []):
                occ_code = occ.get("code", "")
                if occ_code == code_str:
                    logger.info("Occupation code exact match: %s -> id=%s", code_str, occ["id"])
                    return occ["id"]
                if occ_code.startswith(code_str) and not best:
                    best = occ
            if best:
                logger.info("Occupation code prefix match: %s -> id=%s", code_str, best["id"])
                return best["id"]
        except TripletexApiError:
            pass
        # Strategy 2: search by nameNO (description)
        try:
            resp = api_client.get(
                "/employee/employment/occupationCode",
                params={"nameNO": code_str, "count": 5},
                fields="id,code,nameNO",
            )
            vals = resp.get("values", [])
            if vals:
                logger.info("Occupation code name match: %s -> id=%s", code_str, vals[0]["id"])
                return vals[0]["id"]
        except TripletexApiError:
            pass
        # Strategy 3: try without leading zeros or with padding
        stripped = code_str.lstrip("0")
        padded = code_str.zfill(4)
        for variant in (stripped, padded):
            if variant == code_str:
                continue
            try:
                resp = api_client.get(
                    "/employee/employment/occupationCode",
                    params={"code": variant, "count": 5},
                    fields="id,code",
                )
                vals = resp.get("values", [])
                if vals:
                    logger.info("Occupation code variant match: %s -> id=%s", variant, vals[0]["id"])
                    return vals[0]["id"]
            except TripletexApiError:
                pass
        logger.warning("Could not resolve occupation code: %s", code_str)
        return None


@register_handler
class UpdateEmployeeHandler(BaseHandler):
    """GET /employee (search) then PUT /employee/{id}. 2 API calls."""

    tier = 1
    description = "Update an existing employee"
    param_schema = {
        "firstName": ParamSpec(description="First name to find employee"),
        "lastName": ParamSpec(description="Last name to find employee"),
    }

    def get_task_type(self) -> str:
        return "update_employee"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        first = params["firstName"]
        last = params["lastName"]
        search = api_client.get(
            "/employee",
            params={"firstName": first, "lastName": last, "count": 1},
            fields="*",
        )
        values = search.get("values", [])
        if not values:
            logger.warning("Employee not found: %s %s", first, last)
            return {"error": "not_found"}

        employee = values[0]
        emp_id = employee["id"]

        for field in ("phoneNumberMobile", "firstName", "lastName"):
            if params.get(field):
                employee[field] = params[field]

        if "dateOfBirth" in params:
            date_val = self.validate_date(params["dateOfBirth"], "dateOfBirth")
            if date_val:
                employee["dateOfBirth"] = date_val
        if not employee.get("dateOfBirth"):
            employee["dateOfBirth"] = "1990-01-01"

        if "department" in params:
            employee["department"] = self.ensure_ref(params["department"], "department")

        result = api_client.put(f"/employee/{emp_id}", data=employee)
        logger.info("Updated employee id=%s", emp_id)
        return {"id": emp_id, "action": "updated", "value": result.get("value", {})}

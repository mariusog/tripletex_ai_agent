"""Central task router that connects LLM classification to handler execution.

Orchestrates the flow: parse request -> classify via LLM -> lookup handler(s) -> execute.
Supports multi-step task execution with shared context between steps.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.api_client import TripletexClient
from src.handlers import HANDLER_REGISTRY
from src.llm import LLMClient
from src.models import SolveRequest, SolveResponse, TaskClassification
from src.services.param_normalizer import normalize_params

logger = logging.getLogger(__name__)

_PLACEHOLDER_VALUES = {"<UNKNOWN>", "UNKNOWN", "unknown", "<unknown>", "TBD", "N/A", "n/a", ""}


def _strip_placeholders(params: dict) -> dict:
    """Remove params with placeholder values the LLM couldn't extract."""
    cleaned = {}
    for k, v in params.items():
        if isinstance(v, str) and v.strip() in _PLACEHOLDER_VALUES:
            continue
        if isinstance(v, dict):
            v = _strip_placeholders(v)
        cleaned[k] = v
    return cleaned


def _inject_context(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Inject shared context from previous steps into params.

    Fills in missing entity refs from context — never overwrites explicit values.
    """
    merged = dict(params)
    # Auto-inject any context key that's missing in params
    for key in (
        "customer",
        "supplier",
        "employee",
        "invoiceId",
        "orderId",
        "projectId",
        "voucherId",
        "travelExpenseId",
        "_overdue_invoice_id",
    ):
        if key not in merged and key in context:
            merged[key] = context[key]
    return merged


def _update_context(
    context: dict[str, Any],
    result: dict[str, Any],
    params: dict[str, Any],
    task_type: str = "",
) -> None:
    """Update shared context with results from a completed step."""
    if result.get("id"):
        context["lastId"] = result["id"]

    # Propagate entity references from params
    for key in ("customer", "supplier", "employee"):
        if key in params:
            context[key] = params[key]

    # Propagate IDs based on task type
    if result.get("id"):
        if "invoice" in task_type or task_type in ("send_invoice", "register_payment"):
            context["invoiceId"] = result["id"]
        if "voucher" in task_type:
            context["voucherId"] = result["id"]
        if "project" in task_type:
            context["projectId"] = result["id"]
        # When creating an entity, set the ref in context for later steps
        if task_type == "create_supplier":
            context["supplier"] = {"id": result["id"]}
        if task_type == "create_customer":
            context["customer"] = {"id": result["id"]}
        if task_type == "create_employee":
            context["employee"] = {"id": result["id"]}
    if result.get("orderId"):
        context["orderId"] = result["orderId"]
    if result.get("entryId"):
        context["entryId"] = result["entryId"]

    # Carry overdue invoice ID from voucher step (for late fee tasks)
    if params.get("_overdue_invoice_id"):
        context["_overdue_invoice_id"] = params["_overdue_invoice_id"]


class TaskRouter:
    """Routes classified tasks to the correct handler and executes them."""

    def __init__(
        self,
        llm_client: LLMClient,
        handler_registry: dict[str, Any] | None = None,
    ) -> None:
        self._llm = llm_client
        self._registry = handler_registry or HANDLER_REGISTRY

    async def solve(self, request: SolveRequest) -> SolveResponse:
        """Parse request, classify via LLM, execute handler(s), return response."""
        start = time.monotonic()
        api_client = TripletexClient(
            base_url=request.tripletex_credentials.base_url,
            session_token=request.tripletex_credentials.session_token,
        )
        # Run metadata collected for GCS export
        self._run_meta: dict[str, Any] = {}

        try:
            classifications = self._classify(request)
            # Validate and fix under-classified project lifecycle prompts
            classifications = self._validate_classifications(classifications, request)
            logger.info(
                "Classified %d task(s): %s",
                len(classifications),
                [c.task_type for c in classifications],
            )

            # Shared context carries entity refs between steps
            context: dict[str, Any] = {}
            step_results: list[dict[str, Any]] = []
            all_read_only = True

            for i, classification in enumerate(classifications):
                task_type = classification.task_type
                params = _strip_placeholders(classification.params)
                params = normalize_params(params)

                # Inject context from previous steps
                if i > 0:
                    params = _inject_context(params, context)

                logger.info(
                    "Step %d/%d: task_type=%s params=%s",
                    i + 1,
                    len(classifications),
                    task_type,
                    params,
                )

                handler = self._registry.get(task_type)
                if handler is None:
                    logger.warning("No handler for task_type=%s, skipping", task_type)
                    continue

                missing = handler.validate_params(params)
                if missing:
                    logger.warning(
                        "Missing params %s for task_type=%s, executing anyway",
                        missing,
                        task_type,
                    )

                # Handle batch "items" for handlers without native support
                try:
                    items = params.get("items", [])
                    if items and not hasattr(handler, "_create_one"):
                        results = []
                        for item in items:
                            merged = {**params, **item}
                            merged.pop("items", None)
                            results.append(handler.execute(api_client, merged))
                        result = {"results": results, "count": len(results)}
                    else:
                        result = handler.execute(api_client, params)

                    # Update context for next step
                    _update_context(context, result, params, task_type)
                    step_results.append(result)
                    if api_client.write_call_count > 0:
                        all_read_only = False

                    elapsed = time.monotonic() - start
                    logger.info(
                        "Handler result step=%d task_type=%s handler=%s "
                        "api_calls=%d writes=%d errors=%d duration=%.2fs result=%s",
                        i + 1,
                        task_type,
                        type(handler).__name__,
                        api_client.api_call_count,
                        api_client.write_call_count,
                        api_client.error_count,
                        elapsed,
                        result,
                    )
                except Exception:
                    elapsed = time.monotonic() - start
                    logger.exception(
                        "Step %d/%d failed (task_type=%s) after %.2fs, continuing",
                        i + 1,
                        len(classifications),
                        task_type,
                        elapsed,
                    )

            # If all steps were read-only, re-classify with the data
            if all_read_only and step_results:
                logger.info("All steps read-only, re-classifying with data")
                step_results = self._enrich_with_analysis(step_results)
                analysis = next(
                    (sr for sr in step_results if sr.get("action") == "expense_analysis"),
                    None,
                )
                # For expense analysis: create projects+activities directly
                if analysis and analysis.get("top_increases"):
                    self._execute_expense_analysis(api_client, analysis, start)
                else:
                    new_tasks = self._reclassify_with_data(request, step_results)
                    write_tasks = [t for t in new_tasks if t.task_type != "balance_sheet_report"]
                    if write_tasks:
                        logger.info(
                            "Re-classified %d action task(s): %s",
                            len(write_tasks),
                            [t.task_type for t in write_tasks],
                        )
                        for i, classification in enumerate(write_tasks):
                            task_type = classification.task_type
                            params = _strip_placeholders(classification.params)
                            params = normalize_params(params)
                            handler = self._registry.get(task_type)
                            if not handler:
                                continue
                            try:
                                result = handler.execute(api_client, params)
                                elapsed = time.monotonic() - start
                                logger.info(
                                    "Handler result step=R%d task_type=%s "
                                    "writes=%d errors=%d duration=%.2fs",
                                    i + 1,
                                    task_type,
                                    api_client.write_call_count,
                                    api_client.error_count,
                                    elapsed,
                                )
                            except Exception:
                                logger.exception("Re-classified step R%d failed", i + 1)

        except Exception:
            elapsed = time.monotonic() - start
            logger.exception("Router error after %.2fs", elapsed)
        finally:
            # Post-run verification (GETs are free)
            import contextlib

            with contextlib.suppress(UnboundLocalError):
                self._verify_run(api_client, context, step_results)

            # Collect run metadata for GCS export
            with contextlib.suppress(UnboundLocalError):
                task_types = [c.task_type for c in classifications]
                self._run_meta = {
                    "task_types": task_types,
                    "task_type": task_types[0] if len(task_types) == 1 else "multi",
                    "steps": len(task_types),
                    "api_calls": api_client.api_call_count,
                    "writes": api_client.write_call_count,
                    "errors": api_client.error_count,
                    "results": [
                        {k: v for k, v in r.items() if k in ("id", "action", "error")}
                        for r in step_results
                    ],
                }
            api_client.close()

        return SolveResponse(status="completed")

    @staticmethod
    def _verify_run(
        api_client: TripletexClient,
        context: dict[str, Any],
        step_results: list[dict[str, Any]],
    ) -> None:
        """Post-run verification via free GETs to see what competition sees."""
        try:
            # Verify ALL invoices on sandbox (GETs are free)
            try:
                all_inv = api_client.get(
                    "/invoice",
                    params={
                        "count": 20,
                        "invoiceDateFrom": "2020-01-01",
                        "invoiceDateTo": "2030-01-01",
                    },
                    fields="id,invoiceNumber,amount,amountOutstanding,"
                    "customer(id,name),invoiceDate,isCreditNote",
                )
                for inv in all_inv.get("values", []):
                    logger.info("VERIFY invoice: %s", inv)
            except Exception:
                logger.debug("Could not verify invoices")
            # Also verify overdue invoice if present
            overdue_id = context.get("_overdue_invoice_id")
            inv_id = context.get("invoiceId")
            if overdue_id and overdue_id != inv_id:
                ov = api_client.get(
                    f"/invoice/{overdue_id}",
                    fields="id,invoiceNumber,amount,amountOutstanding,"
                    "customer(id,name),invoiceDate",
                )
                logger.info("VERIFY overdue invoice: %s", ov.get("value", {}))

            # Verify created voucher
            v_id = context.get("voucherId")
            if v_id:
                v = api_client.get(
                    f"/ledger/voucher/{v_id}",
                    fields="id,number,date,voucherType(id,name),"
                    "postings(account(number),amountGross,supplier(id),"
                    "customer(id),department(id))",
                )
                logger.info("VERIFY voucher: %s", v.get("value", {}))

            # Verify created project
            p_id = context.get("projectId")
            if p_id:
                p = api_client.get(
                    f"/project/{p_id}",
                    fields="id,name,isInternal,isFixedPrice,fixedprice,"
                    "customer(id,name),projectManager(id,firstName,lastName)",
                )
                logger.info("VERIFY project: %s", p.get("value", {}))

            # Verify created employee
            e_id = (
                context.get("employee", {}).get("id")
                if isinstance(context.get("employee"), dict)
                else None
            )
            if e_id:
                e = api_client.get(
                    f"/employee/{e_id}",
                    fields="id,firstName,lastName,email,nationalIdentityNumber,department(id,name)",
                )
                logger.info("VERIFY employee: %s", e.get("value", {}))
                # Also check employment
                emp = api_client.get(
                    "/employee/employment",
                    params={"employeeId": e_id, "count": 1},
                    fields="id,division(id,name),employmentDetails("
                    "occupationCode(id,code),annualSalary,"
                    "percentageOfFullTimeEquivalent,shiftDurationHours,"
                    "remunerationType)",
                )
                logger.info("VERIFY employment: %s", emp.get("values", []))
        except Exception:
            logger.debug("Verification failed")

    def _classify(self, request: SolveRequest) -> list[TaskClassification]:
        """Classify via LLM with one retry on failure."""
        try:
            return self._llm.classify_and_extract(
                prompt=request.prompt,
                files=request.files or None,
            )
        except Exception:
            logger.exception("LLM classification failed, retrying with rephrased prompt")

        rephrased = (
            f"Identify the Tripletex accounting task(s) in this request "
            f"and extract parameters:\n\n{request.prompt}"
        )
        return self._llm.classify_and_extract(prompt=rephrased, files=request.files or None)

    @staticmethod
    def _enrich_with_analysis(
        step_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Pre-compute expense analysis when we have multiple balance sheets."""
        balance_sheets = [sr for sr in step_results if sr.get("action") == "report_retrieved"]
        if len(balance_sheets) < 2:
            return step_results
        # Compare expense/cost accounts (4000-9999) between periods
        period1 = {
            e["account"]["number"]: e
            for e in balance_sheets[0].get("entries", [])
            if e.get("account", {}).get("number", 0) >= 4000
        }
        period2 = {
            e["account"]["number"]: e
            for e in balance_sheets[1].get("entries", [])
            if e.get("account", {}).get("number", 0) >= 4000
        }
        increases = []
        for num, e2 in period2.items():
            e1 = period1.get(num, {})
            change1 = e1.get("balanceChange", 0)
            change2 = e2.get("balanceChange", 0)
            diff = change2 - change1
            if diff > 0:
                increases.append(
                    {
                        "account_number": num,
                        "account_name": e2["account"]["name"],
                        "period1_change": change1,
                        "period2_change": change2,
                        "increase": diff,
                    }
                )
        increases.sort(key=lambda x: x["increase"], reverse=True)
        if increases:
            analysis = {
                "action": "expense_analysis",
                "top_increases": increases[:5],
                "summary": "; ".join(
                    f"{i['account_name']}: +{i['increase']:.0f}" for i in increases[:5]
                ),
            }
            logger.info("Expense analysis: %s", analysis["summary"])
            return [*step_results, analysis]
        return step_results

    def _execute_expense_analysis(
        self,
        api_client: TripletexClient,
        analysis: dict[str, Any],
        start: float,
    ) -> None:
        """Create internal projects + activities for top expense increases."""
        top = analysis["top_increases"][:3]
        project_handler = self._registry.get("create_project")
        activity_handler = self._registry.get("create_activity")
        if not project_handler or not activity_handler:
            return
        for i, item in enumerate(top):
            name = item["account_name"]
            try:
                proj_result = project_handler.execute(
                    api_client,
                    {"name": name, "isInternal": True, "startDate": "2026-01-01"},
                )
                elapsed = time.monotonic() - start
                logger.info(
                    "Expense project R%d '%s' id=%s duration=%.2fs",
                    i + 1,
                    name,
                    proj_result.get("id"),
                    elapsed,
                )
                # Create activity and link to project
                act_result = activity_handler.execute(api_client, {"name": name})
                act_id = act_result.get("id")
                logger.info(
                    "Expense activity R%d '%s' id=%s",
                    i + 1,
                    name,
                    act_id,
                )
                proj_id = proj_result.get("id")
                if proj_id and act_id:
                    try:
                        api_client.post(
                            "/project/projectActivity",
                            data={
                                "project": {"id": proj_id},
                                "activity": {"id": act_id},
                            },
                        )
                    except Exception:
                        logger.warning("Could not link activity to project")
                # Verify what competition sees (GETs are free)
                if proj_id:
                    try:
                        pv = api_client.get(
                            f"/project/{proj_id}",
                            fields="id,name,isInternal,isClosed,"
                            "projectActivities(activity(id,name))",
                        )
                        logger.info("Project verify: %s", pv.get("value", {}))
                    except Exception:
                        logger.debug("Could not verify project")
            except Exception:
                logger.exception("Expense analysis step %d failed", i + 1)

    def _validate_classifications(
        self,
        classifications: list[TaskClassification],
        request: SolveRequest,
    ) -> list[TaskClassification]:
        """Detect under-classified prompts and force re-classification."""
        task_types = {c.task_type for c in classifications}
        prompt_lower = request.prompt.lower()

        # Detect project lifecycle: mentions project + hours + invoice
        lifecycle_keywords = [
            ("proyecto", "horas", "factura"),  # Spanish
            ("projet", "heures", "facture"),  # French
            ("prosjekt", "timer", "faktura"),  # Norwegian
            ("project", "hours", "invoice"),  # English
            ("projekt", "stunden", "rechnung"),  # German
            ("projeto", "horas", "fatura"),  # Portuguese
        ]
        is_lifecycle = any(all(kw in prompt_lower for kw in kws) for kws in lifecycle_keywords)
        has_workflow = task_types & {
            "create_project",
            "log_timesheet",
            "create_invoice",
        }

        if is_lifecycle and not has_workflow:
            logger.warning(
                "Project lifecycle detected but no workflow tasks classified. "
                "Re-classifying with explicit instructions."
            )
            augmented = (
                f"{request.prompt}\n\n"
                "CRITICAL INSTRUCTION: This is a PROJECT LIFECYCLE task. "
                "You MUST decompose it into these task types IN ORDER:\n"
                "1. create_project (with customer and budget)\n"
                "2. log_timesheet (one per employee, with hours)\n"
                "3. create_voucher (for supplier costs, debit 4300, credit 2400)\n"
                "4. create_invoice (include orderLines with the project name "
                "and the budget amount as price)\n"
                "Do NOT just create entities. Execute the FULL workflow."
            )
            try:
                new_cls = self._llm.classify_and_extract(
                    prompt=augmented, files=request.files or None
                )
                new_types = {c.task_type for c in new_cls}
                if new_types & {"create_project", "log_timesheet", "create_invoice"}:
                    logger.info("Re-classified to: %s", [c.task_type for c in new_cls])
                    return new_cls
            except Exception:
                logger.exception("Re-classification failed")

        return classifications

    def _reclassify_with_data(
        self,
        request: SolveRequest,
        step_results: list[dict[str, Any]],
    ) -> list[TaskClassification]:
        """Re-classify after read-only steps, passing API data to LLM for analysis."""
        # Check if we have pre-computed expense analysis
        analysis = next(
            (sr for sr in step_results if sr.get("action") == "expense_analysis"),
            None,
        )
        if analysis and analysis.get("top_increases"):
            top = analysis["top_increases"][:3]
            lines = []
            for item in top:
                lines.append(f"- {item['account_name']} (increase: {item['increase']:.0f} NOK)")
            augmented_prompt = (
                f"{request.prompt}\n\n"
                f"ANALYSIS RESULT — Top expense increases:\n"
                + "\n".join(lines)
                + "\n\nCRITICAL: You MUST create these tasks:\n"
                "For EACH account listed above:\n"
                "1. create_project with name=EXACT account name, isInternal=true\n"
                "2. create_activity with name=EXACT account name\n"
                f"That means {len(top)} create_project + {len(top)} create_activity tasks."
            )
        else:
            data_summary = []
            for sr in step_results:
                data_summary.append(str(sr)[:2000])
            augmented_prompt = (
                f"{request.prompt}\n\n"
                f"DATA FROM TRIPLETEX API:\n"
                + "\n---\n".join(data_summary)
                + "\n\nINSTRUCTIONS: Based on the data above, determine what "
                "actions to take. Create projects with isInternal=true and name "
                "them EXACTLY after the account name from the data. "
                "Create one activity per project."
            )
        try:
            return self._llm.classify_and_extract(
                prompt=augmented_prompt,
                files=request.files or None,
            )
        except Exception:
            logger.exception("Re-classification with data failed")
            return []


def create_router() -> TaskRouter:
    """Factory that creates a TaskRouter with default dependencies."""
    llm_client = LLMClient()
    return TaskRouter(llm_client=llm_client)

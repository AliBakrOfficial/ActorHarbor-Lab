from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .paths import ARTIFACTS_DIR


def create_run_record(scenario: dict, mode: str, project_id: str) -> dict:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    return {
        "id": f"{scenario['id']}-{run_id}",
        "scenario_id": scenario["id"],
        "scenario_name": scenario["name"],
        "project_id": project_id,
        "mode": mode,
        "status": "running",
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ended_at": "",
        "artifact_dir": "",
        "launch_mode": scenario.get("launch_mode", "browser"),
        "options": {},
        "steps": [],
        "summary": "",
    }


def ensure_artifact_dir(run_record: dict) -> Path:
    started = datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_dir = ARTIFACTS_DIR / started / run_record["scenario_id"]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    run_record["artifact_dir"] = str(artifact_dir)
    return artifact_dir


def finalize_run_record(run_record: dict) -> dict:
    run_record["ended_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    recovery_overview = _build_recovery_overview(run_record)
    run_record["recovery_overview"] = recovery_overview
    validation_invalid_reasons = _collect_validation_invalid_reasons(run_record)
    run_record["validation_invalid_reasons"] = validation_invalid_reasons
    if validation_invalid_reasons:
        run_record["status"] = "validation-invalid"
    elif recovery_overview["unrecovered_failure_count"] > 0:
        run_record["status"] = "failed"
    elif any(step["status"] == "manual" for step in run_record["steps"]):
        run_record["status"] = "manual-review"
    elif recovery_overview["recovered_failure_count"] > 0:
        run_record["status"] = "passed-with-recovery"
    else:
        run_record["status"] = "passed"
    run_record["step_counts"] = _build_step_counts(run_record)
    run_record["resolution_counts"] = _build_resolution_counts(run_record)
    if run_record["status"] == "passed-with-recovery":
        run_record["summary"] = (
            f"{run_record['scenario_name']} finished with passed-with-recovery after "
            f"{recovery_overview['recovered_failure_count']} recovered issue(s)."
        )
    elif run_record["status"] == "manual-review" and recovery_overview["recovery_occurred"]:
        run_record["summary"] = (
            f"{run_record['scenario_name']} finished with manual-review after "
            f"{recovery_overview['recovered_failure_count']} recovered issue(s)."
        )
    elif run_record["status"] == "failed":
        run_record["summary"] = (
            f"{run_record['scenario_name']} finished with failed after "
            f"{recovery_overview['unrecovered_failure_count']} unrecovered issue(s)."
        )
    elif run_record["status"] == "validation-invalid":
        reason_text = ", ".join(validation_invalid_reasons) if validation_invalid_reasons else "unknown validation blocker"
        run_record["summary"] = (
            f"{run_record['scenario_name']} finished with validation-invalid because auth/session contamination "
            f"prevented a clean authenticated runtime surface ({reason_text})."
        )
    else:
        run_record["summary"] = f"{run_record['scenario_name']} finished with {run_record['status']}."
    return run_record


def write_run_artifacts(run_record: dict, artifact_dir: Path) -> None:
    summary_file = artifact_dir / "summary.json"
    log_file = artifact_dir / "step-log.json"
    markdown_file = artifact_dir / "summary.md"
    evidence_file = artifact_dir / "evidence-index.json"

    summary_file.write_text(json.dumps(run_record, indent=2), encoding="utf-8")
    log_file.write_text(json.dumps(_build_step_log(run_record), indent=2), encoding="utf-8")
    evidence_file.write_text(json.dumps(_build_evidence_index(run_record), indent=2), encoding="utf-8")
    markdown_lines = [
        f"# {run_record['scenario_name']}",
        "",
        f"- Run ID: `{run_record['id']}`",
        f"- Mode: `{run_record['mode']}`",
        f"- Launch mode: `{run_record.get('launch_mode', 'browser')}`",
        f"- Status: `{run_record['status']}`",
        f"- Started: `{run_record['started_at']}`",
        f"- Ended: `{run_record['ended_at']}`",
        f"- Artifact folder: `{run_record.get('artifact_dir', '-')}`",
        "",
        "## Recovery Overview",
        f"- Recovery occurred: `{run_record.get('recovery_overview', {}).get('recovery_occurred', False)}`",
        f"- Recovered issues: `{run_record.get('recovery_overview', {}).get('recovered_failure_count', 0)}`",
        f"- Unrecovered issues: `{run_record.get('recovery_overview', {}).get('unrecovered_failure_count', 0)}`",
        "",
        "## Inspection Overview",
        f"- Keep-open requested: `{run_record.get('inspection_overview', {}).get('keep_windows_open_requested', False)}`",
        f"- Live preservation supported: `{run_record.get('inspection_overview', {}).get('live_preservation_supported', False)}`",
        f"- True live keep-open used: `{run_record.get('inspection_overview', {}).get('true_keep_open', False)}`",
        f"- Fallback reopen used: `{run_record.get('inspection_overview', {}).get('fallback_reopen_used', False)}`",
        "",
        "## Step Counts",
        f"- Passed: `{run_record.get('step_counts', {}).get('passed', 0)}`",
        f"- Failed: `{run_record.get('step_counts', {}).get('failed', 0)}`",
        f"- Manual review: `{run_record.get('step_counts', {}).get('manual', 0)}`",
        f"- Blocked: `{run_record.get('step_counts', {}).get('blocked', 0)}`",
        "",
        "## Resolution Counts",
        f"- Executed: `{run_record.get('resolution_counts', {}).get('executed', 0)}`",
        f"- Resolved by branch: `{run_record.get('resolution_counts', {}).get('resolved-by-auth-aware-branch', 0)}`",
        f"- Skipped already satisfied: `{run_record.get('resolution_counts', {}).get('skipped-because-already-satisfied', 0)}`",
        f"- Skipped already authenticated: `{run_record.get('resolution_counts', {}).get('skipped-because-already-authenticated', 0)}`",
        f"- Manual review: `{run_record.get('resolution_counts', {}).get('manual-review', 0)}`",
        f"- Failed: `{run_record.get('resolution_counts', {}).get('failed', 0)}`",
        "",
        "## Actor Sessions",
    ]
    for actor in run_record.get("actor_sessions", []):
        markdown_lines.extend([
            f"- **{actor['actor_name']}**",
            f"  startup: `{actor.get('startup_state', 'fresh-launch')}` | attempts: `{actor.get('startup_attempts', 1)}` | recovered startup: `{actor.get('startup_recovered', False)}`",
            f"  final url: `{actor.get('final_url', '-')}`",
            f"  steps: `{len(actor.get('steps', []))}` | reused: `{actor.get('reused', False)}` | kept open: `{actor.get('kept_open', False)}`",
            f"  inspection: `{actor.get('inspection_label', actor.get('inspection_state', '-'))}`",
            f"  auth: `{actor.get('auth_label', actor.get('auth_state', '-'))}`",
            f"  final screenshot: `{actor.get('final_screenshot', '-')}`",
        ])
        if actor.get("fallback_reason"):
            markdown_lines.append(f"  fallback reason: `{actor['fallback_reason']}`")
    markdown_lines.extend([
        "",
        "## Best Evidence",
    ])
    for item in run_record.get("best_evidence", []):
        markdown_lines.append(f"- `{item.get('type', 'evidence')}` {item.get('label', '-') } ({item.get('actor', '-')}) :: `{item.get('path', '-')}`")
    markdown_lines.extend([
        "",
        "## Manual Review Points",
    ])
    manual_steps = [step for step in run_record.get("steps", []) if step.get("status") == "manual"]
    if manual_steps:
        for step in manual_steps:
            markdown_lines.append(f"- {step['title']} ({step['actor']}) :: {step['message']}")
    else:
        markdown_lines.append("- None")
    markdown_lines.extend([
        "",
        "## Validation Invalid Reasons",
    ])
    validation_invalid_reasons = run_record.get("validation_invalid_reasons", [])
    if validation_invalid_reasons:
        for reason in validation_invalid_reasons:
            markdown_lines.append(f"- `{reason}`")
    else:
        markdown_lines.append("- None")
    markdown_lines.extend([
        "",
        "## Failure Notes",
    ])
    failure_steps = [step for step in run_record.get("steps", []) if step.get("status") in {"failed", "blocked"}]
    if failure_steps:
        for step in failure_steps:
            markdown_lines.append(f"- {step['title']} ({step['actor']}) :: {step['reason'] or step['message']}")
            if step.get("recovered"):
                markdown_lines.append(f"  recovered by: `{step.get('recovered_by_step_id', '-')}`")
    else:
        markdown_lines.append("- None")
    markdown_lines.extend([
        "",
        "## Steps",
    ])
    for step in run_record.get("steps", []):
        markdown_lines.append(
            f"- `{step['status']}` / `{step.get('resolution', '-')}` [{step.get('actor', '-')}] {step['title']} ({step.get('action', '-')}) :: {step['message']}"
        )
        if step.get("current_url"):
            markdown_lines.append(f"  url: `{step['current_url']}`")
        if step.get("reason"):
            markdown_lines.append(f"  reason: `{step['reason']}`")
        if step.get("failure_category"):
            markdown_lines.append(f"  failure category: `{step['failure_category']}`")
        if step.get("recovered"):
            markdown_lines.append(f"  recovered by: `{step.get('recovered_by_step_id', '-')}`")
            if step.get("recovery_note"):
                markdown_lines.append(f"  recovery note: `{step['recovery_note']}`")
        if step.get("screenshot"):
            markdown_lines.append(f"  screenshot: `{step['screenshot']}`")
        if step.get("artifact"):
            markdown_lines.append(f"  artifact: `{step['artifact']}`")
    markdown_file.write_text("\n".join(markdown_lines), encoding="utf-8")


def _build_step_counts(run_record: dict) -> dict:
    counts = {"passed": 0, "failed": 0, "manual": 0, "blocked": 0, "validation-invalid": 0}
    for step in run_record.get("steps", []):
        status = step.get("status")
        if status in counts:
            counts[status] += 1
    return counts


def _build_resolution_counts(run_record: dict) -> dict:
    counts = {
        "executed": 0,
        "resolved-by-auth-aware-branch": 0,
        "skipped-because-already-satisfied": 0,
        "skipped-because-already-authenticated": 0,
        "manual-review": 0,
        "failed": 0,
        "blocked": 0,
    }
    for step in run_record.get("steps", []):
        resolution = step.get("resolution")
        if resolution in counts:
            counts[resolution] += 1
    return counts


def _build_step_log(run_record: dict) -> list[dict]:
    entries: list[dict] = []
    for step in run_record.get("steps", []):
        entries.append(
            {
                "index": step.get("index", 0),
                "step_id": step.get("id", ""),
                "title": step.get("title", ""),
                "actor": step.get("actor", ""),
                "action": step.get("action", ""),
                "mode": step.get("mode", ""),
                "status": step.get("status", ""),
                "reason": step.get("reason", ""),
                "resolution": step.get("resolution", ""),
                "failure_category": step.get("failure_category", ""),
                "recovered": bool(step.get("recovered")),
                "recovered_by_step_id": step.get("recovered_by_step_id", ""),
                "recovery_note": step.get("recovery_note", ""),
                "message": step.get("message", ""),
                "current_url": step.get("current_url", ""),
                "screenshot": step.get("screenshot", ""),
                "artifact": step.get("artifact", ""),
                "observations": step.get("observations", {}),
                "evidence_type": step.get("evidence_type", ""),
                "best_evidence": bool(step.get("best_evidence")),
            }
        )
    return entries


def _build_evidence_index(run_record: dict) -> dict:
    return {
        "scenario_name": run_record.get("scenario_name", ""),
        "status": run_record.get("status", ""),
        "artifact_dir": run_record.get("artifact_dir", ""),
        "validation_invalid_reasons": run_record.get("validation_invalid_reasons", []),
        "recovery_overview": run_record.get("recovery_overview", {}),
        "best_evidence": run_record.get("best_evidence", []),
        "actor_sessions": [
            {
                "actor_name": actor.get("actor_name", ""),
                "startup_state": actor.get("startup_state", ""),
                "startup_attempts": actor.get("startup_attempts", 1),
                "startup_recovered": actor.get("startup_recovered", False),
                "final_url": actor.get("final_url", ""),
                "final_screenshot": actor.get("final_screenshot", ""),
                "kept_open": actor.get("kept_open", False),
                "inspection_state": actor.get("inspection_state", ""),
                "inspection_label": actor.get("inspection_label", ""),
                "auth_state": actor.get("auth_state", ""),
                "auth_label": actor.get("auth_label", ""),
                "inspectable": actor.get("inspectable", False),
                "fallback_reason": actor.get("fallback_reason", ""),
            }
            for actor in run_record.get("actor_sessions", [])
        ],
        "inspection_overview": run_record.get("inspection_overview", {}),
        "manual_review_points": [
            {
                "step_id": step.get("id", ""),
                "title": step.get("title", ""),
                "actor": step.get("actor", ""),
                "message": step.get("message", ""),
                "resolution": step.get("resolution", ""),
                "screenshot": step.get("screenshot", ""),
            }
            for step in run_record.get("steps", [])
            if step.get("status") == "manual"
        ],
        "failure_points": [
            {
                "step_id": step.get("id", ""),
                "title": step.get("title", ""),
                "actor": step.get("actor", ""),
                "reason": step.get("reason", ""),
                "resolution": step.get("resolution", ""),
                "failure_category": step.get("failure_category", ""),
                "recovered": bool(step.get("recovered")),
                "recovered_by_step_id": step.get("recovered_by_step_id", ""),
                "recovery_note": step.get("recovery_note", ""),
                "current_url": step.get("current_url", ""),
                "screenshot": step.get("screenshot", ""),
            }
            for step in run_record.get("steps", [])
            if step.get("status") in {"failed", "blocked"}
        ],
    }


def _build_recovery_overview(run_record: dict) -> dict:
    steps = run_record.get("steps", [])
    recovered_failures = []
    unrecovered_failures = []
    for step in steps:
        if step.get("status") not in {"failed", "blocked"}:
            continue
        recovered_by = _find_recovery_step(step, steps)
        if recovered_by:
            step["recovered"] = True
            step["recovered_by_step_id"] = recovered_by.get("id", "")
            step["recovery_note"] = (
                f"Later step {recovered_by.get('id', '')} reached a valid scenario state for {step.get('actor', 'actor')}."
            )
            recovered_failures.append(step)
        else:
            step["recovered"] = False
            step["recovered_by_step_id"] = ""
            step["recovery_note"] = ""
            unrecovered_failures.append(step)
    return {
        "recovery_occurred": bool(recovered_failures),
        "recovered_failure_count": len(recovered_failures),
        "unrecovered_failure_count": len(unrecovered_failures),
        "recovered_step_ids": [step.get("id", "") for step in recovered_failures],
        "unrecovered_step_ids": [step.get("id", "") for step in unrecovered_failures],
    }


def _collect_validation_invalid_reasons(run_record: dict) -> list[str]:
    has_failure = False
    reasons: list[str] = []
    for step in run_record.get("steps", []):
        if step.get("status") not in {"failed", "blocked"}:
            continue
        has_failure = True
        observations = step.get("observations", {})
        auth_surface = observations.get("auth_surface", "")
        current_url = step.get("current_url", "")
        reason = f"{step.get('reason', '')}\n{step.get('message', '')}".lower()
        if auth_surface == "staff-login" or "/#/staff/login" in current_url or "authentication did not stabilize" in reason:
            reasons.append("staff-auth-not-stabilized")
        if auth_surface in {"patient-session-expired", "patient-scan"} or "/#/patient/session-expired" in current_url:
            reasons.append("patient-session-collapsed")
        if "visibility_state was 'visible', expected 'hidden'" in reason:
            reasons.append("hidden-tab-evidence-unreliable")
        if "expected baseline" in reason or "baseline snapshot not found" in reason:
            reasons.append("stale-queue-contamination")
        if "waiting for locator" in reason and step.get("action") == "click" and observations.get("auth_surface") in {"staff-login", "patient-session-expired"}:
            reasons.append("selector-evidence-not-trustworthy")

    if has_failure:
        for actor in run_record.get("actor_sessions", []):
            final_url = actor.get("final_url", "")
            if "/#/staff/login" in final_url:
                reasons.append("staff-auth-not-stabilized")
            if "/#/patient/session-expired" in final_url:
                reasons.append("patient-session-collapsed")
    deduped: list[str] = []
    for reason in reasons:
        if reason not in deduped:
            deduped.append(reason)
    return deduped


def _find_recovery_step(failed_step: dict, steps: list[dict]) -> dict | None:
    failed_actor = failed_step.get("actor", "")
    failed_index = int(failed_step.get("index", 0))
    for step in steps:
        if step.get("actor", "") != failed_actor:
            continue
        if int(step.get("index", 0)) <= failed_index:
            continue
        if step.get("status") in {"passed", "manual"}:
            return step
    return None


def is_safe_artifact_dir(target: str | Path) -> bool:
    try:
        Path(target).resolve().relative_to(ARTIFACTS_DIR.resolve())
    except ValueError:
        return False
    return True


def delete_run_artifact_dir(target: str | Path) -> bool:
    artifact_dir = Path(target)
    if not artifact_dir.exists():
        return False
    if not is_safe_artifact_dir(artifact_dir):
        raise ValueError("Artifact deletion target is outside the lab artifact root.")
    for child in sorted(artifact_dir.iterdir(), reverse=True):
        if child.is_dir():
            delete_run_artifact_dir(child)
        else:
            child.unlink()
    artifact_dir.rmdir()
    return True


def prune_run_history(history: list[dict], run_ids: list[str], *, delete_artifacts: bool = False) -> tuple[list[dict], int]:
    removal_ids = set(run_ids)
    removed = 0
    kept_history: list[dict] = []
    for run in history:
        if run.get("id") not in removal_ids:
            kept_history.append(run)
            continue
        removed += 1
        if delete_artifacts and run.get("artifact_dir"):
            delete_run_artifact_dir(run["artifact_dir"])
    return kept_history, removed

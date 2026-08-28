import { useEffect, useState } from "react";

import {
    getAlertRules,
    upsertAlertRule,
    deleteAlertRule,
    evaluateAlerts,
} from "../api";

const SEVERITY_LABEL = {
    critical: "critical",
    warning: "warning",
    info: "info",
};

function Alerts({ onFiringChange }) {
    const [rules, setRules] = useState([]);
    const [evaluations, setEvaluations] = useState({});
    const [firingCount, setFiringCount] = useState(0);
    const [drafts, setDrafts] = useState({});
    const [saving, setSaving] = useState(null);
    const [error, setError] = useState(null);

    async function reload() {
        setError(null);
        try {
            const [ruleList, evalResult] = await Promise.all([
                getAlertRules(),
                evaluateAlerts(),
            ]);
            setRules(ruleList);
            const byId = {};
            for (const r of evalResult.rules) {
                byId[r.rule_id] = r;
            }
            setEvaluations(byId);
            setFiringCount(evalResult.firing_count);
        } catch (err) {
            setError(err.message);
        }
    }

    useEffect(() => {
        reload();
    }, []);

    useEffect(() => {
        if (onFiringChange) {
            onFiringChange(firingCount);
        }
    }, [firingCount, onFiringChange]);

    function draftFor(rule) {
        return (
            drafts[rule.rule_id] ?? {
                threshold: rule.threshold,
                window_minutes: rule.window_minutes,
            }
        );
    }

    function updateDraft(ruleId, field, value) {
        setDrafts((prev) => ({
            ...prev,
            [ruleId]: {
                ...draftFor({ rule_id: ruleId, ...prev[ruleId] }),
                [field]: value,
            },
        }));
    }

    async function handleSave(rule) {
        const draft = draftFor(rule);
        setSaving(rule.rule_id);
        setError(null);
        try {
            await upsertAlertRule({
                rule_id: rule.rule_id,
                name: rule.name,
                kind: rule.kind,
                threshold: Number(draft.threshold),
                window_minutes: Number(draft.window_minutes),
                severity: rule.severity,
                enabled: rule.enabled,
            });
            setDrafts((prev) => {
                const next = { ...prev };
                delete next[rule.rule_id];
                return next;
            });
            await reload();
        } catch (err) {
            setError(err.message);
        } finally {
            setSaving(null);
        }
    }

    async function handleToggle(rule) {
        setSaving(rule.rule_id);
        try {
            await upsertAlertRule({
                ...rule,
                threshold: Number(rule.threshold),
                enabled: !rule.enabled,
            });
            await reload();
        } catch (err) {
            setError(err.message);
        } finally {
            setSaving(null);
        }
    }

    async function handleDelete(ruleId) {
        setSaving(ruleId);
        try {
            await deleteAlertRule(ruleId);
            await reload();
        } catch (err) {
            setError(err.message);
        } finally {
            setSaving(null);
        }
    }

    const firingRules = rules.filter(
        (r) => evaluations[r.rule_id]?.state === "firing"
    );

    return (
        <section className="alerts-section">
            <div className="section-heading">
                <h3>
                    Failure Alerts{" "}
                    {firingCount > 0 && (
                        <span className="alerts-firing-badge">
                            {firingCount} firing
                        </span>
                    )}
                </h3>
                <button
                    type="button"
                    className="refresh-button alerts-refresh"
                    onClick={reload}
                >
                    Re-evaluate
                </button>
            </div>

            {error && (
                <div className="message error">
                    {error}
                </div>
            )}

            {firingRules.length > 0 && (
                <div className="alerts-firing-list">
                    {firingRules.map((rule) => {
                        const ev = evaluations[rule.rule_id];
                        return (
                            <div
                                key={rule.rule_id}
                                className={`alert-card alert-firing severity-${rule.severity}`}
                            >
                                <div className="alert-card-head">
                                    <span
                                        className={`alert-state alert-state-firing`}
                                    >
                                        firing
                                    </span>
                                    <strong>{rule.name}</strong>
                                    <span
                                        className={`alert-severity severity-${rule.severity}`}
                                    >
                                        {SEVERITY_LABEL[rule.severity] ??
                                            rule.severity}
                                    </span>
                                </div>
                                <p className="alert-message">
                                    {ev?.message}
                                </p>
                            </div>
                        );
                    })}
                </div>
            )}

            <div className="alerts-rules">
                {rules.length === 0 && (
                    <div className="message">
                        No alert rules configured.
                    </div>
                )}

                {rules.map((rule) => {
                    const ev = evaluations[rule.rule_id];
                    const firing = ev?.state === "firing";
                    const draft = draftFor(rule);
                    const dirty =
                        Number(draft.threshold) !==
                            Number(rule.threshold) ||
                        Number(draft.window_minutes) !==
                            Number(rule.window_minutes);

                    return (
                        <div
                            key={rule.rule_id}
                            className={`alert-rule-row ${
                                firing ? "is-firing" : ""
                            } ${rule.enabled ? "" : "is-disabled"}`}
                        >
                            <div className="alert-rule-main">
                                <div className="alert-rule-title">
                                    <span
                                        className={`alert-state ${
                                            firing
                                                ? "alert-state-firing"
                                                : "alert-state-ok"
                                        }`}
                                    >
                                        {firing ? "firing" : "ok"}
                                    </span>
                                    <strong>{rule.name}</strong>
                                    <span
                                        className={`alert-severity severity-${rule.severity}`}
                                    >
                                        {SEVERITY_LABEL[
                                            rule.severity
                                        ] ?? rule.severity}
                                    </span>
                                </div>
                                <p className="alert-message">
                                    {ev?.message ??
                                        "Rule disabled — not evaluated."}
                                </p>
                            </div>

                            <div className="alert-rule-controls">
                                <label className="alert-field">
                                    <span>threshold</span>
                                    <input
                                        type="number"
                                        min="0"
                                        step="any"
                                        value={draft.threshold}
                                        onChange={(e) =>
                                            updateDraft(
                                                rule.rule_id,
                                                "threshold",
                                                e.target.value
                                            )
                                        }
                                        disabled={!rule.enabled}
                                    />
                                </label>
                                <label className="alert-field">
                                    <span>window (m)</span>
                                    <input
                                        type="number"
                                        min="1"
                                        step="1"
                                        value={draft.window_minutes}
                                        onChange={(e) =>
                                            updateDraft(
                                                rule.rule_id,
                                                "window_minutes",
                                                e.target.value
                                            )
                                        }
                                        disabled={!rule.enabled}
                                    />
                                </label>

                                <button
                                    type="button"
                                    className="alert-save-button"
                                    disabled={!dirty || saving === rule.rule_id}
                                    onClick={() => handleSave(rule)}
                                >
                                    {saving === rule.rule_id
                                        ? "…"
                                        : "Save"}
                                </button>
                                <button
                                    type="button"
                                    className="alert-toggle-button"
                                    onClick={() => handleToggle(rule)}
                                    disabled={
                                        saving === rule.rule_id
                                    }
                                >
                                    {rule.enabled ? "Disable" : "Enable"}
                                </button>
                                <button
                                    type="button"
                                    className="alert-delete-button"
                                    onClick={() =>
                                        handleDelete(rule.rule_id)
                                    }
                                    disabled={
                                        saving === rule.rule_id
                                    }
                                    title="Delete rule"
                                >
                                    ✕
                                </button>
                            </div>
                        </div>
                    );
                })}
            </div>
        </section>
    );
}

export default Alerts;
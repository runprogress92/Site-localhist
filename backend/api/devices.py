"""Endpoints Connexions : montres Garmin, Polar, COROS."""
from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timedelta

from .. import db, settings
from ..providers import registry
from ..providers.base import NotConfigured, ProviderError
from ..server import ROUTER, Response, bad_request, not_found, redirect

HELP = {
    "garmin": {
        "title": "Garmin Connect Developer Program",
        "steps": [
            "Demander l'accès au programme partenaire sur developer.garmin.com "
            "(Health API et/ou Activity API).",
            "Une fois l'application créée, relever la Consumer Key et le Consumer Secret.",
            "Déclarer l'URL de rappel indiquée ci-dessous dans la console développeur.",
            "Coller les identifiants ici, puis lancer la connexion pour chaque athlète.",
        ],
        "note": "Garmin fonctionne en mode push : les nouvelles séances sont "
                "envoyées à l'URL de notification. En attendant l'accès partenaire, "
                "l'import de fichiers .fit exportés depuis Garmin Connect donne "
                "exactement les mêmes données.",
    },
    "polar": {
        "title": "Polar AccessLink",
        "steps": [
            "Créer un client sur admin.polaraccesslink.com (gratuit, immédiat).",
            "Renseigner l'URL de redirection OAuth indiquée ci-dessous.",
            "Coller le Client ID et le Client Secret ici.",
            "Chaque athlète autorise ensuite l'accès depuis sa fiche.",
        ],
        "note": "Polar utilise un modèle transactionnel : les séances ne sont "
                "marquées comme lues qu'après import réussi, aucune donnée ne "
                "peut être perdue en cas d'interruption.",
    },
    "coros": {
        "title": "COROS Open API",
        "steps": [
            "Déposer une demande sur open.coros.com (validation sous quelques jours).",
            "Renseigner l'URL de redirection et l'URL de webhook indiquées ci-dessous.",
            "Coller le Client ID et le Client Secret ici.",
        ],
        "note": "COROS fournit le fichier FIT complet de chaque séance : toutes "
                "les métriques sont donc recalculées localement avec vos seuils.",
    },
}


@ROUTER.get("/api/devices/providers")
def list_providers(request):
    """État des trois connecteurs et athlètes reliés."""
    providers = registry.describe_all()
    accounts = db.query(
        "SELECT pa.*, a.first_name, a.last_name, a.accent FROM provider_accounts pa"
        " JOIN athletes a ON a.id = pa.athlete_id ORDER BY a.last_name")
    by_provider: dict[str, list] = {}
    for account in accounts:
        account.pop("access_token", None)
        account.pop("refresh_token", None)
        account.pop("token_secret", None)
        by_provider.setdefault(account["provider"], []).append(account)
    base = settings.base_url()
    for provider in providers:
        provider["accounts"] = by_provider.get(provider["key"], [])
        provider["connected_count"] = sum(
            1 for a in provider["accounts"] if a["status"] == "connected")
        provider["help"] = HELP.get(provider["key"], {})
        provider["webhook_url"] = f"{base}/api/webhooks/{provider['key']}"
    return {"providers": providers, "base_url": base,
            "file_import": {
                "formats": [".fit", ".tcx", ".gpx"],
                "note": "Toutes les montres Garmin, Polar et COROS exportent des "
                        "fichiers .fit ou .tcx. Le décodeur intégré lit ces fichiers "
                        "en local, sans clé d'API et sans envoi de données à un tiers.",
            }}


@ROUTER.post("/api/devices/<provider_key>/config")
def save_config(request):
    """Enregistre les identifiants d'application d'un connecteur."""
    key = request.params["provider_key"]
    if key not in registry.PROVIDER_CLASSES:
        raise not_found(f"Connecteur inconnu : {key}")
    payload = request.json
    saved = settings.save_provider_config(key, payload)
    return {"provider": key, "configured": bool(saved.get("client_id")),
            "redirect_uri": saved.get("redirect_uri")}


@ROUTER.get("/api/devices/<provider_key>/authorize")
def authorize(request):
    """Démarre le flux d'autorisation et redirige vers la marque."""
    key = request.params["provider_key"]
    athlete_id = request.q_int("athlete_id")
    if not athlete_id:
        raise bad_request("Paramètre athlete_id obligatoire.")
    if not db.query_one("SELECT id FROM athletes WHERE id = ?", (athlete_id,)):
        raise not_found("Athlète introuvable.")
    try:
        provider = registry.get(key)
    except KeyError:
        raise not_found(f"Connecteur inconnu : {key}")
    state = secrets.token_urlsafe(24)
    try:
        url = provider.authorize_url(athlete_id, state)
    except NotConfigured as exc:
        raise bad_request(str(exc))
    except ProviderError as exc:
        raise bad_request(f"{provider.label} : {exc}")
    provider.save_account(athlete_id, status="pending")
    if request.q_bool("json"):
        return {"authorize_url": url, "state": state}
    return redirect(url)


@ROUTER.get("/api/devices/<provider_key>/callback")
def callback(request):
    """Reçoit le retour d'autorisation et enregistre le jeton."""
    key = request.params["provider_key"]
    provider = registry.get(key)
    params = {k: v[0] for k, v in request.query.items()}
    state = params.get("state")
    stored = db.query_one("SELECT * FROM oauth_states WHERE state = ?", (state,)) \
        if state else None
    if not stored:
        # Garmin ne renvoie pas toujours le state : on retombe sur le jeton de requête
        stored = db.query_one(
            "SELECT * FROM oauth_states WHERE request_token = ? ORDER BY created_at DESC",
            (params.get("oauth_token"),)) if params.get("oauth_token") else None
    if not stored:
        return _callback_page(False, key, "État d'autorisation introuvable ou expiré. "
                                          "Relancez la connexion depuis l'application.")
    try:
        provider.handle_callback(stored["athlete_id"], params, stored)
    except Exception as exc:
        provider.save_account(stored["athlete_id"], status="error", last_error=str(exc))
        return _callback_page(False, key, str(exc))
    finally:
        db.execute("DELETE FROM oauth_states WHERE state = ?", (stored["state"],))
    return _callback_page(True, key, "")


def _callback_page(ok: bool, provider: str, message: str) -> Response:
    """Petite page de retour, qui referme la fenêtre d'autorisation."""
    title = "Connexion réussie" if ok else "Connexion impossible"
    color = "#3fb98c" if ok else "#d8543f"
    body = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>{title}</title><style>
body{{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:#0f1319;
color:#e8ecf2;display:grid;place-items:center;height:100vh;margin:0}}
.card{{background:#171d26;border:1px solid #232c39;border-radius:14px;padding:40px;
max-width:460px;text-align:center}}h1{{color:{color};font-size:19px;margin:0 0 12px}}
p{{color:#94a3b5;line-height:1.6;font-size:14px}}
a{{color:#4f8ff7;text-decoration:none}}</style></head><body><div class="card">
<h1>{title} — {provider.upper()}</h1>
<p>{message or 'Le compte est relié. Vous pouvez fermer cette fenêtre et lancer une synchronisation.'}</p>
<p><a href="/#/connexions">Retour à Athlytics</a></p></div>
<script>setTimeout(function(){{ if(window.opener) window.close(); }}, {2500 if ok else 9000});</script>
</body></html>"""
    return Response(body.encode("utf-8"), "text/html; charset=utf-8")


@ROUTER.post("/api/devices/<provider_key>/sync")
def sync(request):
    """Lance une synchronisation pour un athlète, ou pour tous."""
    key = request.params["provider_key"]
    try:
        provider = registry.get(key)
    except KeyError:
        raise not_found(f"Connecteur inconnu : {key}")
    days = request.q_int("days", 30)
    athlete_id = request.q_int("athlete_id") or request.json.get("athlete_id")
    if athlete_id:
        targets = [athlete_id]
    else:
        targets = [r["athlete_id"] for r in db.query(
            "SELECT athlete_id FROM provider_accounts WHERE provider = ?"
            " AND status = 'connected'", (key,))]
    if not targets:
        raise bad_request(f"Aucun athlète connecté à {provider.label}.")
    results = {}
    for target in targets:
        try:
            results[target] = provider.sync(target, days)
        except Exception as exc:
            results[target] = {"status": "error", "message": str(exc)}
    return {"provider": key, "results": results}


@ROUTER.delete("/api/devices/<provider_key>/accounts/<int:athlete_id>")
def disconnect(request):
    key = request.params["provider_key"]
    provider = registry.get(key)
    provider.disconnect(request.params["athlete_id"])
    return {"disconnected": key, "athlete_id": request.params["athlete_id"]}


@ROUTER.get("/api/devices/sync-log")
def sync_log(request):
    rows = db.query(
        "SELECT s.*, a.first_name, a.last_name FROM sync_log s"
        " LEFT JOIN athletes a ON a.id = s.athlete_id"
        " ORDER BY s.started_at DESC LIMIT ?", (request.q_int("limit", 50),))
    for row in rows:
        if row.get("detail"):
            try:
                row["detail"] = json.loads(row["detail"])
            except json.JSONDecodeError:
                pass
    return {"log": rows}


@ROUTER.get("/api/devices/hardware")
def hardware(request):
    """Montres et capteurs identifiés dans les fichiers importés."""
    rows = db.query(
        "SELECT device_name, provider, COUNT(*) AS sessions,"
        " MAX(start_time) AS last_seen, MIN(start_time) AS first_seen,"
        " athlete_id FROM activities WHERE device_name IS NOT NULL"
        " GROUP BY athlete_id, device_name ORDER BY last_seen DESC")
    athletes = {a["id"]: a for a in db.query(
        "SELECT id, first_name, last_name, accent FROM athletes")}
    for row in rows:
        row["athlete"] = athletes.get(row["athlete_id"])
    return {"devices": rows}


# ------------------------------------------------------------------ webhooks
@ROUTER.post("/api/webhooks/<provider_key>")
def webhook(request):
    """Point d'entrée des notifications push des marques."""
    key = request.params["provider_key"]
    try:
        provider = registry.get(key)
    except KeyError:
        raise not_found(f"Connecteur inconnu : {key}")
    try:
        payload = request.json
    except Exception:
        payload = {}
    db.insert("sync_log", {
        "provider": key, "started_at": db.now_iso(), "finished_at": db.now_iso(),
        "status": "ok", "message": "notification push reçue",
        "detail": json.dumps(payload, ensure_ascii=False)[:4000]})
    handler = getattr(provider, "handle_push", None)
    if handler is None:
        return {"received": True, "handled": 0,
                "note": f"{provider.label} ne déclare pas de traitement push."}
    try:
        result = handler(payload)
    except Exception as exc:
        return {"received": True, "error": str(exc)}, 200
    return {"received": True, **(result or {})}


@ROUTER.get("/api/webhooks/<provider_key>")
def webhook_verify(request):
    """Certaines marques valident l'URL par un GET (écho du challenge)."""
    challenge = request.q("challenge") or request.q("hub.challenge")
    if challenge:
        return Response(challenge.encode(), "text/plain")
    return {"status": "ready", "provider": request.params["provider_key"]}

"""
Integrations API

GET  /integrations/            → list all integrations with their status for current user
POST /integrations/connect/{provider}  → initiate OAuth or API-key connect
DELETE /integrations/{provider}        → disconnect integration
GET  /integrations/catalog             → full catalog (all providers + status labels)
POST /integrations/{provider}/sync     → trigger manual sync
"""
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.models import Integration, OAuthState, User
from app.api.auth.deps import get_current_user

router = APIRouter(prefix="/integrations", tags=["Integrations"])


# ── Integration catalog definition ───────────────────────────────────────────
# status: "available" | "coming_soon" | "beta" | "unsupported"
# auth_type: "oauth" | "api_key" | "webhook"

CATALOG = [
    # ── Source Control ──
    {
        "provider": "github",
        "name": "GitHub",
        "category": "Source Control",
        "description": "Track commits, PRs, branches and repository activity.",
        "icon": "🐙",
        "status": "available",
        "auth_type": "oauth",
        "features": ["commits", "pull_requests", "branches", "releases"],
        "oauth_url": "/auth/login/github",
    },
    {
        "provider": "gitlab",
        "name": "GitLab",
        "category": "Source Control",
        "description": "Connect GitLab repositories and pipelines.",
        "icon": "🦊",
        "status": "coming_soon",
        "auth_type": "oauth",
        "features": ["commits", "merge_requests", "pipelines"],
    },
    {
        "provider": "bitbucket",
        "name": "Bitbucket",
        "category": "Source Control",
        "description": "Bitbucket repository and pipeline integration.",
        "icon": "🪣",
        "status": "coming_soon",
        "auth_type": "oauth",
        "features": ["commits", "pull_requests"],
    },

    # ── Deployment ──
    {
        "provider": "vercel",
        "name": "Vercel",
        "category": "Deployment",
        "description": "Track deployments, preview URLs and build logs.",
        "icon": "▲",
        "status": "beta",
        "auth_type": "api_key",
        "features": ["deployments", "build_logs", "domains"],
    },
    {
        "provider": "render",
        "name": "Render",
        "category": "Deployment",
        "description": "Monitor Render services and deployment status.",
        "icon": "🟣",
        "status": "beta",
        "auth_type": "api_key",
        "features": ["deployments", "services"],
    },
    {
        "provider": "netlify",
        "name": "Netlify",
        "category": "Deployment",
        "description": "Track Netlify builds and deploy previews.",
        "icon": "🟩",
        "status": "coming_soon",
        "auth_type": "oauth",
        "features": ["deployments", "build_logs"],
    },
    {
        "provider": "railway",
        "name": "Railway",
        "category": "Deployment",
        "description": "Railway deployment and service monitoring.",
        "icon": "🚂",
        "status": "coming_soon",
        "auth_type": "api_key",
        "features": ["deployments", "services"],
    },

    # ── CI/CD ──
    {
        "provider": "github_actions",
        "name": "GitHub Actions",
        "category": "CI/CD",
        "description": "Monitor workflow runs and build status.",
        "icon": "⚙️",
        "status": "beta",
        "auth_type": "oauth",
        "features": ["workflow_runs", "build_status"],
        "requires": "github",
    },
    {
        "provider": "circleci",
        "name": "CircleCI",
        "category": "CI/CD",
        "description": "CircleCI pipeline and build analytics.",
        "icon": "⭕",
        "status": "coming_soon",
        "auth_type": "api_key",
        "features": ["pipelines", "builds"],
    },
    {
        "provider": "jenkins",
        "name": "Jenkins",
        "category": "CI/CD",
        "description": "Jenkins build and pipeline integration.",
        "icon": "🏗️",
        "status": "coming_soon",
        "auth_type": "api_key",
        "features": ["builds", "jobs"],
    },

    # ── Productivity ──
    {
        "provider": "linear",
        "name": "Linear",
        "category": "Productivity",
        "description": "Correlate Linear issues with commits and deployments.",
        "icon": "⚡",
        "status": "coming_soon",
        "auth_type": "oauth",
        "features": ["issues", "projects", "cycles"],
    },
    {
        "provider": "notion",
        "name": "Notion",
        "category": "Productivity",
        "description": "Sync execution reports to Notion databases.",
        "icon": "📝",
        "status": "coming_soon",
        "auth_type": "oauth",
        "features": ["pages", "databases"],
    },
    {
        "provider": "jira",
        "name": "Jira",
        "category": "Productivity",
        "description": "Link Jira tickets to your execution data.",
        "icon": "🎯",
        "status": "coming_soon",
        "auth_type": "oauth",
        "features": ["issues", "sprints", "boards"],
    },

    # ── Communication ──
    {
        "provider": "slack",
        "name": "Slack",
        "category": "Communication",
        "description": "Receive daily audit reports and alerts in Slack.",
        "icon": "💬",
        "status": "coming_soon",
        "auth_type": "oauth",
        "features": ["notifications", "reports"],
    },
    {
        "provider": "discord",
        "name": "Discord",
        "category": "Communication",
        "description": "Post execution summaries to Discord channels.",
        "icon": "🎮",
        "status": "coming_soon",
        "auth_type": "webhook",
        "features": ["notifications"],
    },

    # ── Coding Telemetry ──
    {
        "provider": "wakatime",
        "name": "WakaTime",
        "category": "Coding Telemetry",
        "description": "Real coding time analytics per project and language.",
        "icon": "⏱️",
        "status": "beta",
        "auth_type": "api_key",
        "features": ["coding_time", "languages", "projects"],
    },

    # ── AI ──
    {
        "provider": "openai",
        "name": "OpenAI",
        "category": "AI",
        "description": "Route OpenAI calls through TraceOps proxy for logging.",
        "icon": "🤖",
        "status": "available",
        "auth_type": "api_key",
        "features": ["proxy_logging", "usage_tracking"],
        "connect_url": "/app/proxy",
    },
    {
        "provider": "anthropic",
        "name": "Anthropic",
        "category": "AI",
        "description": "Route Claude calls through TraceOps proxy for logging.",
        "icon": "🧠",
        "status": "available",
        "auth_type": "api_key",
        "features": ["proxy_logging", "usage_tracking"],
        "connect_url": "/app/proxy",
    },

    # ── Analytics ──
    {
        "provider": "posthog",
        "name": "PostHog",
        "category": "Analytics",
        "description": "Product analytics and session recording.",
        "icon": "🦔",
        "status": "coming_soon",
        "auth_type": "api_key",
        "features": ["events", "sessions"],
    },
    {
        "provider": "sentry",
        "name": "Sentry",
        "category": "Analytics",
        "description": "Error tracking and performance monitoring.",
        "icon": "🔴",
        "status": "coming_soon",
        "auth_type": "api_key",
        "features": ["errors", "performance"],
    },
]

CATALOG_BY_PROVIDER = {c["provider"]: c for c in CATALOG}


# ── Schemas ───────────────────────────────────────────────────────────────────

class ApiKeyConnectRequest(BaseModel):
    api_key: str
    extra: Optional[dict] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _enrich_with_user_status(catalog_item: dict, user_integrations: dict) -> dict:
    item     = dict(catalog_item)
    provider = item["provider"]
    if provider in user_integrations:
        integ = user_integrations[provider]
        item["connected"]   = True
        item["user_status"] = integ.status
        item["connected_at"]= integ.connected_at.isoformat() if integ.connected_at else None
        item["username"]    = integ.provider_username
    else:
        item["connected"]   = False
        item["user_status"] = None
        item["connected_at"]= None
        item["username"]    = None
    return item


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/catalog")
async def get_catalog(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full catalog grouped by category, enriched with user connection status."""
    result = await db.execute(
        select(Integration).where(Integration.user_id == current_user.id)
    )
    user_integrations = {i.provider: i for i in result.scalars().all()}

    # Group by category
    categories: dict[str, list] = {}
    for item in CATALOG:
        cat = item["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(_enrich_with_user_status(item, user_integrations))

    return {
        "categories": [
            {"name": cat, "integrations": items}
            for cat, items in categories.items()
        ],
        "total": len(CATALOG),
        "connected": len(user_integrations),
    }


@router.get("/")
async def list_user_integrations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List only this user's connected integrations."""
    result = await db.execute(
        select(Integration).where(Integration.user_id == current_user.id)
    )
    integrations = result.scalars().all()
    enriched = []
    for integ in integrations:
        catalog_info = CATALOG_BY_PROVIDER.get(integ.provider, {})
        enriched.append({
            "id":               integ.id,
            "provider":         integ.provider,
            "name":             catalog_info.get("name", integ.provider),
            "icon":             catalog_info.get("icon", "🔌"),
            "category":         catalog_info.get("category", "Other"),
            "status":           integ.status,
            "provider_username": integ.provider_username,
            "connected_at":     integ.connected_at.isoformat() if integ.connected_at else None,
            "last_synced_at":   integ.last_synced_at.isoformat() if integ.last_synced_at else None,
            "features":         catalog_info.get("features", []),
        })
    return {"integrations": enriched, "count": len(enriched)}


@router.post("/connect/api_key/{provider}")
async def connect_api_key(
    provider: str,
    req: ApiKeyConnectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Connect an integration using an API key (for Vercel, Render, WakaTime etc)."""
    catalog_item = CATALOG_BY_PROVIDER.get(provider)
    if not catalog_item:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    if catalog_item["auth_type"] != "api_key":
        raise HTTPException(status_code=400, detail=f"{provider} uses OAuth, not API key.")
    if catalog_item["status"] not in ("available", "beta"):
        raise HTTPException(status_code=400, detail=f"{provider} is {catalog_item['status']}. Not yet supported.")

    # Validate the API key depending on provider
    username = None
    if provider == "vercel":
        username = await _validate_vercel_key(req.api_key)
    elif provider == "render":
        username = await _validate_render_key(req.api_key)
    elif provider == "wakatime":
        username = await _validate_wakatime_key(req.api_key)

    # Upsert integration
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == current_user.id,
            Integration.provider == provider,
        )
    )
    integ = result.scalar_one_or_none()
    if integ:
        integ.access_token       = req.api_key   # TODO: encrypt in production
        integ.status             = "connected"
        integ.provider_username  = username
        integ.connected_at       = datetime.now(timezone.utc)
    else:
        integ = Integration(
            user_id=current_user.id,
            provider=provider,
            access_token=req.api_key,
            status="connected",
            provider_username=username,
            metadata_=req.extra,
        )
        db.add(integ)
    await db.commit()
    return {"success": True, "provider": provider, "username": username}


@router.delete("/{provider}")
async def disconnect_integration(
    provider: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect and delete an integration."""
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == current_user.id,
            Integration.provider == provider,
        )
    )
    integ = result.scalar_one_or_none()
    if not integ:
        raise HTTPException(status_code=404, detail=f"Integration {provider} not found.")
    await db.delete(integ)
    await db.commit()
    return {"success": True, "provider": provider, "disconnected": True}


@router.post("/{provider}/sync")
async def sync_integration(
    provider: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger manual sync for a connected integration."""
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == current_user.id,
            Integration.provider == provider,
        )
    )
    integ = result.scalar_one_or_none()
    if not integ:
        raise HTTPException(status_code=404, detail=f"Integration {provider} not connected.")

    sync_result = {"provider": provider, "synced": False, "message": ""}

    if provider == "github":
        sync_result = await _sync_github(integ, current_user.id, db)
    else:
        sync_result["message"] = f"Sync for {provider} is not yet implemented."

    integ.last_synced_at = datetime.now(timezone.utc)
    await db.commit()
    return sync_result


# ── Provider validators ───────────────────────────────────────────────────────

async def _validate_vercel_key(api_key: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                "https://api.vercel.com/v2/user",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if r.status_code == 200:
                return r.json().get("user", {}).get("username")
            raise HTTPException(status_code=400, detail="Invalid Vercel API key.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Could not validate Vercel API key.")


async def _validate_render_key(api_key: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                "https://api.render.com/v1/owners?limit=1",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if r.status_code == 200:
                data = r.json()
                if data:
                    return data[0].get("owner", {}).get("name")
            raise HTTPException(status_code=400, detail="Invalid Render API key.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Could not validate Render API key.")


async def _validate_wakatime_key(api_key: str) -> Optional[str]:
    import base64
    try:
        encoded = base64.b64encode(api_key.encode()).decode()
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                "https://wakatime.com/api/v1/users/current",
                headers={"Authorization": f"Basic {encoded}"},
            )
            if r.status_code == 200:
                return r.json().get("data", {}).get("username")
            raise HTTPException(status_code=400, detail="Invalid WakaTime API key.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Could not validate WakaTime API key.")


async def _sync_github(integ: Integration, user_id: str, db: AsyncSession) -> dict:
    """Pull recent commits from all user's GitHub repos and store as events."""
    from app.models.models import Event
    from app.services.normalizer import normalize_github_commit

    token = integ.access_token
    if not token:
        return {"synced": False, "message": "No GitHub token found."}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Get user's repos
            repos_r = await client.get(
                "https://api.github.com/user/repos?per_page=20&sort=pushed&type=owner",
                headers={"Authorization": f"Bearer {token}"},
            )
            if repos_r.status_code != 200:
                return {"synced": False, "message": "GitHub API error."}

            repos = repos_r.json()
            total_commits = 0

            for repo in repos[:5]:  # limit to 5 repos on free tier
                commits_r = await client.get(
                    f"https://api.github.com/repos/{repo['full_name']}/commits?per_page=10",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if commits_r.status_code != 200:
                    continue
                commits = commits_r.json()
                pseudo = {
                    "commits": [
                        {
                            "id": c["sha"],
                            "message": c["commit"]["message"],
                            "timestamp": c["commit"]["author"]["date"],
                            "author": {"name": c["commit"]["author"]["name"]},
                            "url": c["html_url"],
                            "added": [], "modified": [], "removed": [],
                        }
                        for c in commits
                    ]
                }
                normalized = normalize_github_commit(pseudo)
                for ne in normalized:
                    event = Event(
                        user_id=user_id,
                        task_id=ne.get("task_id"),
                        event_type="commit",
                        source=f"github:sync:{repo['full_name']}",
                        raw_data=ne,
                        metadata_=ne.get("metadata"),
                    )
                    db.add(event)
                    total_commits += 1

        return {"synced": True, "commits_imported": total_commits, "repos_scanned": min(len(repos), 5)}
    except Exception as e:
        return {"synced": False, "message": str(e)[:200]}

"""Usage tracking API endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import List
from datetime import datetime, timedelta

from app.database import get_db
from app.models import Tunnel, Usage, Node


router = APIRouter()


class UsagePush(BaseModel):
    tunnel_id: str
    node_id: str
    bytes_used: int


class UsageResponse(BaseModel):
    tunnel_id: str
    bytes_used: int
    timestamp: str


@router.post("/push")
async def push_usage(usage_data: UsagePush, db: AsyncSession = Depends(get_db)):
    """Node pushes usage data"""
    result = await db.execute(select(Tunnel).where(Tunnel.id == usage_data.tunnel_id))
    tunnel = result.scalar_one_or_none()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    
    tunnel.used_mb += usage_data.bytes_used / (1024 * 1024)
    
    if tunnel.quota_mb > 0 and tunnel.used_mb >= tunnel.quota_mb:
        tunnel.status = "error"
    
    usage = Usage(
        tunnel_id=usage_data.tunnel_id,
        node_id=usage_data.node_id,
        bytes_used=usage_data.bytes_used
    )
    db.add(usage)
    await db.commit()
    
    return {"status": "ok"}


@router.get("/tunnel/{tunnel_id}")
async def get_tunnel_usage(tunnel_id: str, db: AsyncSession = Depends(get_db)):
    """Get usage for a tunnel"""
    result = await db.execute(select(Tunnel).where(Tunnel.id == tunnel_id))
    tunnel = result.scalar_one_or_none()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    
    return {
        "tunnel_id": tunnel_id,
        "used_mb": tunnel.used_mb,
        "quota_mb": tunnel.quota_mb,
        "remaining_mb": max(0, tunnel.quota_mb - tunnel.used_mb) if tunnel.quota_mb > 0 else None
    }


@router.get("/tunnel/{tunnel_id}/stats")
async def get_tunnel_traffic_stats(
    tunnel_id: str,
    hours: int = 24,
    db: AsyncSession = Depends(get_db)
):
    """Get traffic statistics for a specific tunnel with time series data"""
    result = await db.execute(select(Tunnel).where(Tunnel.id == tunnel_id))
    tunnel = result.scalar_one_or_none()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    
    now = datetime.utcnow()
    start_time = now - timedelta(hours=hours)
    
    # Get time series data for this tunnel - aggregate usage by hour
    time_series_result = await db.execute(
        select(
            func.strftime('%Y-%m-%d %H:00:00', Usage.timestamp).label('hour'),
            func.sum(Usage.bytes_used).label('total_bytes')
        )
        .where(Usage.tunnel_id == tunnel_id)
        .where(Usage.timestamp >= start_time)
        .group_by('hour')
        .order_by('hour')
    )
    
    time_series_data = []
    for row in time_series_result.all():
        hour_str = row.hour
        total_bytes = row.total_bytes or 0
        # Convert bytes to MB
        total_mb_for_hour = total_bytes / (1024 * 1024)
        time_series_data.append({
            "timestamp": hour_str,
            "bytes": total_bytes,
            "mb": total_mb_for_hour
        })
    
    # Get current rate (traffic in last hour for this tunnel)
    one_hour_ago = now - timedelta(hours=1)
    recent_result = await db.execute(
        select(func.sum(Usage.bytes_used))
        .where(Usage.tunnel_id == tunnel_id)
        .where(Usage.timestamp >= one_hour_ago)
    )
    recent_bytes = recent_result.scalar() or 0
    current_rate_mb_per_hour = recent_bytes / (1024 * 1024)
    
    return {
        "tunnel_id": tunnel_id,
        "used_mb": tunnel.used_mb,
        "quota_mb": tunnel.quota_mb,
        "current_rate_mb_per_hour": current_rate_mb_per_hour,
        "time_series": time_series_data
    }


@router.get("/stats")
async def get_traffic_stats(
    hours: int = 24,
    db: AsyncSession = Depends(get_db)
):
    """Get aggregate traffic statistics with time series data"""
    now = datetime.utcnow()
    start_time = now - timedelta(hours=hours)
    
    # Get total traffic (sum of all tunnel.used_mb)
    total_result = await db.execute(
        select(func.sum(Tunnel.used_mb))
    )
    total_mb = total_result.scalar() or 0.0
    
    # Get time series data - aggregate usage by hour
    # For SQLite, we need to use strftime to group by hour
    time_series_result = await db.execute(
        select(
            func.strftime('%Y-%m-%d %H:00:00', Usage.timestamp).label('hour'),
            func.sum(Usage.bytes_used).label('total_bytes')
        )
        .where(Usage.timestamp >= start_time)
        .group_by('hour')
        .order_by('hour')
    )
    
    time_series_data = []
    for row in time_series_result.all():
        hour_str = row.hour
        total_bytes = row.total_bytes or 0
        # Convert bytes to MB
        total_mb_for_hour = total_bytes / (1024 * 1024)
        time_series_data.append({
            "timestamp": hour_str,
            "bytes": total_bytes,
            "mb": total_mb_for_hour
        })
    
    # Get current rate (traffic in last hour)
    one_hour_ago = now - timedelta(hours=1)
    recent_result = await db.execute(
        select(func.sum(Usage.bytes_used))
        .where(Usage.timestamp >= one_hour_ago)
    )
    recent_bytes = recent_result.scalar() or 0
    current_rate_mb_per_hour = recent_bytes / (1024 * 1024)
    
    return {
        "total_mb": total_mb,
        "total_bytes": int(total_mb * 1024 * 1024),
        "current_rate_mb_per_hour": current_rate_mb_per_hour,
        "time_series": time_series_data
    }


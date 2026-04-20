#!/usr/bin/env python3
"""
REST API for Amex Platinum Dining Map
Serves dining, plat stays, and love dining data with filtering and search.
"""

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import json
from pathlib import Path
from typing import Optional, List
from datetime import datetime
import csv
import io

# Initialize FastAPI app
app = FastAPI(
    title="Amex Platinum Dining Map API",
    description="Programmatic access to Amex dining partners, plat stays, and love dining venues",
    version="1.0.0"
)

# Enable CORS for cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data paths
DATA_DIR = Path(__file__).parent / "web" / "data"

def load_json(filename: str) -> list:
    """Load JSON data file."""
    path = DATA_DIR / filename
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)

def load_all_data():
    """Load all datasets."""
    return {
        "dining": load_json("japan-restaurants.json") + load_json("global-restaurants.json"),
        "stays": load_json("plat-stays.json"),
        "love_dining": load_json("love-dining.json"),
        "ratings": load_json("google-maps-ratings.json") or {}
    }

# Cache data on startup
DATA_CACHE = {}

@app.on_event("startup")
async def startup():
    """Load data on startup."""
    global DATA_CACHE
    DATA_CACHE = load_all_data()

def filter_records(records: list, search: Optional[str] = None, country: Optional[str] = None,
                  cuisine: Optional[str] = None, min_rating: Optional[float] = None) -> list:
    """Filter records based on criteria."""
    results = records

    if search:
        search_lower = search.lower()
        results = [r for r in results if
                  any(str(r.get(k, "")).lower().find(search_lower) >= 0
                      for k in ["name", "cuisine", "city", "country"])]

    if country:
        results = [r for r in results if r.get("country") == country]

    if cuisine:
        results = [r for r in results if cuisine in r.get("cuisines", []) or r.get("cuisine") == cuisine]

    if min_rating:
        results = [r for r in results if r.get("rating", 0) >= min_rating]

    return results

@app.get("/api/v1/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "dining_count": len(DATA_CACHE.get("dining", [])),
        "stays_count": len(DATA_CACHE.get("stays", [])),
        "love_dining_count": len(DATA_CACHE.get("love_dining", []))
    }

@app.get("/api/v1/dining")
async def get_dining(
    search: Optional[str] = Query(None, description="Search by name, cuisine, city"),
    country: Optional[str] = Query(None, description="Filter by country"),
    cuisine: Optional[str] = Query(None, description="Filter by cuisine"),
    min_rating: Optional[float] = Query(None, description="Minimum Google rating"),
    limit: int = Query(100, ge=1, le=1000, description="Results limit"),
    skip: int = Query(0, ge=0, description="Results to skip for pagination")
):
    """Get dining venues with optional filtering."""
    dining = DATA_CACHE.get("dining", [])
    filtered = filter_records(dining, search, country, cuisine, min_rating)
    return {
        "total": len(filtered),
        "limit": limit,
        "skip": skip,
        "results": filtered[skip:skip+limit]
    }

@app.get("/api/v1/stays")
async def get_stays(
    search: Optional[str] = Query(None, description="Search by property name, city, country"),
    country: Optional[str] = Query(None, description="Filter by country"),
    min_rating: Optional[float] = Query(None, description="Minimum Google rating"),
    limit: int = Query(100, ge=1, le=1000, description="Results limit"),
    skip: int = Query(0, ge=0, description="Results to skip for pagination")
):
    """Get Plat Stay properties with optional filtering."""
    stays = DATA_CACHE.get("stays", [])
    filtered = filter_records(stays, search, country, min_rating=min_rating)
    return {
        "total": len(filtered),
        "limit": limit,
        "skip": skip,
        "results": filtered[skip:skip+limit]
    }

@app.get("/api/v1/love-dining")
async def get_love_dining(
    search: Optional[str] = Query(None, description="Search by venue name, cuisine, hotel"),
    cuisine: Optional[str] = Query(None, description="Filter by cuisine"),
    venue_type: Optional[str] = Query(None, description="Filter by type (restaurant/hotel)"),
    min_rating: Optional[float] = Query(None, description="Minimum Google rating"),
    limit: int = Query(100, ge=1, le=1000, description="Results limit"),
    skip: int = Query(0, ge=0, description="Results to skip for pagination")
):
    """Get Love Dining Singapore venues with optional filtering."""
    love = DATA_CACHE.get("love_dining", [])
    filtered = love

    if search:
        search_lower = search.lower()
        filtered = [r for r in filtered if
                   any(str(r.get(k, "")).lower().find(search_lower) >= 0
                       for k in ["name", "cuisine", "hotel"])]

    if cuisine:
        filtered = [r for r in filtered if r.get("cuisine") == cuisine]

    if venue_type:
        filtered = [r for r in filtered if r.get("type") == venue_type]

    if min_rating:
        filtered = [r for r in filtered if r.get("rating", 0) >= min_rating]

    return {
        "total": len(filtered),
        "limit": limit,
        "skip": skip,
        "results": filtered[skip:skip+limit]
    }

@app.get("/api/v1/search")
async def search_all(
    q: str = Query(..., description="Search query across all datasets"),
    limit: int = Query(50, ge=1, le=500, description="Results limit")
):
    """Search across all datasets (dining, stays, love dining)."""
    search_lower = q.lower()

    results = {
        "dining": [],
        "stays": [],
        "love_dining": []
    }

    # Search dining
    for record in DATA_CACHE.get("dining", [])[:limit]:
        if any(str(record.get(k, "")).lower().find(search_lower) >= 0
               for k in ["name", "cuisine", "city", "country"]):
            results["dining"].append(record)

    # Search stays
    for record in DATA_CACHE.get("stays", [])[:limit]:
        if any(str(record.get(k, "")).lower().find(search_lower) >= 0
               for k in ["name", "city", "country"]):
            results["stays"].append(record)

    # Search love dining
    for record in DATA_CACHE.get("love_dining", [])[:limit]:
        if any(str(record.get(k, "")).lower().find(search_lower) >= 0
               for k in ["name", "cuisine", "hotel"]):
            results["love_dining"].append(record)

    return {
        "query": q,
        "results": results,
        "total": sum(len(v) for v in results.values())
    }

@app.get("/api/v1/export/csv")
async def export_csv(
    dataset: str = Query("dining", regex="^(dining|stays|love_dining)$"),
    search: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    cuisine: Optional[str] = Query(None)
):
    """Export filtered dataset as CSV."""
    if dataset == "dining":
        records = filter_records(DATA_CACHE.get("dining", []), search, country, cuisine)
    elif dataset == "stays":
        records = filter_records(DATA_CACHE.get("stays", []), search, country)
    else:
        records = DATA_CACHE.get("love_dining", [])
        if search:
            search_lower = search.lower()
            records = [r for r in records if
                      any(str(r.get(k, "")).lower().find(search_lower) >= 0
                          for k in ["name", "cuisine", "hotel"])]

    if not records:
        return {"error": "No records to export"}

    # Generate CSV
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=records[0].keys())
    writer.writeheader()
    writer.writerows(records)

    csv_str = output.getvalue()

    return StreamingResponse(
        iter([csv_str]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={dataset}-{datetime.now().strftime('%Y-%m-%d')}.csv"}
    )

@app.get("/api/v1/stats")
async def get_stats():
    """Get global statistics."""
    dining = DATA_CACHE.get("dining", [])
    stays = DATA_CACHE.get("stays", [])
    love = DATA_CACHE.get("love_dining", [])

    return {
        "dining": {
            "total": len(dining),
            "countries": len(set(r.get("country") for r in dining if r.get("country"))),
            "cities": len(set(r.get("city") for r in dining if r.get("city")))
        },
        "stays": {
            "total": len(stays),
            "countries": len(set(r.get("country") for r in stays if r.get("country")))
        },
        "love_dining": {
            "total": len(love),
            "cuisines": len(set(r.get("cuisine") for r in love if r.get("cuisine")))
        }
    }

@app.get("/")
async def root():
    """API documentation."""
    return {
        "name": "Amex Platinum Dining Map API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/api/v1/health",
            "dining": "/api/v1/dining",
            "stays": "/api/v1/stays",
            "love_dining": "/api/v1/love-dining",
            "search": "/api/v1/search",
            "export": "/api/v1/export/csv",
            "stats": "/api/v1/stats"
        },
        "docs": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
